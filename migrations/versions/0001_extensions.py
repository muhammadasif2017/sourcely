"""Extensions: pgvector for embeddings, citext for case-insensitive emails.

Revision ID: 0001
Revises:
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make sure the extensions exist.

    Creating an extension needs a superuser, so `docker/postgres/init.sql` and the test
    fixtures create them first. Here `IF NOT EXISTS` makes this a check, not a privilege need.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    """Keep the extensions: other objects may depend on them, and the owner can't drop them."""
