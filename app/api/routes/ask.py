"""Question answering routes: a complete answer, or the same answer streamed as it's written."""

import json
import logging
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.auth import IndexDep, PrincipalDep, require
from app.api.deps import EmbedderDep, LLMDep, SettingsDep
from app.core.errors import AppError
from app.schemas.ask import AskRequest, AskResponse
from app.schemas.search import SearchHit
from app.services.llm import LLM, LLMError
from app.services.rag import RagStream, answer_question, start_answer_stream

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])

STREAM_INTERRUPTED = "The answer was interrupted"


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    settings: SettingsDep,
    embedder: EmbedderDep,
    principal: PrincipalDep,
    index: IndexDep,
    llm: LLMDep,
) -> AskResponse:
    """Answer a question from the stored documents, citing the sources used as [n]."""
    require(principal, "read")
    configured = _require(llm)
    try:
        result = answer_question(
            body.question,
            body.top_k or settings.default_top_k,
            settings.min_relevance,
            embedder,
            index,
            configured,
            body.filters.to_filter() if body.filters else None,
        )
    except LLMError as exc:
        raise AppError(exc.status_code, exc.detail) from exc
    return AskResponse(
        answer=result.answer,
        sources=[SearchHit.from_chunk(hit) for hit in result.sources],
        provider=result.provider,
        model=result.model,
    )


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-Sent Events"}},
)
def ask_stream(
    body: AskRequest,
    settings: SettingsDep,
    embedder: EmbedderDep,
    principal: PrincipalDep,
    index: IndexDep,
    llm: LLMDep,
) -> StreamingResponse:
    """Stream the answer as Server-Sent Events: `sources`, then `token` events, then `done`.

    Errors before the first token return a normal HTTP status. An error after it arrives as an
    `error` event, because the 200 status has already been sent.
    """
    require(principal, "read")
    configured = _require(llm)
    try:
        stream = start_answer_stream(
            body.question,
            body.top_k or settings.default_top_k,
            settings.min_relevance,
            embedder,
            index,
            configured,
            body.filters.to_filter() if body.filters else None,
        )
    except LLMError as exc:
        raise AppError(exc.status_code, exc.detail) from exc
    return StreamingResponse(
        _sse_events(stream),
        media_type="text/event-stream",
        # Proxies such as nginx buffer responses by default, which would hold every token back.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _require(llm: LLM | None) -> LLM:
    """The configured LLM, or a 503 when its API key is missing."""
    if llm is None:
        raise AppError(status.HTTP_503_SERVICE_UNAVAILABLE, "LLM provider not configured")
    return llm


def _sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event. JSON keeps newlines in the text from breaking the framing."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_events(stream: RagStream) -> Iterator[str]:
    """Format a started answer stream as Server-Sent Events."""
    sources = [SearchHit.from_chunk(hit).model_dump() for hit in stream.sources]
    yield _sse("sources", {"sources": sources, "provider": stream.provider, "model": stream.model})
    try:
        for text in stream.tokens:
            yield _sse("token", {"text": text})
    except LLMError as exc:
        yield _sse("error", {"detail": exc.detail})
        return
    except Exception:
        # The 200 status is already sent, so the generic 500 handler can't run. Log the trace
        # and send a safe message instead.
        logger.exception("answer stream failed after the first token")
        yield _sse("error", {"detail": STREAM_INTERRUPTED})
        return
    yield _sse("done", {})
