"""Retrieval-augmented answering: retrieve relevant chunks, then ask the LLM about them."""

from dataclasses import dataclass

from app.services.embeddings import Embedder
from app.services.llm import LLM, SYSTEM_PROMPT, build_user_prompt
from app.services.vector_store import ChunkHit, VectorStore

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
    question: str, top_k: int, min_relevance: float, embedder: Embedder, store: VectorStore
) -> list[ChunkHit]:
    """The `top_k` nearest chunks that score at least `min_relevance`, best first."""
    hits = store.query(embedder.embed_query(question), top_k)
    return [hit for hit in hits if hit.score >= min_relevance]


def answer_question(
    question: str,
    top_k: int,
    min_relevance: float,
    embedder: Embedder,
    store: VectorStore,
    llm: LLM,
) -> RagAnswer:
    """Answer from retrieved context. Raises `LLMError` when the provider fails.

    When no chunk is relevant enough, the LLM is not called at all: it saves the cost, and it
    avoids a confident answer built on unrelated text.
    """
    sources = retrieve_relevant(question, top_k, min_relevance, embedder, store)
    if not sources:
        return RagAnswer(NO_CONTEXT_ANSWER, [], llm.provider, llm.model)
    result = llm.complete(SYSTEM_PROMPT, build_user_prompt(question, sources))
    return RagAnswer(result.text, sources, llm.provider, result.model)
