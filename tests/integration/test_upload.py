import pytest

TEXT = "Cats purr when they are content.\n\nDogs wag their tails when they are happy."


def _upload(client, filename, content: bytes, **form):
    return client.post("/documents/upload", files={"file": (filename, content)}, data=form)


def _stored_ids(store, document_id):
    return store._collection.get(where={"document_id": document_id})["ids"]


def test_txt_upload_returns_201_with_filename_as_title(client, store):
    r = _upload(client, "pets.txt", TEXT.encode(), document_id="pets")
    assert r.status_code == 201
    assert r.json() == {
        "document_id": "pets",
        "title": "pets.txt",
        "chunks": 1,
        "characters": len(TEXT),
    }
    assert _stored_ids(store, "pets") == ["pets:0"]


@pytest.mark.parametrize("filename", ["notes.md", "NOTES.MD", "Report.Txt"])
def test_md_and_any_case_extension_accepted(client, filename):
    assert _upload(client, filename, TEXT.encode()).status_code == 201


def test_generated_id_when_absent(client):
    body = _upload(client, "pets.txt", TEXT.encode()).json()
    assert len(body["document_id"]) == 36


def test_reupload_replaces_document(client, store):
    long_text = "\n\n".join(f"Paragraph {i} about topic {i} in detail." for i in range(40))
    first = _upload(client, "a.txt", long_text.encode(), document_id="doc").json()
    assert first["chunks"] > 1
    r = _upload(client, "a.txt", b"Now short.", document_id="doc")
    assert r.json()["chunks"] == 1
    assert _stored_ids(store, "doc") == ["doc:0"]


def test_uploaded_text_is_searchable(client):
    _upload(client, "pets.txt", TEXT.encode(), document_id="pets")
    hit = client.post("/search", json={"query": "why do cats purr", "top_k": 1}).json()
    assert hit["results"][0]["document_id"] == "pets"
    assert hit["results"][0]["title"] == "pets.txt"


def test_utf8_bom_is_removed(client, store):
    r = _upload(client, "bom.txt", b"\xef\xbb\xbf" + TEXT.encode(), document_id="bom")
    assert r.json()["characters"] == len(TEXT)
    assert store._collection.get(ids=["bom:0"])["documents"][0].startswith("Cats")


def test_title_is_the_base_name_without_client_path(client):
    for name in ("C:\\Users\\me\\notes.txt", "/home/me/notes.txt"):
        assert _upload(client, name, TEXT.encode()).json()["title"] == "notes.txt"


def test_long_filename_is_truncated_to_title_limit(client):
    title = _upload(client, "n" * 250 + ".txt", TEXT.encode()).json()["title"]
    assert len(title) == 200


@pytest.mark.parametrize("filename", ["report.pdf", "data.docx", "noextension", "archive.txt.zip"])
def test_other_file_types_return_415(client, store, filename):
    r = _upload(client, filename, TEXT.encode())
    assert r.status_code == 415
    assert store.count() == 0


def test_non_utf8_returns_422(client, store):
    r = _upload(client, "latin1.txt", "café".encode("latin-1"))
    assert r.status_code == 422
    assert store.count() == 0


@pytest.mark.parametrize("content", [b"", b"   \n\t  "])
def test_empty_or_blank_file_returns_422(client, store, content):
    assert _upload(client, "blank.txt", content).status_code == 422
    assert store.count() == 0


def test_bad_document_id_returns_422(client, store):
    assert _upload(client, "a.txt", TEXT.encode(), document_id="has space").status_code == 422
    assert store.count() == 0


def test_missing_file_returns_422(client):
    assert client.post("/documents/upload", data={"document_id": "x"}).status_code == 422


def test_text_over_limit_returns_413(client, store, settings):
    r = _upload(client, "big.txt", b"x" * (settings.max_document_chars + 1))
    assert r.status_code == 413
    assert store.count() == 0


def test_text_at_limit_is_accepted(client, settings):
    r = _upload(client, "big.txt", b"x" * settings.max_document_chars)
    assert r.status_code == 201


def test_limit_counts_characters_not_bytes(client, settings):
    # "é" is 2 bytes in UTF-8. At the character limit the byte count is double, and it's accepted.
    r = _upload(client, "accents.txt", ("é" * settings.max_document_chars).encode())
    assert r.status_code == 201
    assert r.json()["characters"] == settings.max_document_chars
