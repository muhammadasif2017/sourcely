"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.embeddings import BGE_QUERY_PREFIX


class Settings(BaseSettings):
    """All runtime configuration. Field names map to upper-case env vars (e.g. `CHUNK_SIZE`)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    openai_base_url: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    llm_max_tokens: int = Field(16_000, ge=1)
    llm_timeout_seconds: float = Field(120.0, gt=0)

    # Embeddings and storage
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = "./data/models"
    # Prepended to queries only. Set to "" for models without a retrieval instruction.
    embedding_query_prefix: str = BGE_QUERY_PREFIX
    # Must match the model's output and the `vector(...)` column. Checked at startup.
    embedding_dim: int = Field(384, ge=1)
    chroma_path: str = "./data/chroma"
    collection_name: str = "documents"

    # Database. The API connects as a role that owns no table, so row-level security always
    # applies to it; migrations run as the owner. See SPEC.md, Phase 1.
    database_url: str = "postgresql+psycopg://sourcely_app:sourcely_app@127.0.0.1:5434/sourcely"
    migration_database_url: str = (
        "postgresql+psycopg://sourcely_owner:sourcely_owner@127.0.0.1:5434/sourcely"
    )

    # Accounts and sessions
    # Secure cookies are only sent over HTTPS. Set to false only for plain-HTTP local work.
    cookie_secure: bool = True
    session_idle_days: int = Field(14, ge=1)
    email_backend: Literal["console"] = "console"
    # Where links in emails point (the future web app).
    app_base_url: str = "http://localhost:8000"

    # Chunking and retrieval
    chunk_size: int = Field(800, ge=50)
    chunk_overlap: int = Field(120, ge=0)
    max_document_chars: int = Field(200_000, ge=1)
    # Whole request body. 2 MiB admits a maximum-size document even when every character is
    # JSON-escaped as a 6-byte \u escape, plus room for the rest of the body.
    max_request_bytes: int = Field(2 * 1024 * 1024, ge=1024)
    default_top_k: int = Field(4, ge=1, le=20)
    # Calibrated at Checkpoint B for bge-small with the query prefix (see SPEC.md).
    min_relevance: float = Field(0.58, ge=-1.0, le=1.0)

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_chunking(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self

    @property
    def llm_model(self) -> str:
        """Model name for the active provider."""
        return self.anthropic_model if self.llm_provider == "anthropic" else self.openai_model

    @property
    def llm_api_key(self) -> str | None:
        """API key for the active provider, or None when missing or blank."""
        key = self.anthropic_api_key if self.llm_provider == "anthropic" else self.openai_api_key
        return key.strip() or None if key else None

    @property
    def llm_configured(self) -> bool:
        """True when the active provider has a key, so `/ask` can run."""
        return self.llm_api_key is not None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    return Settings()
