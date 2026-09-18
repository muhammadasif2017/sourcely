"""Request and response models for semantic search."""

from pydantic import BaseModel, Field, field_validator

from app.schemas.documents import MetadataValue

MAX_QUERY_CHARS = 2000
MAX_TOP_K = 20


class SearchRequest(BaseModel):
    """A search query. `top_k` falls back to the `DEFAULT_TOP_K` setting when omitted."""

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int | None = Field(None, ge=1, le=MAX_TOP_K)

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


class SearchResponse(BaseModel):
    """Matching chunks, sorted from most to least similar."""

    query: str
    results: list[SearchHit]
