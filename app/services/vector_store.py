"""Vector storage on a ChromaDB collection using cosine distance."""

from chromadb.api import ClientAPI


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
