from fastapi.testclient import TestClient

from app.main import create_app


def test_response_carries_generated_request_id(client):
    r = client.get("/health")
    assert len(r.headers["X-Request-ID"]) == 32


def test_safe_incoming_request_id_is_echoed(client):
    r = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert r.headers["X-Request-ID"] == "trace-123"


def test_unsafe_incoming_request_id_is_replaced(client):
    r = client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert r.headers["X-Request-ID"] != "bad id\twith spaces"


def test_unhandled_error_returns_generic_500(settings, embedder):
    app = create_app(settings, embedder=embedder)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internals")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error"}
