"""Vector storage on a ChromaDB collection using cosine distance."""

from collections.abc import Mapping, Sequence

from chromadb.api import ClientAPI

Metadata = Mapping[str, str | int | float | bool]


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
