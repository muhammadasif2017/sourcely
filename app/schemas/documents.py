"""Request and response models for document ingestion."""

import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

# Chroma stores only scalar metadata values. NaN and infinity are not valid JSON numbers.
MetadataValue = str | int | Annotated[float, Field(allow_inf_nan=False)] | bool

DOCUMENT_ID_PATTERN = r"^[A-Za-z0-9._-]{1,128}$"
RESERVED_METADATA_KEYS = frozenset({"document_id", "chunk_index", "title"})
MAX_METADATA_KEYS = 20
_METADATA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


class DocumentCreate(BaseModel):
    """One text document to ingest. The size limit is checked in the route (413, not 422)."""

    text: str
    document_id: str | None = Field(None, pattern=DOCUMENT_ID_PATTERN)
    title: str | None = Field(None, max_length=200)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("text must contain non-whitespace characters")
        return text

    @field_validator("metadata")
    @classmethod
    def _check_metadata_keys(cls, metadata: dict[str, MetadataValue]) -> dict[str, MetadataValue]:
        if len(metadata) > MAX_METADATA_KEYS:
            raise ValueError(f"metadata allows at most {MAX_METADATA_KEYS} keys")
        for key in metadata:
            if key in RESERVED_METADATA_KEYS:
                raise ValueError(f"metadata key '{key}' is reserved")
            if not _METADATA_KEY.match(key):
                raise ValueError(
                    f"metadata key '{key}' must start with a letter and contain only "
                    "letters, digits and underscores (max 64 characters)"
                )
        return metadata


class DocumentCreated(BaseModel):
    """Summary of an ingested document."""

    document_id: str
    title: str
    chunks: int
    characters: int
