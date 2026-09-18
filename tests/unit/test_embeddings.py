"""FastEmbedEmbedder with a fake fastembed model: the query prefix reaches queries only."""

import fastembed
import pytest

from app.services.embeddings import BGE_QUERY_PREFIX, FastEmbedEmbedder


class _Vec(list):
    def tolist(self) -> list[float]:
        return list(self)


class FakeTextEmbedding:
    """Records what fastembed would embed. Returns the text length as a 1-d vector."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.embedded: list[str] = []
        self.queried: list[str] = []

    def embed(self, texts: list[str]):
        self.embedded.extend(texts)
        return iter(_Vec([float(len(t))]) for t in texts)

    def query_embed(self, text: str):
        self.queried.append(text)
        return iter([_Vec([float(len(text))])])


@pytest.fixture(autouse=True)
def fake_fastembed(monkeypatch):
    monkeypatch.setattr(fastembed, "TextEmbedding", FakeTextEmbedding)


def test_query_gets_the_prefix():
    embedder = FastEmbedEmbedder("bge", query_prefix=BGE_QUERY_PREFIX)
    embedder.embed_query("how many leave days")
    assert embedder._model.queried == [BGE_QUERY_PREFIX + "how many leave days"]


def test_documents_never_get_the_prefix():
    embedder = FastEmbedEmbedder("bge", query_prefix=BGE_QUERY_PREFIX)
    embedder.embed_documents(["Leave policy text."])
    assert embedder._model.embedded == ["Leave policy text."]


def test_empty_prefix_leaves_the_query_unchanged():
    embedder = FastEmbedEmbedder("bge", query_prefix="")
    embedder.embed_query("plain")
    assert embedder._model.queried == ["plain"]
