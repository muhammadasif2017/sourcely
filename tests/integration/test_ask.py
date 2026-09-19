import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import SYSTEM_PROMPT, LLMError
from app.services.rag import NO_CONTEXT_ANSWER

CATS = "Cats are small domesticated felines. Cats purr when they are content and relaxed."
ROCKETS = "Rockets burn fuel to produce thrust. A rocket engine pushes exhaust downward."


def _ingest(client, document_id, text, title=""):
    r = client.post("/documents", json={"text": text, "document_id": document_id, "title": title})
    assert r.status_code == 201


def test_answer_with_sources(client, llm):
    _ingest(client, "cats", CATS, title="Cats")
    r = client.post("/ask", json={"question": "why do cats purr"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == llm.answer
    assert body["provider"] == "fake-provider"
    assert body["model"] == "fake-model"
    assert [s["document_id"] for s in body["sources"]] == ["cats"]
    source = body["sources"][0]
    assert set(source) == {"document_id", "chunk_index", "title", "text", "score", "metadata"}
    assert source["title"] == "Cats"
    assert source["text"] == CATS


def test_context_and_question_reach_the_prompt(client, llm):
    _ingest(client, "cats", CATS, title="Cats")
    client.post("/ask", json={"question": "why do cats purr"})
    assert len(llm.calls) == 1
    system, user = llm.calls[0]
    assert system == SYSTEM_PROMPT
    assert '<source id="1" title="Cats">' in user
    assert CATS in user
    assert "why do cats purr" in user


def test_irrelevant_chunks_are_not_sources(client, llm):
    _ingest(client, "cats", CATS)
    _ingest(client, "rockets", ROCKETS)
    body = client.post("/ask", json={"question": "why do cats purr", "top_k": 2}).json()
    # The fake embedder gives the rocket text zero similarity, below MIN_RELEVANCE.
    assert [s["document_id"] for s in body["sources"]] == ["cats"]
    assert "Rockets" not in llm.calls[0][1]


def test_empty_store_returns_fixed_answer_without_llm_call(client, llm):
    r = client.post("/ask", json={"question": "why do cats purr"})
    assert r.status_code == 200
    assert r.json() == {
        "answer": NO_CONTEXT_ANSWER,
        "sources": [],
        "provider": "fake-provider",
        "model": "fake-model",
    }
    assert llm.calls == []


def test_off_topic_question_skips_llm(client, llm):
    _ingest(client, "cats", CATS)
    body = client.post("/ask", json={"question": "quantum chromodynamics lattice"}).json()
    assert body["answer"] == NO_CONTEXT_ANSWER
    assert body["sources"] == []
    assert llm.calls == []


def test_sources_respect_top_k(client, llm):
    for i in range(5):
        _ingest(client, f"cats-{i}", f"Cats purr, note {i}.")
    body = client.post("/ask", json={"question": "cats purr", "top_k": 2}).json()
    assert len(body["sources"]) == 2
    assert body["sources"][0]["score"] >= body["sources"][1]["score"]


def test_missing_key_returns_503(settings, embedder, auth_headers):
    settings.openai_api_key = None
    app = create_app(settings, embedder=embedder)
    with TestClient(app, headers=auth_headers) as c:
        r = c.post("/ask", json={"question": "why do cats purr"})
        assert r.status_code == 503
        assert r.json() == {"detail": "LLM provider not configured"}
        # Documents and search keep working without a key.
        assert c.post("/documents", json={"text": CATS}).status_code == 201
        assert c.post("/search", json={"query": "cats"}).status_code == 200


@pytest.mark.parametrize("status", [502, 503, 504])
def test_llm_errors_map_to_their_status(client, llm, status):
    _ingest(client, "cats", CATS)
    llm.error = LLMError(status, f"provider failed with {status}")
    r = client.post("/ask", json={"question": "why do cats purr"})
    assert r.status_code == status
    assert r.json() == {"detail": f"provider failed with {status}"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": "  \n "},
        {"question": "q" * 2001},
        {"question": "ok", "top_k": 0},
        {"question": "ok", "top_k": 21},
    ],
)
def test_invalid_input_returns_422(client, llm, payload):
    r = client.post("/ask", json=payload)
    assert r.status_code == 422
    assert llm.calls == []
