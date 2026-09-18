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
