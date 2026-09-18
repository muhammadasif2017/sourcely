import pytest

DOCS = {
    "cats": "Cats are small domesticated felines. Cats purr and chase mice around the house.",
    "rockets": "Rockets burn fuel to produce thrust. A rocket engine pushes exhaust downward.",
    "bread": "Bread is baked from flour, water and yeast. Knead the dough before baking bread.",
}


def _ingest(client, document_id, text, **extra):
    r = client.post("/documents", json={"text": text, "document_id": document_id, **extra})
    assert r.status_code == 201
    return r.json()


def _ingest_all(client):
    for document_id, text in DOCS.items():
        _ingest(client, document_id, text, title=document_id.title())


def test_empty_store_returns_no_results(client):
    r = client.post("/search", json={"query": "anything at all"})
    assert r.status_code == 200
    assert r.json() == {"query": "anything at all", "results": []}


def test_relevant_document_ranks_first(client):
    _ingest_all(client)
    r = client.post("/search", json={"query": "why do cats purr", "top_k": 3})
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 3
    assert results[0]["document_id"] == "cats"


def test_hit_has_spec_fields(client):
    _ingest(
        client,
        "rockets",
        DOCS["rockets"],
        title="Rocketry",
        metadata={"source": "wiki", "year": 2026},
    )
    hit = client.post("/search", json={"query": "rocket thrust", "top_k": 1}).json()["results"][0]
    assert set(hit) == {"document_id", "chunk_index", "title", "text", "score", "metadata"}
    assert hit["document_id"] == "rockets"
    assert hit["chunk_index"] == 0
    assert hit["title"] == "Rocketry"
    assert hit["text"] == DOCS["rockets"]
    # Reserved keys are already top-level fields, so metadata holds only the client's own keys.
    assert hit["metadata"] == {"source": "wiki", "year": 2026}


def test_scores_are_cosine_similarity_sorted_high_to_low(client):
    _ingest_all(client)
    results = client.post("/search", json={"query": DOCS["bread"], "top_k": 3}).json()["results"]
    scores = [hit["score"] for hit in results]
    assert scores == sorted(scores, reverse=True)
    # The query is identical to the stored chunk, so similarity is 1 (distance 0).
    assert results[0]["document_id"] == "bread"
    assert scores[0] == pytest.approx(1.0, abs=1e-5)
    assert all(-1.0 <= s <= 1.0 for s in scores)


def test_top_k_defaults_to_setting(client, settings):
    for i in range(settings.default_top_k + 2):
        _ingest(client, f"doc-{i}", f"Note number {i} about shared words.")
    results = client.post("/search", json={"query": "shared words"}).json()["results"]
    assert len(results) == settings.default_top_k


def test_top_k_larger_than_store_returns_everything(client):
    _ingest_all(client)
    results = client.post("/search", json={"query": "bread", "top_k": 20}).json()["results"]
    assert len(results) == len(DOCS)


def test_search_does_not_need_llm_key(client, settings):
    settings.openai_api_key = None
    _ingest_all(client)
    r = client.post("/search", json={"query": "cats"})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": ""},
        {"query": "   \n\t "},
        {"query": "q" * 2001},
        {"query": "ok", "top_k": 0},
        {"query": "ok", "top_k": 21},
        {"query": "ok", "top_k": "many"},
        {"query": 42},
    ],
)
def test_invalid_input_returns_422(client, payload):
    r = client.post("/search", json=payload)
    assert r.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "q" * 2000},
        {"query": "q", "top_k": 1},
        {"query": "q", "top_k": 20},
    ],
)
def test_boundary_values_are_accepted(client, payload):
    r = client.post("/search", json=payload)
    assert r.status_code == 200
