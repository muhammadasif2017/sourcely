import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**overrides) -> Settings:
    # _env_file=None keeps a developer's local .env from leaking into the test.
    return Settings(_env_file=None, **overrides)


def test_defaults_match_spec(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_BASE_URL",
        "LLM_PROVIDER",
        "MIN_RELEVANCE",
        "EMBEDDING_QUERY_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)
    s = make()
    assert s.llm_provider == "openai"
    assert s.anthropic_model == "claude-opus-5"
    assert s.openai_base_url is None
    assert s.embedding_model == "BAAI/bge-small-en-v1.5"
    assert (s.chunk_size, s.chunk_overlap) == (800, 120)
    assert s.default_top_k == 4
    assert s.max_document_chars == 200_000
    assert s.min_relevance == 0.58
    assert s.embedding_query_prefix.startswith("Represent this sentence")


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValidationError, match="chunk_overlap"):
        make(chunk_size=100, chunk_overlap=100)


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        make(llm_provider="cohere")


def test_llm_configured_follows_active_provider_key():
    assert make(llm_provider="openai", openai_api_key="k").llm_configured
    assert not make(llm_provider="openai", openai_api_key=None).llm_configured
    assert not make(
        llm_provider="anthropic", anthropic_api_key=None, openai_api_key="k"
    ).llm_configured
    assert make(llm_provider="anthropic", anthropic_api_key="k").llm_configured


def test_blank_key_counts_as_missing():
    assert not make(llm_provider="openai", openai_api_key="   ").llm_configured


def test_active_model_follows_provider():
    assert make(llm_provider="openai", openai_model="m1").llm_model == "m1"
    assert make(llm_provider="anthropic", anthropic_model="m2").llm_model == "m2"
