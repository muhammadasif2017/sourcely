"""Text embedding: a small protocol plus the local fastembed implementation."""

from typing import Protocol


class Embedder(Protocol):
    """Anything that turns text into vectors. Tests supply a fake."""

    model_name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        ...


class FastEmbedEmbedder:
    """Local ONNX embeddings via fastembed. Downloads the model on first use."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        # Imported here so tests that inject a fake never load onnxruntime.
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage."""
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        """Embed a query. bge models expect a query instruction, which `query_embed` adds."""
        vector: list[float] = next(iter(self._model.query_embed(text))).tolist()
        return vector
