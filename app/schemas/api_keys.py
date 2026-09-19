"""Request and response models for API keys."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

KeyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class ApiKeyCreate(BaseModel):
    """A name to recognise the key by, such as the integration that uses it."""

    name: KeyName


class ApiKeyOut(BaseModel):
    """A key as listed: never the secret, only its first characters."""

    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(BaseModel):
    """A new key. `key` is the full secret and is shown only in this response."""

    id: uuid.UUID
    name: str
    prefix: str
    key: str
    created_at: datetime


class ApiKeyList(BaseModel):
    """A workspace's keys, newest first."""

    api_keys: list[ApiKeyOut]
