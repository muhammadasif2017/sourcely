"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    chroma_path: str = "./data/chroma"
    collection_name: str = "documents"

    # Chunking and retrieval
    chunk_size: int = Field(800, ge=50)
    chunk_overlap: int = Field(120, ge=0)
    max_document_chars: int = Field(200_000, ge=1)
    default_top_k: int = Field(4, ge=1, le=20)
    min_relevance: float = Field(0.5, ge=-1.0, le=1.0)

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
