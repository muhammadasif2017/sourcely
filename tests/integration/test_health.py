def test_health_reports_state(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "chunks_indexed": 0,
        "embedding_model": "fake-embedder",
        "llm_provider": "openai",
        "llm_model": "fake-model",
        "llm_configured": True,
    }
