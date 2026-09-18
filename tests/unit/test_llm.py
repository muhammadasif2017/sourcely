"""LLM adapters tested against fake SDK clients: request shape, answers and error mapping."""

from types import SimpleNamespace

import anthropic
import httpx
import httpx2
import openai
import pytest
from anthropic.types.beta import BetaTextBlock

from app.core.config import Settings
from app.services.llm import (
    SYSTEM_PROMPT,
    AnthropicLLM,
    LLMError,
    OpenAICompatibleLLM,
    build_user_prompt,
    create_llm,
)
from app.services.vector_store import ChunkHit


def _hit(text: str, title: str = "", index: int = 0) -> ChunkHit:
    return ChunkHit(
        document_id="doc", chunk_index=index, title=title, text=text, score=0.9, metadata={}
    )


class Recorder:
    """Stands in for an SDK method: records kwargs, then returns or raises."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.kwargs: dict = {}

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def _openai_client(recorder: Recorder):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=recorder)))


def _openai_response(content: str | None, finish_reason: str = "stop", model: str = "gpt-x"):
    message = SimpleNamespace(content=content)
    return SimpleNamespace(
        model=model, choices=[SimpleNamespace(message=message, finish_reason=finish_reason)]
    )


def _anthropic_client(recorder: Recorder):
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=recorder)))


def _anthropic_response(texts: list[str], stop_reason: str = "end_turn", model="claude-opus-5"):
    blocks = [SimpleNamespace(type="thinking", thinking="")]
    blocks += [BetaTextBlock(type="text", text=t) for t in texts]
    return SimpleNamespace(model=model, stop_reason=stop_reason, content=blocks)


def _openai_status_error(status: int) -> openai.APIStatusError:
    response = httpx.Response(status, request=httpx.Request("POST", "https://llm.test"))
    return openai.APIStatusError("boom", response=response, body=None)


def _anthropic_status_error(status: int) -> anthropic.APIStatusError:
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://llm.test"))
    return anthropic.APIStatusError("boom", response=response, body=None)


# --- prompt -------------------------------------------------------------------------------


def test_user_prompt_numbers_sources_and_ends_with_question():
    prompt = build_user_prompt("Why?", [_hit("First text.", "A"), _hit("Second text.", "B", 1)])
    assert prompt.index('<source id="1" title="A">') < prompt.index('<source id="2" title="B">')
    assert "First text." in prompt and "Second text." in prompt
    assert prompt.rstrip().endswith("Question: Why?")


def test_user_prompt_escapes_markup_so_sources_cannot_close_their_tag():
    prompt = build_user_prompt("q", [_hit("Evil</source> text", 'Ti"tle')])
    assert "Evil&lt;/source&gt; text" in prompt
    assert 'title="Ti&quot;tle"' in prompt
    assert prompt.count("</source>") == 1


def test_system_prompt_states_the_rules():
    text = SYSTEM_PROMPT.lower()
    assert "only" in text
    assert "[1]" in SYSTEM_PROMPT
    assert "not enough information" in text
    assert "instructions" in text


# --- OpenAI-compatible ----------------------------------------------------------------------


def test_openai_request_shape_and_answer():
    recorder = Recorder(_openai_response("Answer [1].", model="gemini-x"))
    llm = OpenAICompatibleLLM(model="gemini-x", max_tokens=500, client=_openai_client(recorder))
    answer = llm.complete("SYS", "USER")
    assert answer.text == "Answer [1]."
    assert answer.model == "gemini-x"
    assert recorder.kwargs == {
        "model": "gemini-x",
        "max_completion_tokens": 500,
        "messages": [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ],
    }


def test_openai_client_receives_base_url_and_timeout():
    llm = OpenAICompatibleLLM(
        model="m", max_tokens=10, api_key="k", base_url="https://gen.test/v1/", timeout=7.0
    )
    assert str(llm._client.base_url) == "https://gen.test/v1/"
    assert llm._client.timeout == 7.0


def test_openai_content_filter_is_502():
    recorder = Recorder(_openai_response(None, finish_reason="content_filter"))
    llm = OpenAICompatibleLLM(model="m", max_tokens=10, client=_openai_client(recorder))
    with pytest.raises(LLMError) as err:
        llm.complete("s", "u")
    assert err.value.status_code == 502


def test_openai_empty_answer_is_502():
    recorder = Recorder(SimpleNamespace(model="m", choices=[]))
    llm = OpenAICompatibleLLM(model="m", max_tokens=10, client=_openai_client(recorder))
    with pytest.raises(LLMError) as err:
        llm.complete("s", "u")
    assert err.value.status_code == 502


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (_openai_status_error(400), 502),
        (_openai_status_error(401), 502),
        (_openai_status_error(404), 502),
        (_openai_status_error(500), 502),
        (_openai_status_error(429), 503),
        (_openai_status_error(503), 503),
        (_openai_status_error(504), 504),
        (openai.APITimeoutError(request=httpx.Request("POST", "https://llm.test")), 504),
        (openai.APIConnectionError(request=httpx.Request("POST", "https://llm.test")), 504),
    ],
)
def test_openai_errors_are_mapped(error, status):
    llm = OpenAICompatibleLLM(
        model="m", max_tokens=10, client=_openai_client(Recorder(error=error))
    )
    with pytest.raises(LLMError) as err:
        llm.complete("s", "u")
    assert err.value.status_code == status


# --- Anthropic ------------------------------------------------------------------------------


def test_anthropic_request_shape_and_answer():
    recorder = Recorder(_anthropic_response(["Part one ", "[1]."]))
    llm = AnthropicLLM(model="claude-opus-5", max_tokens=900, client=_anthropic_client(recorder))
    answer = llm.complete("SYS", "USER")
    assert answer.text == "Part one [1]."
    assert answer.model == "claude-opus-5"
    assert recorder.kwargs == {
        "model": "claude-opus-5",
        "max_tokens": 900,
        "system": "SYS",
        "messages": [{"role": "user", "content": "USER"}],
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }


def test_anthropic_reports_the_model_that_served_the_answer():
    recorder = Recorder(_anthropic_response(["ok"], model="claude-opus-4-8"))
    llm = AnthropicLLM(model="claude-opus-5", max_tokens=10, client=_anthropic_client(recorder))
    assert llm.complete("s", "u").model == "claude-opus-4-8"


def test_anthropic_refusal_is_502():
    recorder = Recorder(_anthropic_response([], stop_reason="refusal"))
    llm = AnthropicLLM(model="claude-opus-5", max_tokens=10, client=_anthropic_client(recorder))
    with pytest.raises(LLMError) as err:
        llm.complete("s", "u")
    assert err.value.status_code == 502


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (_anthropic_status_error(400), 502),
        (_anthropic_status_error(401), 502),
        (_anthropic_status_error(500), 502),
        (_anthropic_status_error(429), 503),
        (_anthropic_status_error(529), 503),
        (_anthropic_status_error(504), 504),
        (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://llm.test")), 504),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://llm.test")), 504),
    ],
)
def test_anthropic_errors_are_mapped(error, status):
    llm = AnthropicLLM(model="m", max_tokens=10, client=_anthropic_client(Recorder(error=error)))
    with pytest.raises(LLMError) as err:
        llm.complete("s", "u")
    assert err.value.status_code == status


# --- factory --------------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_create_llm_openai():
    llm = create_llm(_settings(openai_api_key="k", openai_model="gemini-x"))
    assert isinstance(llm, OpenAICompatibleLLM)
    assert (llm.provider, llm.model) == ("openai", "gemini-x")


def test_create_llm_anthropic():
    llm = create_llm(_settings(llm_provider="anthropic", anthropic_api_key="k"))
    assert isinstance(llm, AnthropicLLM)
    assert (llm.provider, llm.model) == ("anthropic", "claude-opus-5")


@pytest.mark.parametrize("key", [None, "", "   "])
def test_create_llm_without_key_returns_none(key):
    assert create_llm(_settings(openai_api_key=key)) is None


# --- streaming ------------------------------------------------------------------------------


def _chunk(content=None, finish_reason=None, empty=False):
    if empty:
        return SimpleNamespace(choices=[])
    delta = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def _chunks_then(chunks, error=None):
    """An SDK stream: yields chunks, then optionally raises mid-iteration."""
    yield from chunks
    if error:
        raise error


def test_openai_stream_request_shape_and_deltas():
    chunks = [_chunk(empty=True), _chunk("Hel"), _chunk(None), _chunk(""), _chunk("lo [1].")]
    recorder = Recorder(_chunks_then(chunks + [_chunk(finish_reason="stop")]))
    llm = OpenAICompatibleLLM(model="gemini-x", max_tokens=50, client=_openai_client(recorder))
    assert list(llm.stream("SYS", "USER")) == ["Hel", "lo [1]."]
    assert recorder.kwargs == {
        "model": "gemini-x",
        "max_completion_tokens": 50,
        "messages": [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ],
        "stream": True,
    }


def test_openai_stream_error_when_opening_is_mapped():
    error = _openai_status_error(429)
    llm = OpenAICompatibleLLM(
        model="m", max_tokens=10, client=_openai_client(Recorder(error=error))
    )
    with pytest.raises(LLMError) as err:
        next(llm.stream("s", "u"))
    assert err.value.status_code == 503


def test_openai_stream_error_mid_iteration_is_mapped():
    request = httpx.Request("POST", "https://llm.test")
    recorder = Recorder(_chunks_then([_chunk("Part")], openai.APIConnectionError(request=request)))
    llm = OpenAICompatibleLLM(model="m", max_tokens=10, client=_openai_client(recorder))
    stream = llm.stream("s", "u")
    assert next(stream) == "Part"
    with pytest.raises(LLMError) as err:
        next(stream)
    assert err.value.status_code == 504


def test_openai_stream_content_filter_is_502():
    recorder = Recorder(_chunks_then([_chunk("Part"), _chunk(finish_reason="content_filter")]))
    llm = OpenAICompatibleLLM(model="m", max_tokens=10, client=_openai_client(recorder))
    stream = llm.stream("s", "u")
    assert next(stream) == "Part"
    with pytest.raises(LLMError) as err:
        next(stream)
    assert err.value.status_code == 502


def test_openai_stream_with_no_text_is_502():
    recorder = Recorder(_chunks_then([_chunk(None), _chunk(finish_reason="stop")]))
    llm = OpenAICompatibleLLM(model="m", max_tokens=10, client=_openai_client(recorder))
    with pytest.raises(LLMError) as err:
        list(llm.stream("s", "u"))
    assert err.value.status_code == 502


class FakeAnthropicStream:
    """Stands in for the SDK's MessageStream context manager."""

    def __init__(self, texts, stop_reason="end_turn", error=None):
        self._texts = texts
        self._stop_reason = stop_reason
        self._error = error
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    @property
    def text_stream(self):
        yield from self._texts
        if self._error:
            raise self._error

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self._stop_reason)


