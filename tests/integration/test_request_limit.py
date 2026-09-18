import pytest
from fastapi.testclient import TestClient

from app.main import create_app

LIMIT = 4096


@pytest.fixture
def limited(settings, store, embedder, llm):
    settings.max_request_bytes = LIMIT
    with TestClient(create_app(settings, embedder=embedder, store=store, llm=llm)) as c:
        yield c


def _json_body(size: int) -> bytes:
    """A valid `POST /documents` body of exactly `size` bytes."""
    shell = b'{"text": ""}'
    return shell[:10] + b"x" * (size - len(shell)) + shell[10:]


def test_body_at_limit_is_accepted(limited):
    r = limited.post(
        "/documents", content=_json_body(LIMIT), headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 201


def test_declared_length_over_limit_returns_413(limited, store):
    r = limited.post(
        "/documents", content=_json_body(LIMIT + 1), headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json() == {"detail": f"Request body is larger than {LIMIT} bytes"}
    assert r.headers["x-request-id"]
    assert store.count() == 0


def test_chunked_body_over_limit_returns_413(limited, store):
    def chunks():
        yield b'{"text": "'
        for _ in range(10):
            yield b"x" * 1000
        yield b'"}'

    # A generator body is sent with Transfer-Encoding: chunked and no Content-Length.
    r = limited.post("/documents", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert store.count() == 0


def test_chunked_body_within_limit_is_accepted(limited):
    def chunks():
        yield b'{"text": "'
        yield b"x" * 1000
        yield b'"}'

    r = limited.post("/documents", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 201


def test_oversized_upload_returns_413(limited, store):
    r = limited.post("/documents/upload", files={"file": ("big.txt", b"x" * (LIMIT + 1))})
    assert r.status_code == 413
    assert store.count() == 0


def test_invalid_content_length_returns_400(limited):
    r = limited.post(
        "/documents",
        content=b'{"text": "ok"}',
        headers={"Content-Type": "application/json", "Content-Length": "abc"},
    )
    assert r.status_code == 400


def test_get_requests_are_unaffected(limited):
    assert limited.get("/health").status_code == 200


def test_default_limit_fits_largest_valid_document(settings):
    # The default must admit a maximum-size document even if every character is JSON-escaped
    # as \\uXXXX (6 bytes each).
    from app.core.config import Settings

    defaults = Settings(_env_file=None)
    assert defaults.max_request_bytes >= defaults.max_document_chars * 6 + 1024
