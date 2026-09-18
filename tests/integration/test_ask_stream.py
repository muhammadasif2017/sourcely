import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import LLMError
from app.services.rag import NO_CONTEXT_ANSWER

CATS = "Cats are small domesticated felines. Cats purr when they are content and relaxed."
DOGS = "Dogs wag their tails when they are happy."


def _ingest(client, document_id, text):
    r = client.post("/documents", json={"text": text, "document_id": document_id})
    assert r.status_code == 201


def _events(response) -> list[tuple[str, dict]]:
    """Parse a Server-Sent Events body into (event, data) pairs."""
    events = []
    for block in response.text.split("\n\n"):
        if not block.strip():
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def _stream(client, **body):
    return client.post("/ask/stream", json={"question": "why do cats purr", **body})


def test_events_arrive_in_order(client, llm):
    _ingest(client, "cats", CATS)
    r = _stream(client)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _events(r)
    names = [name for name, _ in events]
    assert names[0] == "sources"
    assert names[-1] == "done"
    assert set(names[1:-1]) == {"token"}
    assert len(names) - 2 == len(llm.answer.split(" "))


def test_tokens_join_to_the_answer(client, llm):
    _ingest(client, "cats", CATS)
    events = _events(_stream(client))
    assert "".join(data["text"] for name, data in events if name == "token") == llm.answer
    assert events[-1] == ("done", {})


def test_sources_event_has_sources_provider_and_model(client):
    _ingest(client, "cats", CATS)
    name, data = _events(_stream(client))[0]
    assert name == "sources"
    assert data["provider"] == "fake-provider"
    assert data["model"] == "fake-model"
    assert [s["document_id"] for s in data["sources"]] == ["cats"]
    assert set(data["sources"][0]) == {
        "document_id",
        "chunk_index",
        "title",
        "text",
        "score",
        "metadata",
    }


def test_response_headers_disable_caching_and_keep_request_id(client):
    _ingest(client, "cats", CATS)
    r = _stream(client)
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    assert r.headers["x-request-id"]


def test_no_context_sends_fixed_answer_without_llm_call(client, llm):
    r = _stream(client)
    assert r.status_code == 200
    assert _events(r) == [
        ("sources", {"sources": [], "provider": "fake-provider", "model": "fake-model"}),
        ("token", {"text": NO_CONTEXT_ANSWER}),
        ("done", {}),
    ]
    assert llm.calls == []


def test_filters_apply_to_stream(client, llm):
    _ingest(client, "cats", CATS)
    _ingest(client, "dogs", DOGS)
    r = _stream(client, filters={"document_ids": ["dogs"]})
    assert _events(r)[1] == ("token", {"text": NO_CONTEXT_ANSWER})
    assert llm.calls == []


@pytest.mark.parametrize("status", [502, 503, 504])
def test_error_before_first_token_keeps_http_status(client, llm, status):
    _ingest(client, "cats", CATS)
    llm.error = LLMError(status, f"failed {status}")
    r = _stream(client)
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": f"failed {status}"}


def test_error_after_first_token_becomes_error_event(client, llm):
    _ingest(client, "cats", CATS)
    llm.mid_stream_error = LLMError(502, "LLM provider declined to answer")
    r = _stream(client)
    assert r.status_code == 200
    events = _events(r)
    assert [name for name, _ in events] == ["sources", "token", "token", "error"]
    assert events[-1] == ("error", {"detail": "LLM provider declined to answer"})


def test_unexpected_mid_stream_failure_sends_generic_error(client, llm):
    _ingest(client, "cats", CATS)
    llm.mid_stream_error = RuntimeError("socket details that must not leak")
    events = _events(_stream(client))
    assert events[-1] == ("error", {"detail": "The answer was interrupted"})


def test_missing_key_returns_503(settings, store, embedder):
    settings.openai_api_key = None
    with TestClient(create_app(settings, embedder=embedder, store=store)) as c:
        r = c.post("/ask/stream", json={"question": "why do cats purr"})
        assert r.status_code == 503
        assert r.json() == {"detail": "LLM provider not configured"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": " "},
        {"question": "ok", "top_k": 0},
        {"question": "ok", "filters": {"x": 1}},
    ],
)
def test_invalid_input_returns_422(client, llm, payload):
    assert client.post("/ask/stream", json=payload).status_code == 422
    assert llm.calls == []