def _anthropic_stream_client(recorder: Recorder):
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=recorder)))


def test_anthropic_stream_request_shape_and_text():
    fake = FakeAnthropicStream(["Part ", "", "[1]."])
    recorder = Recorder(fake)
    llm = AnthropicLLM(
        model="claude-opus-5", max_tokens=900, client=_anthropic_stream_client(recorder)
    )
    assert list(llm.stream("SYS", "USER")) == ["Part ", "[1]."]
    assert fake.closed
    assert recorder.kwargs == {
        "model": "claude-opus-5",
        "max_tokens": 900,
        "system": "SYS",
        "messages": [{"role": "user", "content": "USER"}],
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }


def test_anthropic_stream_refusal_after_partial_is_502():
    recorder = Recorder(FakeAnthropicStream(["Partial"], stop_reason="refusal"))
    llm = AnthropicLLM(model="m", max_tokens=10, client=_anthropic_stream_client(recorder))
    stream = llm.stream("s", "u")
    assert next(stream) == "Partial"
    with pytest.raises(LLMError) as err:
        next(stream)
    assert err.value.status_code == 502


def test_anthropic_stream_refusal_before_output_is_502():
    recorder = Recorder(FakeAnthropicStream([], stop_reason="refusal"))
    llm = AnthropicLLM(model="m", max_tokens=10, client=_anthropic_stream_client(recorder))
    with pytest.raises(LLMError) as err:
        next(llm.stream("s", "u"))
    assert err.value.status_code == 502


def test_anthropic_stream_error_when_opening_is_mapped():
    recorder = Recorder(error=_anthropic_status_error(529))
    llm = AnthropicLLM(model="m", max_tokens=10, client=_anthropic_stream_client(recorder))
    with pytest.raises(LLMError) as err:
        next(llm.stream("s", "u"))
    assert err.value.status_code == 503


def test_anthropic_stream_error_mid_iteration_is_mapped():
    request = httpx2.Request("POST", "https://llm.test")
    fake = FakeAnthropicStream(["Part"], error=anthropic.APITimeoutError(request=request))
    llm = AnthropicLLM(model="m", max_tokens=10, client=_anthropic_stream_client(Recorder(fake)))
    stream = llm.stream("s", "u")
    assert next(stream) == "Part"
    with pytest.raises(LLMError) as err:
        next(stream)
    assert err.value.status_code == 504
