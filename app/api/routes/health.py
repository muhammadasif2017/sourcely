"""Health check route."""

from fastapi import APIRouter, status

from app.api.deps import EmbedderDep, EngineDep, SettingsDep, StoreDep
from app.core.errors import AppError
from app.db.engine import database_ok
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(
    settings: SettingsDep, embedder: EmbedderDep, store: StoreDep, engine: EngineDep
) -> HealthResponse:
    """Report liveness, database reachability, index size and which models are configured."""
    # 503 rather than a 200 with "database: down": container health checks and load balancers
    # look at the status code, and the API can't serve requests without its database.
    if not database_ok(engine):
        raise AppError(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable")
    return HealthResponse(
        status="ok",
        database="ok",
        chunks_indexed=store.count(),
        embedding_model=embedder.model_name,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_configured=settings.llm_configured,
    )
