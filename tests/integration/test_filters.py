import pytest

from app.services.rag import NO_CONTEXT_ANSWER

DOCS = [
    ("cats-wiki", "Cats purr when they are content.", {"source": "wiki", "year": 2026}),
    ("cats-blog", "Cats purr loudly at night.", {"source": "blog", "year": 2025}),
    ("dogs-wiki", "Dogs wag their tails when happy.", {"source": "wiki", "year": 2025}),
]


@pytest.fixture
def seeded(client):
    for document_id, text, metadata in DOCS:
        r = client.post(
            "/documents", json={"text": text, "document_id": document_id, "metadata": metadata}
        )
        assert r.status_code == 201
    return client


def _search_ids(client, filters):
    body = {"query": "cats purr", "top_k": 10, "filters": filters}
    r = client.post("/search", json=body)
    assert r.status_code == 200
    return sorted(hit["document_id"] for hit in r.json()["results"])


def test_search_filtered_by_document_ids(seeded):
    assert _search_ids(seeded, {"document_ids": ["cats-blog", "dogs-wiki"]}) == [
        "cats-blog",
        "dogs-wiki",
    ]


def test_search_filtered_by_metadata(seeded):
    assert _search_ids(seeded, {"metadata": {"source": "wiki"}}) == ["cats-wiki", "dogs-wiki"]


def test_search_filters_combine_with_and(seeded):
    filters = {"document_ids": ["cats-wiki", "cats-blog"], "metadata": {"year": 2025}}
    assert _search_ids(seeded, filters) == ["cats-blog"]


@pytest.mark.parametrize("filters", [None, {}])
def test_absent_or_empty_filters_do_not_filter(seeded, filters):
    assert len(_search_ids(seeded, filters)) == 3


def test_filter_matching_nothing_returns_empty(seeded):
    assert _search_ids(seeded, {"metadata": {"source": "news"}}) == []


def test_ask_sources_respect_filters(seeded, llm):
    body = {"question": "why do cats purr", "top_k": 5, "filters": {"document_ids": ["cats-blog"]}}
    sources = seeded.post("/ask", json=body).json()["sources"]
    assert [s["document_id"] for s in sources] == ["cats-blog"]
    assert "content" not in llm.calls[0][1]


def test_ask_with_filter_excluding_relevant_docs_skips_llm(seeded, llm):
    body = {"question": "why do cats purr", "filters": {"document_ids": ["dogs-wiki"]}}
    r = seeded.post("/ask", json=body)
    assert r.json()["answer"] == NO_CONTEXT_ANSWER
    assert llm.calls == []


INVALID_FILTERS = [
    {"document_ids": []},
    {"document_ids": [f"d{i}" for i in range(101)]},
    {"document_ids": ["has space"]},
    {"document_ids": "cats-wiki"},
    {"metadata": {}},
    {"metadata": {f"k{i}": i for i in range(11)}},
    {"metadata": {"document_id": "cats-wiki"}},
    {"metadata": {"title": "x"}},
    {"metadata": {"1bad": "x"}},
    {"metadata": {"source": ["wiki", "blog"]}},
    {"metadata": {"source": None}},
    {"unknown": 1},
]


@pytest.mark.parametrize("filters", INVALID_FILTERS)
def test_invalid_search_filters_return_422(client, filters):
    r = client.post("/search", json={"query": "cats", "filters": filters})
    assert r.status_code == 422


@pytest.mark.parametrize("filters", INVALID_FILTERS)
def test_invalid_ask_filters_return_422(client, llm, filters):
    r = client.post("/ask", json={"question": "cats", "filters": filters})
    assert r.status_code == 422
    assert llm.calls == []


def test_filter_limits_are_inclusive(client):
    filters = {
        "document_ids": [f"d{i}" for i in range(100)],
        "metadata": {f"k{i}": i for i in range(10)},
    }
    assert client.post("/search", json={"query": "q", "filters": filters}).status_code == 200
