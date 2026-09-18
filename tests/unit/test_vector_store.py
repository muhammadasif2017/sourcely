"""`build_where` as a pure function, and filtered queries against a real in-memory Chroma."""

import uuid

import chromadb
import pytest

from app.services.vector_store import VectorStore, build_where


def test_no_filters_means_no_where_clause():
    assert build_where(None, None) is None


def test_document_ids_become_in():
    assert build_where(["a", "b"], None) == {"document_id": {"$in": ["a", "b"]}}


def test_single_metadata_pair_is_not_wrapped():
    # Chroma rejects $and with fewer than two conditions.
    assert build_where(None, {"source": "wiki"}) == {"source": {"$eq": "wiki"}}


def test_several_metadata_pairs_are_anded():
    assert build_where(None, {"source": "wiki", "year": 2026}) == {
        "$and": [{"source": {"$eq": "wiki"}}, {"year": {"$eq": 2026}}]
    }


def test_ids_and_metadata_are_anded():
    assert build_where(["a"], {"public": True}) == {
        "$and": [{"document_id": {"$in": ["a"]}}, {"public": {"$eq": True}}]
    }


# --- filtered queries on a real collection ------------------------------------------------


@pytest.fixture
def store() -> VectorStore:
    s = VectorStore(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex}")
    docs = {
        "wiki-2026": {"source": "wiki", "year": 2026, "public": True, "rating": 4.5},
        "wiki-2025": {"source": "wiki", "year": 2025, "public": False, "rating": 3.0},
        "blog-2026": {"source": "blog", "year": 2026, "public": True, "rating": 4.5},
    }
    for i, (doc_id, meta) in enumerate(docs.items()):
        # Near-identical vectors, so every document is a neighbour and only filters decide.
        s.replace_document(doc_id, ["text"], [[1.0, 0.01 * i]], meta, doc_id)
    return s


def _ids(store, where):
    return sorted(hit.document_id for hit in store.query([1.0, 0.0], 10, where))


def test_query_without_filter_returns_all(store):
    assert _ids(store, None) == ["blog-2026", "wiki-2025", "wiki-2026"]


def test_filter_by_document_ids(store):
    assert _ids(store, build_where(["wiki-2025", "blog-2026"], None)) == ["blog-2026", "wiki-2025"]


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"source": "wiki"}, ["wiki-2025", "wiki-2026"]),
        ({"year": 2026}, ["blog-2026", "wiki-2026"]),
        ({"public": False}, ["wiki-2025"]),
        ({"rating": 4.5}, ["blog-2026", "wiki-2026"]),
        ({"source": "wiki", "year": 2026}, ["wiki-2026"]),
        ({"source": "news"}, []),
    ],
)
def test_filter_by_metadata(store, metadata, expected):
    assert _ids(store, build_where(None, metadata)) == expected


def test_ids_and_metadata_must_both_match(store):
    assert _ids(store, build_where(["wiki-2025", "blog-2026"], {"source": "wiki"})) == ["wiki-2025"]


def test_unknown_id_matches_nothing(store):
    assert _ids(store, build_where(["missing"], None)) == []
