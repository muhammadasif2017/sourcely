"""Documents and chunks on pgvector, isolated per workspace by row-level security (Task 16).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A row is visible, and may be written, only when its workspace is the one the API set for
# this transaction (`SELECT set_config('app.workspace_id', ..., true)`). With the setting
# absent, current_setting(..., true) is NULL (or '' on a reused connection, hence NULLIF), the
# comparison is NULL, and no row matches: forgetting to set it hides everything.
TENANT_CHECK = "workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"


def upgrade() -> None:
    """Tables, the vector index, row-level security, and a chunk count for /health."""
    op.create_table(
        "documents",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_documents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "document_id", name=op.f("pk_documents")),
    )
    op.create_table(
        "chunks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("embedding", Vector(dim=384), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.document_id"],
            name=op.f("fk_chunks_workspace_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "document_id", "chunk_index", name=op.f("pk_chunks")
        ),
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    for table in ("documents", "chunks"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_CHECK}) WITH CHECK ({TENANT_CHECK})"
        )

    # /health reports the deployment-wide chunk count, which row-level security would hide
    # from the app role. This function runs with its owner's rights (SECURITY DEFINER) and
    # returns only a number, never rows. search_path is pinned so it can't be hijacked.
    op.execute(
        """
        CREATE FUNCTION chunk_count() RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS 'SELECT count(*) FROM chunks'
        """
    )
    op.execute("REVOKE ALL ON FUNCTION chunk_count() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION chunk_count() TO sourcely_app")


def downgrade() -> None:
    """Drop the function, the policies and the tables."""
    op.execute("DROP FUNCTION IF EXISTS chunk_count()")
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks", postgresql_using="hnsw")
    op.drop_table("chunks")
    op.drop_table("documents")
