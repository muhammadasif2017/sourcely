"""API keys: creating, listing, revoking, and resolving a presented key."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.db.models import ApiKey

KEY_PREFIX = "sk_live_"
# Enough of the key to tell keys apart in a list, far too little to guess the rest.
SHOWN_PREFIX_LENGTH = 12
# `last_used_at` is written at most this often, so a busy integration doesn't cause a write on
# every request.
LAST_USED_RESOLUTION = timedelta(minutes=1)


@dataclass(frozen=True)
class CreatedKey:
    """A new key's row and its full secret. The secret is never available again."""

    row: ApiKey
    key: str


def generate_key() -> str:
    """`sk_live_` plus 32 random bytes, URL-safe (43 characters)."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def create_key(
    db: Session, workspace_id: uuid.UUID, name: str, created_by: uuid.UUID
) -> CreatedKey:
    """Store a new key for the workspace and return it with its secret."""
    key = generate_key()
    row = ApiKey(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=name,
        prefix=key[:SHOWN_PREFIX_LENGTH],
        key_hash=hash_token(key),
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return CreatedKey(row=row, key=key)


def list_keys(db: Session, workspace_id: uuid.UUID) -> list[ApiKey]:
    """The workspace's keys, revoked ones included, newest first."""
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.workspace_id == workspace_id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id)
        )
    )


def revoke_key(db: Session, workspace_id: uuid.UUID, key_id: uuid.UUID) -> bool:
    """Revoke a key of this workspace. False if the workspace has no such key.

    Revoking an already revoked key is allowed and keeps the original revocation time.
    """
    row = db.get(ApiKey, key_id)
    if row is None or row.workspace_id != workspace_id:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
    return True


def resolve_key(db: Session, key: str) -> ApiKey | None:
    """The active key matching a presented secret, or None. Updates `last_used_at`."""
    if not key.startswith(KEY_PREFIX):
        return None
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_token(key)))
    if row is None or row.revoked_at is not None:
        return None
    now = datetime.now(UTC)
    if row.last_used_at is None or row.last_used_at < now - LAST_USED_RESOLUTION:
        row.last_used_at = now
    return row
