"""Text embedding: a small protocol plus the local fastembed implementation."""

from typing import Protocol

# BAAI's retrieval instruction for bge English v1.5 models. It goes on queries only, never on
# passages. Measured at Checkpoint B: it widened the gap between relevant and unrelated
# scores from 0.020 to 0.052.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


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
    """Local ONNX embeddings via fastembed. Downloads the model on first use.

    `query_prefix` is prepended to queries (not to documents), for models trained with a
    retrieval instruction such as bge.
    """

    def __init__(
        self, model_name: str, cache_dir: str | None = None, query_prefix: str = ""
    ) -> None:
        # Imported here so tests that inject a fake never load onnxruntime.
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._query_prefix = query_prefix
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage."""
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query, with the query prefix in front.

        `query_embed` is fastembed's query-side entry point. For bge-small-en-v1.5 it returns the
        same vector as `embed` (verified): it does not add bge's query instruction itself, so
        the prefix is added here.
        """
        vector: list[float] = next(
            iter(self._model.query_embed(self._query_prefix + text))
        ).tolist()
        return vector
