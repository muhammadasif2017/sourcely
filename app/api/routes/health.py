"""Health check route."""

from fastapi import APIRouter

from app.api.deps import EmbedderDep, SettingsDep, StoreDep
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep, embedder: EmbedderDep, store: StoreDep) -> HealthResponse:
    """Report liveness, index size and which models are configured."""
    return HealthResponse(
        status="ok",
        chunks_indexed=store.count(),
        embedding_model=embedder.model_name,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_configured=settings.llm_configured,
    )
