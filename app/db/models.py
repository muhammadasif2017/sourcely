"""Every table, defined in one place so Alembic's autogenerate sees the full schema.

Phase 1 adds tables task by task: accounts (Task 13), workspaces (Task 14), API keys
(Task 15), documents and chunks (Task 16). Migrations in `migrations/versions/` create them.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """A person who can sign in. `email` is case-insensitive (citext) and unique."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str]
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_column()


class AuthSession(Base):
    """A signed-in browser. Only the SHA-256 of the cookie value is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Compared with the X-CSRF-Token header on every write made with this session.
    csrf_token: Mapped[str]
    created_at: Mapped[datetime] = _now_column()
    last_seen_at: Mapped[datetime] = _now_column()


class EmailToken(Base):
    """A single-use link sent by email: address verification or password reset."""

    __tablename__ = "email_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('verify', 'reset')", name="purpose"),)

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    """One failed sign-in, kept to throttle guessing. Old rows simply stop counting."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_email_attempted_at", "email", "attempted_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT)
    attempted_at: Mapped[datetime] = _now_column()


class Workspace(Base):
    """The unit of isolation: documents, keys and members all belong to one workspace."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = _now_column()


class Membership(Base):
    """A user's role in a workspace: owner, admin, editor or viewer."""

    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'editor', 'viewer')", name="role"),
        # Exactly one owner per workspace, enforced by the database itself: a partial unique
        # index over the owner rows only.
        Index(
            "uq_memberships_one_owner",
            "workspace_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _now_column()


class ApiKey(Base):
    """A workspace's API key. Only its SHA-256 and its first 12 characters are stored."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(60))
    # Shown in lists so people can tell keys apart, e.g. "sk_live_7Hq2".
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    # Kept when the creator leaves: the key belongs to the workspace, not the person.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _now_column()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# The embedding column's size. Must equal Settings.embedding_dim, which startup checks against
# the model; changing it means a migration that rebuilds the column.
EMBEDDING_DIM = 384


class Document(Base):
    """A document in a workspace. Its text lives in its chunks.

    Row-level security (migration 0005) limits every query to the workspace named in the
    `app.workspace_id` setting of the current transaction.
    """

    __tablename__ = "documents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    # The PoC id rule (^[A-Za-z0-9._-]{1,128}$); unique per workspace, not globally.
    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    metadata_: Mapped[dict[str, str | int | float | bool]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _now_column()
    updated_at: Mapped[datetime] = _now_column()


class Chunk(Base):
    """One chunk of a document, with its embedding."""

    __tablename__ = "chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.document_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    chunk_index: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class Invite(Base):
    """A pending invitation to join a workspace. Only the token's SHA-256 is stored."""

    __tablename__ = "invites"
    __table_args__ = (
        # Invites can't create owners: ownership only moves by transfer.
        CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(CITEXT)
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _now_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
