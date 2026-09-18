"""Request and response models for semantic search."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.documents import DOCUMENT_ID_PATTERN, MetadataValue, check_metadata_keys
from app.services.vector_store import ChunkHit

MAX_QUERY_CHARS = 2000
MAX_TOP_K = 20
MAX_FILTER_DOCUMENT_IDS = 100
MAX_FILTER_METADATA_PAIRS = 10

DocumentId = Annotated[str, StringConstraints(pattern=DOCUMENT_ID_PATTERN)]


class SearchFilters(BaseModel):
    """Restricts which chunks can match. A chunk must satisfy every field that is given."""

    # A misspelled field would otherwise be ignored silently, and everything would match.
    model_config = ConfigDict(extra="forbid")

    document_ids: list[DocumentId] | None = Field(
        None, min_length=1, max_length=MAX_FILTER_DOCUMENT_IDS
    )
    metadata: dict[str, MetadataValue] | None = Field(None, min_length=1)

    @field_validator("metadata")
    @classmethod
    def _check_metadata(
        cls, metadata: dict[str, MetadataValue] | None
    ) -> dict[str, MetadataValue] | None:
        if metadata is None:
            return None
        return check_metadata_keys(metadata, MAX_FILTER_METADATA_PAIRS)


class SearchRequest(BaseModel):
    """A search query. `top_k` falls back to the `DEFAULT_TOP_K` setting when omitted."""

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int | None = Field(None, ge=1, le=MAX_TOP_K)
    filters: SearchFilters | None = None

    @field_validator("query")
    @classmethod
    def _query_not_blank(cls, query: str) -> str:
        if not query.strip():
            raise ValueError("query must contain non-whitespace characters")
        return query


class SearchHit(BaseModel):
    """One matching chunk. `score` is cosine similarity: higher means more similar."""

    document_id: str
    chunk_index: int
    title: str
    text: str
    score: float
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_chunk(cls, hit: ChunkHit) -> "SearchHit":
        """Build the response shape from a vector-store hit."""
        return cls(
            document_id=hit.document_id,
            chunk_index=hit.chunk_index,
            title=hit.title,
            text=hit.text,
            score=hit.score,
            metadata=hit.metadata,
        )


class SearchResponse(BaseModel):
    """Matching chunks, sorted from most to least similar."""

    query: str
    results: list[SearchHit]
