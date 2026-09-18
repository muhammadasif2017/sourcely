"""Vector storage on a ChromaDB collection using cosine distance."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from chromadb.api import ClientAPI

Metadata = Mapping[str, str | int | float | bool]

# Stored on every chunk by `replace_document`. Hits expose them as their own fields.
_RESERVED_KEYS = frozenset({"document_id", "chunk_index", "title"})


@dataclass(frozen=True)
class ChunkHit:
    """A stored chunk returned by a similarity query."""

    document_id: str
    chunk_index: int
    title: str
    text: str
    score: float
    metadata: dict[str, str | int | float | bool]


@dataclass(frozen=True)
class StoredDocument:
    """One stored document, rebuilt from its chunks' metadata."""

    document_id: str
    title: str
    chunks: int
    metadata: dict[str, str | int | float | bool]


class VectorStore:
    """Stores document chunks with their embeddings and metadata."""

    def __init__(self, client: ClientAPI, collection_name: str) -> None:
        # embedding_function=None: we always pass our own vectors, and it stops Chroma
        # from downloading its default model.
        self._collection = client.get_or_create_collection(
            collection_name,
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=None,
        )

    def count(self) -> int:
        """Number of chunks stored."""
        return self._collection.count()

    def list_documents(self) -> list[StoredDocument]:
        """Every stored document with its chunk count, sorted by `document_id`.

        Chroma has no document table, so this reads every chunk's metadata: the cost grows with
        the number of chunks. Fine for a PoC, and noted in SPEC.md as a scaling limit.
        """
        metadatas = self._collection.get(include=["metadatas"])["metadatas"] or []
        counts: dict[str, int] = {}
        first: dict[str, Mapping[str, object]] = {}
        for meta in metadatas:
            if meta is None:
                continue
            document_id = str(meta["document_id"])
            counts[document_id] = counts.get(document_id, 0) + 1
            # Every chunk of a document carries the same title and metadata.
            first.setdefault(document_id, meta)
        return [
            StoredDocument(
                document_id=document_id,
                title=str(first[document_id].get("title", "")),
                chunks=counts[document_id],
                metadata=_client_metadata(first[document_id]),
            )
            for document_id in sorted(counts)
        ]

    def delete_document(self, document_id: str) -> bool:
        """Delete every chunk of a document. Returns False when it had no chunks."""
        existing = self._collection.get(where={"document_id": document_id}, limit=1, include=[])
        if not existing["ids"]:
            return False
        self._collection.delete(where={"document_id": document_id})
        return True

    def query(self, embedding: Sequence[float], top_k: int) -> list[ChunkHit]:
        """Return up to `top_k` chunks nearest to `embedding`, most similar first.

        The collection uses cosine distance, so `score = 1 - distance` is cosine similarity.
        An empty collection returns `[]`.
        """
        vector: list[Sequence[float]] = [embedding]
        result = self._collection.query(
            query_embeddings=vector,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        # One query vector in, so every result list holds exactly one inner list.
        ids = result["ids"][0]
        documents = (result["documents"] or [[]])[0]
        metadatas = (result["metadatas"] or [[]])[0]
        distances = (result["distances"] or [[]])[0]
        hits: list[ChunkHit] = []
        for i in range(len(ids)):
            meta = metadatas[i] or {}
            hits.append(
                ChunkHit(
                    document_id=str(meta["document_id"]),
                    chunk_index=int(str(meta["chunk_index"])),
                    title=str(meta.get("title", "")),
                    text=documents[i] or "",
                    score=1.0 - float(distances[i]),
                    metadata=_client_metadata(meta),
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits

    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadata: Metadata,
        title: str,
    ) -> None:
        """Store a document's chunks as `{document_id}:{i}`, replacing any previous version.

        Old chunks are deleted by their `document_id` metadata, not by computed ids, so a
        shorter new version leaves no orphan chunks behind.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        self._collection.delete(where={"document_id": document_id})
        if not chunks:
            return
        vectors: list[Sequence[float]] = list(embeddings)
        self._collection.add(
            ids=[f"{document_id}:{i}" for i in range(len(chunks))],
            documents=list(chunks),
            embeddings=vectors,
            metadatas=[
                {**metadata, "document_id": document_id, "chunk_index": i, "title": title}
                for i in range(len(chunks))
            ],
        )


def _client_metadata(meta: Mapping[str, object]) -> dict[str, str | int | float | bool]:
    """The client's own metadata: stored keys minus the ones the store reserves."""
    return {
        key: value
        for key, value in meta.items()
        if key not in _RESERVED_KEYS and isinstance(value, str | int | float | bool)
    }
