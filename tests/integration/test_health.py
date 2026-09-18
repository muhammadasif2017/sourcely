import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.engine import make_engine
from app.main import create_app


def test_health_reports_state(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "database": "ok",
        "chunks_indexed": 0,
        "embedding_model": "fake-embedder",
        "llm_provider": "openai",
        "llm_model": "fake-model",
        "llm_configured": True,
    }


def test_health_returns_503_when_database_is_down(settings, store, embedder, llm):
    # Nothing listens on port 1. A short timeout keeps the test fast even where a firewall
    # silently drops the attempt instead of refusing it.
    engine = make_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", connect_timeout=1)
    app = create_app(settings, embedder=embedder, store=store, llm=llm, engine=engine)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}


def test_startup_fails_when_embedding_dimension_mismatches(settings, store, embedder, llm):
    settings.embedding_dim = 128
    app = create_app(settings, embedder=embedder, store=store, llm=llm)
    with pytest.raises(RuntimeError, match="EMBEDDING_DIM is 128"), TestClient(app):
        pass


def test_db_session_uses_the_app_role(client):
    engine = client.app.state.engine
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar() == "sourcely_app"


def test_app_role_cannot_create_tables(client):
    # The app role owns nothing and can't change the schema, so it can't disable RLS either.
    engine = client.app.state.engine
    with engine.connect() as connection, pytest.raises(Exception, match="permission denied"):
        connection.execute(text("CREATE TABLE sneaky (id int)"))
