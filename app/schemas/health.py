"""Health check response model."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness plus a summary of the loaded components."""

    status: str
    chunks_indexed: int
    embedding_model: str
    llm_provider: str
    llm_model: str
    llm_configured: bool
