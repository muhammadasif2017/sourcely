"""Vector storage on PostgreSQL with pgvector, one workspace at a time.

Every method takes the request's `Session` and a `workspace_id`. The queries filter by that
workspace, and row-level security (migration 0005) enforces it again underneath, using the
`app.workspace_id` setting that `set_workspace` puts on the transaction.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import and_, delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document

Metadata = Mapping[str, str | int | float | bool]


@dataclass(frozen=True)
class ChunkHit:
    """A stored chunk returned by a similarity query."""

    document_id: str
    chunk_index: int
    title: str
    text: str
    score: float
    metadata: dict[str, str | int | float | bool]


@dataclass(frozen=True)
class StoredDocument:
    """One stored document and how many chunks it has."""

    document_id: str
    title: str
    chunks: int
    metadata: dict[str, str | int | float | bool]


@dataclass(frozen=True)
class SearchFilter:
    """Which chunks may match. A chunk must satisfy every field that is set."""

    document_ids: tuple[str, ...] | None = None
    metadata: Mapping[str, str | int | float | bool] | None = None


def set_workspace(db: Session, workspace_id: uuid.UUID) -> None:
    """Scope this transaction to one workspace, for row-level security.

    `set_config(..., true)` is transaction-local, like `SET LOCAL`: it ends with the
    transaction, so a pooled connection never carries one request's workspace into the next.
    """
    db.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": str(workspace_id)},
    )


class PgVectorStore:
    """Documents and their chunk embeddings in Postgres, queried by cosine distance."""

    def count(self, db: Session) -> int:
        """Chunks stored across every workspace, for `/health`.

        Row-level security hides other workspaces' rows from the app role, so this calls
        `chunk_count()`, a function that returns only the number.
        """
        return int(db.scalar(text("SELECT chunk_count()")) or 0)

    def replace_document(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        document_id: str,
        chunks: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadata: Metadata,
        title: str,
    ) -> None:
        """Store a document's chunks, replacing any previous version in the same transaction.

        The old chunks are deleted and the new ones inserted together, so a reader sees either
        the old version or the new one, never a mix or an empty document.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        upsert = pg_insert(Document).values(
            workspace_id=workspace_id,
            document_id=document_id,
            title=title,
            metadata_=dict(metadata),
        )
        db.execute(
            upsert.on_conflict_do_update(
                index_elements=[Document.workspace_id, Document.document_id],
                set_={
                    "title": upsert.excluded.title,
                    "metadata": upsert.excluded.metadata,
                    "updated_at": func.now(),
                },
            )
        )
        db.execute(
            delete(Chunk).where(
                Chunk.workspace_id == workspace_id, Chunk.document_id == document_id
            )
        )
        if chunks:
            db.execute(
                insert(Chunk),
                [
                    {
                        "workspace_id": workspace_id,
                        "document_id": document_id,
                        "chunk_index": i,
                        "text": chunk,
                        "embedding": list(embedding),
                    }
                    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
                ],
            )

    def query(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        embedding: Sequence[float],
        top_k: int,
        search_filter: SearchFilter | None = None,
    ) -> list[ChunkHit]:
        """Return up to `top_k` chunks nearest to `embedding`, most similar first.

        `score` is cosine similarity, `1 - cosine distance`, exactly as in the Chroma PoC, so
        `MIN_RELEVANCE` keeps its meaning.
        """
        distance = Chunk.embedding.cosine_distance(list(embedding))
        statement = (
            select(
                Chunk.document_id,
                Chunk.chunk_index,
                Document.title,
                Chunk.text,
                (1 - distance).label("score"),
                Document.metadata_,
            )
            .join(
                Document,
                and_(
                    Document.workspace_id == Chunk.workspace_id,
                    Document.document_id == Chunk.document_id,
                ),
            )
            .where(Chunk.workspace_id == workspace_id)
            .order_by(distance)
            .limit(top_k)
        )
        if search_filter and search_filter.document_ids:
            statement = statement.where(Chunk.document_id.in_(search_filter.document_ids))
        if search_filter and search_filter.metadata:
            # JSONB containment: every given pair must be present with an equal, typed value.
            statement = statement.where(Document.metadata_.contains(dict(search_filter.metadata)))
        # With a filter, a plain HNSW scan can stop before finding top_k matching rows.
        # pgvector 0.8's iterative scan keeps searching until it has enough.
        db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rows = db.execute(statement).all()
        hits = [
            ChunkHit(
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                title=row.title,
                text=row.text,
                score=float(row.score),
                metadata=dict(row.metadata_),
            )
            for row in rows
        ]
        # relaxed_order may return nearly-sorted rows; the contract is strictly sorted.
        hits.sort(key=lambda hit: (-hit.score, hit.document_id, hit.chunk_index))
        return hits

    def list_documents(self, db: Session, workspace_id: uuid.UUID) -> list[StoredDocument]:
        """The workspace's documents with their chunk counts, sorted by `document_id`."""
        rows = db.execute(
            select(
                Document.document_id,
                Document.title,
                Document.metadata_,
                func.count(Chunk.chunk_index).label("chunks"),
            )
            .outerjoin(
                Chunk,
                and_(
                    Chunk.workspace_id == Document.workspace_id,
                    Chunk.document_id == Document.document_id,
                ),
            )
            .where(Document.workspace_id == workspace_id)
            .group_by(Document.workspace_id, Document.document_id)
            .order_by(Document.document_id)
        ).all()
        return [
            StoredDocument(
                document_id=row.document_id,
                title=row.title,
                chunks=int(row.chunks),
                metadata=dict(row.metadata_),
            )
            for row in rows
        ]

    def delete_document(self, db: Session, workspace_id: uuid.UUID, document_id: str) -> bool:
        """Delete a document; its chunks go with it (cascade). False if it didn't exist."""
        deleted = db.execute(
            delete(Document)
            .where(Document.workspace_id == workspace_id, Document.document_id == document_id)
            .returning(Document.document_id)
        ).first()
        return deleted is not None


@dataclass(frozen=True)
class WorkspaceIndex:
    """The vector store bound to one request's session and workspace.

    Built once per request, after the workspace is set on the transaction, so services and
    routes can't forget either argument.
    """

    store: PgVectorStore
    db: Session
    workspace_id: uuid.UUID

    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadata: Metadata,
        title: str,
    ) -> None:
        """See `PgVectorStore.replace_document`."""
        self.store.replace_document(
            self.db, self.workspace_id, document_id, chunks, embeddings, metadata, title
        )

    def query(
        self, embedding: Sequence[float], top_k: int, search_filter: SearchFilter | None = None
    ) -> list[ChunkHit]:
        """See `PgVectorStore.query`."""
        return self.store.query(self.db, self.workspace_id, embedding, top_k, search_filter)

    def list_documents(self) -> list[StoredDocument]:
        """See `PgVectorStore.list_documents`."""
        return self.store.list_documents(self.db, self.workspace_id)

    def delete_document(self, document_id: str) -> bool:
        """See `PgVectorStore.delete_document`."""
        return self.store.delete_document(self.db, self.workspace_id, document_id)
