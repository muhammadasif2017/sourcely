import hashlib
import math
import re
import uuid
from collections.abc import Iterator

import chromadb
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.llm import LLMAnswer
from app.services.vector_store import VectorStore

DIM = 256
_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic hashed bag-of-words embedder.

    Texts that share words get similar vectors, so ranking in tests behaves like a
    real (if crude) semantic model without downloading anything.
    """

    model_name = "fake-embedder"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for word in _WORD.findall(text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeLLM:
    """Records every prompt and returns a fixed answer, or raises `error` when set."""

    provider = "fake-provider"
    model = "fake-model"

    def __init__(self, answer: str = "Cats purr when content [1].") -> None:
        self.answer = answer
        self.error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> LLMAnswer:
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return LLMAnswer(text=self.answer, model=self.model)

    # Streaming: `error` fires before the first token; `mid_stream_error` after
    # `tokens_before_error` tokens.
    mid_stream_error: Exception | None = None
    tokens_before_error: int = 2

    def stream(self, system: str, user: str) -> Iterator[str]:
        self.calls.append((system, user))
        if self.error:
            raise self.error
        for i, token in enumerate(self.answer.split(" ")):
            if self.mid_stream_error and i == self.tokens_before_error:
                raise self.mid_stream_error
            yield token if i == 0 else " " + token


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="test-key",
        openai_model="fake-model",
        chunk_size=200,
        chunk_overlap=40,
        max_document_chars=5_000,
        min_relevance=0.2,
    )


@pytest.fixture
def store() -> VectorStore:
    # Ephemeral clients share one in-process database, so each test needs its own collection.
    return VectorStore(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex}")


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(settings, store, embedder, llm):
    app = create_app(settings, embedder=embedder, store=store, llm=llm)
    with TestClient(app) as c:
        yield c
