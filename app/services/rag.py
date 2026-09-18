"""Retrieval-augmented answering: retrieve relevant chunks, then ask the LLM about them."""

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain

from app.services.embeddings import Embedder
from app.services.llm import LLM, NO_ANSWER, SYSTEM_PROMPT, LLMError, build_user_prompt
from app.services.vector_store import ChunkHit, VectorStore, Where

NO_CONTEXT_ANSWER = (
    "There is not enough information in the indexed documents to answer this question."
)


@dataclass(frozen=True)
class RagAnswer:
    """An answer with the chunks it was grounded in, and who generated it."""

    answer: str
    sources: list[ChunkHit]
    provider: str
    model: str


def retrieve_relevant(
    question: str,
    top_k: int,
    min_relevance: float,
    embedder: Embedder,
    store: VectorStore,
    where: Where | None = None,
) -> list[ChunkHit]:
    """The `top_k` nearest chunks that match `where` and score at least `min_relevance`."""
    hits = store.query(embedder.embed_query(question), top_k, where)
    return [hit for hit in hits if hit.score >= min_relevance]


def answer_question(
    question: str,
    top_k: int,
    min_relevance: float,
    embedder: Embedder,
    store: VectorStore,
    llm: LLM,
    where: Where | None = None,
) -> RagAnswer:
    """Answer from retrieved context. Raises `LLMError` when the provider fails.

    When no chunk is relevant enough, the LLM is not called at all: it saves the cost, and it
    avoids a confident answer built on unrelated text.
    """
    sources = retrieve_relevant(question, top_k, min_relevance, embedder, store, where)
    if not sources:
        return RagAnswer(NO_CONTEXT_ANSWER, [], llm.provider, llm.model)
    result = llm.complete(SYSTEM_PROMPT, build_user_prompt(question, sources))
    return RagAnswer(result.text, sources, llm.provider, result.model)


@dataclass(frozen=True)
class RagStream:
    """A streamed answer: its sources and generator are known before any byte is sent."""

    sources: list[ChunkHit]
    provider: str
    model: str
    tokens: Iterator[str]


def start_answer_stream(
    question: str,
    top_k: int,
    min_relevance: float,
    embedder: Embedder,
    store: VectorStore,
    llm: LLM,
    where: Where | None = None,
) -> RagStream:
    """Retrieve context and start streaming the answer.

    The first token is fetched here, before the caller sends any response headers. A missing
    key, a rejected request, a rate limit or a timeout therefore raises `LLMError` now and can
    still become a normal HTTP error. Only failures after the first token happen mid-stream.
    """
    sources = retrieve_relevant(question, top_k, min_relevance, embedder, store, where)
    if not sources:
        return RagStream([], llm.provider, llm.model, iter([NO_CONTEXT_ANSWER]))
    tokens = llm.stream(SYSTEM_PROMPT, build_user_prompt(question, sources))
    try:
        first = next(tokens)
    except StopIteration as exc:
        raise LLMError(502, NO_ANSWER) from exc
    return RagStream(sources, llm.provider, llm.model, chain([first], tokens))
