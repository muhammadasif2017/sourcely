LONG_TEXT = "\n\n".join(f"Paragraph {i} talks about topic number {i} in detail." for i in range(40))


def _ingest(client, document_id, text="Some short text.", **extra):
    r = client.post("/documents", json={"text": text, "document_id": document_id, **extra})
    assert r.status_code == 201
    return r.json()


def test_empty_store_lists_nothing(client):
    r = client.get("/documents")
    assert r.status_code == 200
    assert r.json() == {"documents": []}


def test_list_is_sorted_with_title_chunks_and_metadata(client):
    long_doc = _ingest(client, "b-long", LONG_TEXT, title="Long", metadata={"source": "wiki"})
    _ingest(client, "a-short", title="Short", metadata={"year": 2026, "public": True})
    _ingest(client, "c-plain")
    assert client.get("/documents").json() == {
        "documents": [
            {
                "document_id": "a-short",
                "title": "Short",
                "chunks": 1,
                "metadata": {"year": 2026, "public": True},
            },
            {
                "document_id": "b-long",
                "title": "Long",
                "chunks": long_doc["chunks"],
                "metadata": {"source": "wiki"},
            },
            {"document_id": "c-plain", "title": "", "chunks": 1, "metadata": {}},
        ]
    }


def test_list_reflects_reingest(client):
    _ingest(client, "doc", LONG_TEXT, title="Old")
    _ingest(client, "doc", "Now short.", title="New")
    assert client.get("/documents").json()["documents"] == [
        {"document_id": "doc", "title": "New", "chunks": 1, "metadata": {}}
    ]


def test_uploaded_file_is_listed(client):
    client.post(
        "/documents/upload", files={"file": ("notes.md", b"# Notes")}, data={"document_id": "n"}
    )
    assert client.get("/documents").json()["documents"][0]["title"] == "notes.md"


def test_delete_returns_204_and_removes_every_chunk(client, store):
    chunks = _ingest(client, "doomed", LONG_TEXT)["chunks"]
    _ingest(client, "kept")
    assert store.count() == chunks + 1
    r = client.delete("/documents/doomed")
    assert r.status_code == 204
    assert r.content == b""
    assert store.count() == 1
    assert [d["document_id"] for d in client.get("/documents").json()["documents"]] == ["kept"]


def test_deleted_document_is_gone_from_search(client):
    _ingest(client, "cats", "Cats purr when they are content.")
    _ingest(client, "rockets", "Rockets burn fuel to produce thrust.")
    client.delete("/documents/cats")
    results = client.post("/search", json={"query": "cats purr", "top_k": 5}).json()["results"]
    assert [hit["document_id"] for hit in results] == ["rockets"]


def test_delete_unknown_returns_404(client):
    r = client.delete("/documents/missing")
    assert r.status_code == 404
    assert r.json() == {"detail": "Document 'missing' not found"}


def test_delete_twice_returns_404_the_second_time(client):
    _ingest(client, "once")
    assert client.delete("/documents/once").status_code == 204
    assert client.delete("/documents/once").status_code == 404


def test_delete_with_invalid_id_returns_422(client):
    assert client.delete("/documents/has space").status_code == 422
    assert client.delete("/documents/" + "x" * 129).status_code == 422
