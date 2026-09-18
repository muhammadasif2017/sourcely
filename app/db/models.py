"""Every table, defined in one place so Alembic's autogenerate sees the full schema.

Phase 1 adds tables task by task: accounts (Task 13), workspaces (Task 14), API keys
(Task 15), documents and chunks (Task 16). Migrations in `migrations/versions/` create them.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
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
