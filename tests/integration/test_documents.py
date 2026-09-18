import pytest

LONG_TEXT = "\n\n".join(
    f"Paragraph {i} talks about topic number {i} in some detail." for i in range(40)
)


def _stored(store, document_id):
    """Ids and metadatas of one document's chunks, read straight from the collection."""
    got = store._collection.get(where={"document_id": document_id})
    return got["ids"], got["metadatas"]


def test_ingest_returns_201_with_summary(client):
    r = client.post(
        "/documents",
        json={"text": LONG_TEXT, "document_id": "doc-1", "title": "Topics"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["document_id"] == "doc-1"
    assert body["title"] == "Topics"
    assert body["characters"] == len(LONG_TEXT)
    assert body["chunks"] > 1


def test_ingest_stores_chunk_ids_and_metadata(client, store):
    r = client.post(
        "/documents",
        json={
            "text": LONG_TEXT,
            "document_id": "doc-1",
            "title": "Topics",
            "metadata": {"source": "wiki", "year": 2026, "score": 0.5, "public": True},
        },
    )
    chunks = r.json()["chunks"]
    ids, metadatas = _stored(store, "doc-1")
    assert sorted(ids) == sorted(f"doc-1:{i}" for i in range(chunks))
    by_index = sorted(metadatas, key=lambda m: m["chunk_index"])
    assert [m["chunk_index"] for m in by_index] == list(range(chunks))
    for m in by_index:
        assert m["document_id"] == "doc-1"
        assert m["title"] == "Topics"
        assert m["source"] == "wiki"
        assert m["year"] == 2026
        assert m["public"] is True
    assert store.count() == chunks


def test_ingest_generates_id_and_defaults_title(client, store):
    r = client.post("/documents", json={"text": "Short text."})
    assert r.status_code == 201
    body = r.json()
    assert len(body["document_id"]) == 36
    assert body["title"] == ""
    assert body["chunks"] == 1
    ids, _ = _stored(store, body["document_id"])
    assert ids == [f"{body['document_id']}:0"]


def test_reingest_shorter_version_leaves_no_orphans(client, store):
    first = client.post("/documents", json={"text": LONG_TEXT, "document_id": "doc-1"}).json()
    old_last = f"doc-1:{first['chunks'] - 1}"
    assert first["chunks"] > 1

    r = client.post("/documents", json={"text": "Now it is short.", "document_id": "doc-1"})
    assert r.status_code == 201
    assert r.json()["chunks"] == 1
    ids, metadatas = _stored(store, "doc-1")
    assert ids == ["doc-1:0"]
    assert old_last not in store._collection.get()["ids"]
    assert store.count() == 1
    assert metadatas[0]["title"] == ""


def test_reingest_leaves_other_documents_alone(client, store):
    client.post("/documents", json={"text": "Alpha text.", "document_id": "a"})
    client.post("/documents", json={"text": "Beta text.", "document_id": "b"})
    client.post("/documents", json={"text": "Alpha again.", "document_id": "a"})
    assert _stored(store, "b")[0] == ["b:0"]
    assert store.count() == 2


def test_text_over_limit_returns_413(client, settings):
    r = client.post("/documents", json={"text": "x" * (settings.max_document_chars + 1)})
    assert r.status_code == 413


def test_text_at_limit_is_accepted(client, settings):
    r = client.post("/documents", json={"text": "x" * settings.max_document_chars})
    assert r.status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": ""},
        {"text": "   \n\t  "},
        {"text": "ok", "document_id": ""},
        {"text": "ok", "document_id": "has space"},
        {"text": "ok", "document_id": "a/b"},
        {"text": "ok", "document_id": "x" * 129},
        {"text": "ok", "title": "t" * 201},
        {"text": "ok", "metadata": {"document_id": "x"}},
        {"text": "ok", "metadata": {"chunk_index": 1}},
        {"text": "ok", "metadata": {"title": "x"}},
        {"text": "ok", "metadata": {"1abc": "x"}},
        {"text": "ok", "metadata": {"has-dash": "x"}},
        {"text": "ok", "metadata": {"": "x"}},
        {"text": "ok", "metadata": {"k" * 65: "x"}},
        {"text": "ok", "metadata": {"tags": ["a", "b"]}},
        {"text": "ok", "metadata": {"nested": {"a": 1}}},
        {"text": "ok", "metadata": {"missing": None}},
        {"text": "ok", "metadata": {f"k{i}": i for i in range(21)}},
    ],
)
def test_invalid_input_returns_422(client, store, payload):
    r = client.post("/documents", json=payload)
    assert r.status_code == 422
    assert store.count() == 0


def test_boundary_values_are_accepted(client):
    r = client.post(
        "/documents",
        json={
            "text": "ok",
            "document_id": "A" * 128,
            "title": "t" * 200,
            "metadata": {**{f"k{i}": i for i in range(19)}, "K" * 64: "long key"},
        },
    )
    assert r.status_code == 201
