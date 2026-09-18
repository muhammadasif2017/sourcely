"""Question answering route."""

from fastapi import APIRouter, status

from app.api.deps import EmbedderDep, LLMDep, SettingsDep, StoreDep
from app.api.routes.search import where_from
from app.core.errors import AppError
from app.schemas.ask import AskRequest, AskResponse
from app.schemas.search import SearchHit
from app.services.llm import LLMError
from app.services.rag import answer_question

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    settings: SettingsDep,
    embedder: EmbedderDep,
    store: StoreDep,
    llm: LLMDep,
) -> AskResponse:
    """Answer a question from the stored documents, citing the sources used as [n]."""
    if llm is None:
        raise AppError(status.HTTP_503_SERVICE_UNAVAILABLE, "LLM provider not configured")
    try:
        result = answer_question(
            body.question,
            body.top_k or settings.default_top_k,
            settings.min_relevance,
            embedder,
            store,
            llm,
            where_from(body.filters),
        )
    except LLMError as exc:
        raise AppError(exc.status_code, exc.detail) from exc
    return AskResponse(
        answer=result.answer,
        sources=[SearchHit.from_chunk(hit) for hit in result.sources],
        provider=result.provider,
        model=result.model,
    )
