"""PgVectorStore against real Postgres, and row-level security at the database level."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.schemas.search import SearchFilters
from app.services.vector_store import PgVectorStore, SearchFilter, WorkspaceIndex, set_workspace

DIM = 384
DOCS = {
    "wiki-2026": {"source": "wiki", "year": 2026, "public": True, "rating": 4.5},
    "wiki-2025": {"source": "wiki", "year": 2025, "public": False, "rating": 3.0},
    "blog-2026": {"source": "blog", "year": 2026, "public": True, "rating": 4.5},
}


def _vector(i: int) -> list[float]:
    # Near-identical vectors: every document is a close neighbour, so only filters decide.
    return [1.0, 0.01 * i] + [0.0] * (DIM - 2)


def _workspace(owner_db) -> uuid.UUID:
    workspace_id = uuid.uuid4()
    owner_db.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, 'W')"), {"id": workspace_id}
    )
    return workspace_id


@pytest.fixture
def app_engine(settings) -> Iterator[Engine]:
    """Connected as the restricted app role, exactly like the API."""
    engine = create_engine(settings.database_url)
    yield engine
    engine.dispose()


def _index(db: Session, workspace_id: uuid.UUID) -> WorkspaceIndex:
    set_workspace(db, workspace_id)
    return WorkspaceIndex(store=PgVectorStore(), db=db, workspace_id=workspace_id)


@pytest.fixture
def seeded(app_engine, owner_db) -> uuid.UUID:
    workspace_id = _workspace(owner_db)
    with Session(app_engine) as db, db.begin():
        index = _index(db, workspace_id)
        for i, (document_id, metadata) in enumerate(DOCS.items()):
            index.replace_document(document_id, ["text"], [_vector(i)], metadata, document_id)
    return workspace_id


def _ids(app_engine, workspace_id, search_filter=None) -> list[str]:
    with Session(app_engine) as db, db.begin():
        hits = _index(db, workspace_id).query(_vector(0), 10, search_filter)
    return sorted(hit.document_id for hit in hits)


# --- queries and filters ----------------------------------------------------------------


def test_query_without_filter_returns_all(app_engine, seeded):
    assert _ids(app_engine, seeded) == ["blog-2026", "wiki-2025", "wiki-2026"]


def test_score_is_cosine_similarity(app_engine, seeded):
    with Session(app_engine) as db, db.begin():
        hits = _index(db, seeded).query(_vector(0), 1)
    assert hits[0].document_id == "wiki-2026"
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    assert hits[0].metadata == DOCS["wiki-2026"]


def test_filter_by_document_ids(app_engine, seeded):
    search_filter = SearchFilter(document_ids=("wiki-2025", "blog-2026"))
    assert _ids(app_engine, seeded, search_filter) == ["blog-2026", "wiki-2025"]


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"source": "wiki"}, ["wiki-2025", "wiki-2026"]),
        ({"year": 2026}, ["blog-2026", "wiki-2026"]),
        ({"public": False}, ["wiki-2025"]),
        ({"rating": 4.5}, ["blog-2026", "wiki-2026"]),
        ({"source": "wiki", "year": 2026}, ["wiki-2026"]),
        ({"source": "news"}, []),
        # Typed matching: the string "2026" is not the number 2026.
        ({"year": "2026"}, []),
    ],
)
def test_filter_by_metadata(app_engine, seeded, metadata, expected):
    assert _ids(app_engine, seeded, SearchFilter(metadata=metadata)) == expected


def test_ids_and_metadata_must_both_match(app_engine, seeded):
    search_filter = SearchFilter(
        document_ids=("wiki-2025", "blog-2026"), metadata={"source": "wiki"}
    )
    assert _ids(app_engine, seeded, search_filter) == ["wiki-2025"]


def test_schema_filters_convert_to_store_filter():
    assert SearchFilters().to_filter() == SearchFilter()
    converted = SearchFilters(document_ids=["a"], metadata={"k": 1}).to_filter()
    assert converted == SearchFilter(document_ids=("a",), metadata={"k": 1})


def test_filtered_search_still_returns_top_k(app_engine, owner_db):
    """Many close non-matching chunks must not crowd matching ones out of the result."""
    workspace_id = _workspace(owner_db)
    with Session(app_engine) as db, db.begin():
        index = _index(db, workspace_id)
        for i in range(60):
            index.replace_document(f"noise-{i}", ["t"], [_vector(0)], {"kind": "noise"}, "")
        for i in range(5):
            index.replace_document(f"match-{i}", ["t"], [_vector(90)], {"kind": "match"}, "")
    with Session(app_engine) as db, db.begin():
        hits = _index(db, workspace_id).query(
            _vector(0), 4, SearchFilter(metadata={"kind": "match"})
        )
    assert len(hits) == 4
    assert all(hit.document_id.startswith("match-") for hit in hits)


def test_replace_is_atomic_and_leaves_no_orphans(app_engine, owner_db):
    workspace_id = _workspace(owner_db)
    with Session(app_engine) as db, db.begin():
        _index(db, workspace_id).replace_document("d", ["a", "b", "c"], [_vector(1)] * 3, {}, "v1")
    with pytest.raises(ValueError), Session(app_engine) as db, db.begin():
        # A failure halfway (mismatched lengths) must keep version 1 intact.
        _index(db, workspace_id).replace_document("d", ["x"], [], {}, "broken")
    with Session(app_engine) as db, db.begin():
        index = _index(db, workspace_id)
        assert [doc.chunks for doc in index.list_documents()] == [3]
        index.replace_document("d", ["only"], [_vector(1)], {}, "v2")
        documents = index.list_documents()
    assert [(doc.title, doc.chunks) for doc in documents] == [("v2", 1)]


def test_count_sees_every_workspace(app_engine, seeded, owner_db):
    other = _workspace(owner_db)
    with Session(app_engine) as db, db.begin():
        _index(db, other).replace_document("x", ["t"], [_vector(1)], {}, "")
    with Session(app_engine) as db, db.begin():
        # No workspace set: row-level security hides everything, but the count function sees all.
        assert PgVectorStore().count(db) == 4


# --- row-level security, at the database level --------------------------------------------


def test_rls_hides_other_workspaces_rows(app_engine, seeded, owner_db):
    other = _workspace(owner_db)
    with app_engine.connect() as connection, connection.begin():
        connection.execute(
            text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(other)}
        )
        # No WHERE clause at all: only the policy stands between the app and workspace A's rows.
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM chunks")).scalar_one() == 0


def test_rls_hides_everything_when_no_workspace_is_set(app_engine, seeded):
    with app_engine.connect() as connection, connection.begin():
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM chunks")).scalar_one() == 0


def test_rls_shows_own_rows(app_engine, seeded):
    with app_engine.connect() as connection, connection.begin():
        connection.execute(
            text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(seeded)}
        )
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 3


def test_rls_refuses_writes_into_another_workspace(app_engine, seeded, owner_db):
    other = _workspace(owner_db)
    with app_engine.connect() as connection, connection.begin():
        connection.execute(
            text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(other)}
        )
        with pytest.raises(ProgrammingError, match="row-level security"):
            connection.execute(
                text(
                    "INSERT INTO documents (workspace_id, document_id, title) VALUES (:w, 'x', '')"
                ),
                {"w": str(seeded)},
            )


def test_rls_setting_does_not_leak_between_transactions(app_engine, seeded):
    with app_engine.connect() as connection:
        with connection.begin():
            connection.execute(
                text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(seeded)}
            )
            assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 3
        with connection.begin():
            # Same pooled connection, new transaction: the workspace is gone again.
            assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
