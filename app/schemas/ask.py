"""Request and response models for answering questions."""

from pydantic import BaseModel, Field, field_validator

from app.schemas.search import MAX_QUERY_CHARS, MAX_TOP_K, SearchFilters, SearchHit


class AskRequest(BaseModel):
    """A question. `top_k` falls back to the `DEFAULT_TOP_K` setting when omitted."""

    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int | None = Field(None, ge=1, le=MAX_TOP_K)
    filters: SearchFilters | None = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, question: str) -> str:
        if not question.strip():
            raise ValueError("question must contain non-whitespace characters")
        return question


class AskResponse(BaseModel):
    """The answer, the chunks it cites as `[n]` (in order), and the model that wrote it."""

    answer: str
    sources: list[SearchHit]
    provider: str
    model: str
