import json
from pathlib import Path

import httpx
import openai
import pytest
from aimd import llm
from aimd.config import Settings


def make_settings(max_tokens: int = 8192) -> Settings:
    return Settings(
        api_key="k",
        base_url="http://t",
        model="MiniMax-M3",
        max_tokens=max_tokens,
        src_dir=Path("./src"),
        dist_dir=Path("./dist"),
    )


def bad_request(message: str) -> openai.BadRequestError:
    return openai.BadRequestError(
        message,
        response=httpx.Response(400, request=httpx.Request("POST", "http://t")),
        body=None,
    )


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, side_effects):
        self.side_effects = list(side_effects)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        effect = self.side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return _FakeResponse(effect)


class _FakeChat:
    def __init__(self, side_effects):
        self.completions = _FakeCompletions(side_effects)


class _FakeClient:
    def __init__(self, side_effects):
        self.chat = _FakeChat(side_effects)


def _install_fake_client(monkeypatch, side_effects):
    fake = _FakeClient(side_effects)
    monkeypatch.setattr(llm, "_make_client", lambda settings: fake)
    return fake


def test_chat_returns_content_with_expected_kwargs(monkeypatch):
    settings = make_settings(max_tokens=8192)
    fake = _install_fake_client(monkeypatch, ["hello"])

    result = llm.chat("sys", "user", settings)

    assert result == "hello"
    assert len(fake.chat.completions.calls) == 1
    kwargs = fake.chat.completions.calls[0]
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 8192
    assert kwargs["model"] == "MiniMax-M3"


def test_chat_retries_without_temperature_on_unsupported_value_error(monkeypatch):
    # Defense in depth (mirrors the real o4-mini failure): a model not covered
    # by llm_params.json or the prefix heuristic still rejects temperature=0.0.
    settings = make_settings(max_tokens=8192)
    fake = _install_fake_client(
        monkeypatch,
        [
            bad_request(
                "Unsupported value: 'temperature' does not support 0.0 with "
                "this model. Only the default (1) value is supported."
            ),
            "hello",
        ],
    )

    result = llm.chat("sys", "user", settings)

    assert result == "hello"
    assert len(fake.chat.completions.calls) == 2
    assert "temperature" in fake.chat.completions.calls[0]
    assert "temperature" not in fake.chat.completions.calls[1]


def test_chat_retries_with_halved_max_tokens_on_token_error(monkeypatch):
    settings = make_settings(max_tokens=8192)
    fake = _install_fake_client(
        monkeypatch,
        [bad_request("max_tokens too large"), "ok after retry"],
    )

    result = llm.chat("sys", "user", settings)

    assert result == "ok after retry"
    assert len(fake.chat.completions.calls) == 2
    assert fake.chat.completions.calls[0]["max_tokens"] == 8192
    assert fake.chat.completions.calls[1]["max_tokens"] == 4096


def test_chat_switches_to_max_completion_tokens_param(monkeypatch):
    settings = make_settings(max_tokens=8192)
    fake = _install_fake_client(
        monkeypatch,
        [
            bad_request(
                "Unsupported parameter: 'max_tokens' is not supported with this "
                "model. Use 'max_completion_tokens' instead."
            ),
            "ok after switch",
        ],
    )

    result = llm.chat("sys", "user", settings)

    assert result == "ok after switch"
    assert len(fake.chat.completions.calls) == 2
    assert "max_tokens" not in fake.chat.completions.calls[1]
    assert fake.chat.completions.calls[1]["max_completion_tokens"] == 8192


def test_chat_propagates_non_token_bad_request(monkeypatch):
    settings = make_settings(max_tokens=8192)
    _install_fake_client(monkeypatch, [bad_request("invalid api key")])

    with pytest.raises(openai.BadRequestError):
        llm.chat("sys", "user", settings)


def test_chat_raises_on_empty_content(monkeypatch):
    settings = make_settings(max_tokens=8192)
    _install_fake_client(monkeypatch, [None])

    with pytest.raises(RuntimeError):
        llm.chat("sys", "user", settings)


def test_chat_stops_retrying_at_min_tokens_floor(monkeypatch):
    min_tokens_x2 = llm._MIN_TOKENS * 2
    settings = make_settings(max_tokens=min_tokens_x2)
    fake = _install_fake_client(
        monkeypatch,
        [
            bad_request("max_tokens too large"),
            bad_request("max_tokens too large"),
        ],
    )

    with pytest.raises(openai.BadRequestError):
        llm.chat("sys", "user", settings)

    assert fake.chat.completions.calls[0]["max_tokens"] == min_tokens_x2
    assert fake.chat.completions.calls[1]["max_tokens"] == llm._MIN_TOKENS


def test_chat_raises_bad_request_when_retries_exhausted_before_floor(monkeypatch):
    settings = make_settings(max_tokens=524288)
    _install_fake_client(
        monkeypatch,
        [bad_request("max_tokens too large")] * (llm._MAX_CLAMP_RETRIES + 1),
    )

    with pytest.raises(openai.BadRequestError):
        llm.chat("sys", "user", settings)


def test_resolve_call_params_uses_llm_params_json_when_present(monkeypatch, tmp_path):
    params_file = tmp_path / "llm_params.json"
    params_file.write_text(
        '{"gpt-5.6-luna": {"token_param": "max_completion_tokens", "max_tokens_value": 128000}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", params_file)

    token_param, tokens, omit_temperature, source = llm._resolve_call_params("gpt-5.6-luna", 200000)

    assert token_param == "max_completion_tokens"
    assert tokens == 128000  # clamped down to the known-good value
    assert omit_temperature is False
    assert source == "llm_params.json"


def test_resolve_call_params_reads_omit_temperature_from_llm_params_json(monkeypatch, tmp_path):
    params_file = tmp_path / "llm_params.json"
    params_file.write_text(
        '{"gpt-5.6-luna": {"token_param": "max_completion_tokens", "max_tokens_value": 128000, '
        '"omit_temperature": true}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", params_file)

    _, _, omit_temperature, _ = llm._resolve_call_params("gpt-5.6-luna", 200000)

    assert omit_temperature is True


def test_resolve_call_params_falls_back_to_prefix_heuristic(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", tmp_path / "missing.json")

    token_param, tokens, omit_temperature, source = llm._resolve_call_params("o4-mini", 100000)

    assert token_param == "max_completion_tokens"
    assert tokens == 100000
    # o4-mini and other reasoning-model prefixes reject temperature=0.0
    # outright (only the default of 1 is supported), so the heuristic path
    # must omit it just like an explicit llm_params.json entry would.
    assert omit_temperature is True
    assert source == "prefix-heuristic"


def test_resolve_call_params_defaults_to_max_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", tmp_path / "missing.json")

    token_param, tokens, omit_temperature, source = llm._resolve_call_params("MiniMax-M3", 100000)

    assert token_param == "max_tokens"
    assert tokens == 100000
    assert omit_temperature is False
    assert source == "default"


def test_chat_uses_llm_params_json_token_param_from_first_call(monkeypatch, tmp_path):
    params_file = tmp_path / "llm_params.json"
    params_file.write_text(
        '{"gpt-5.6-luna": {"token_param": "max_completion_tokens", "max_tokens_value": 4096}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", params_file)
    settings = Settings(
        api_key="k",
        base_url="http://t",
        model="gpt-5.6-luna",
        max_tokens=200000,
        src_dir=Path("./src"),
        dist_dir=Path("./dist"),
    )
    fake = _install_fake_client(monkeypatch, ["ok"])

    result = llm.chat("sys", "user", settings)

    assert result == "ok"
    call = fake.chat.completions.calls[0]
    assert "max_tokens" not in call
    assert call["max_completion_tokens"] == 4096


def test_chat_omits_temperature_when_llm_params_json_says_so(monkeypatch, tmp_path):
    params_file = tmp_path / "llm_params.json"
    params_file.write_text(
        '{"gpt-5.6-luna": {"token_param": "max_completion_tokens", "max_tokens_value": 4096, '
        '"omit_temperature": true}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", params_file)
    settings = Settings(
        api_key="k",
        base_url="http://t",
        model="gpt-5.6-luna",
        max_tokens=200000,
        src_dir=Path("./src"),
        dist_dir=Path("./dist"),
    )
    fake = _install_fake_client(monkeypatch, ["ok"])

    result = llm.chat("sys", "user", settings)

    assert result == "ok"
    call = fake.chat.completions.calls[0]
    assert "temperature" not in call
    assert call["max_completion_tokens"] == 4096


def _make_anthropic_settings(model: str, max_tokens: int) -> Settings:
    return Settings(
        api_key="k",
        base_url="http://t",
        model=model,
        max_tokens=max_tokens,
        src_dir=Path("./src"),
        dist_dir=Path("./dist"),
        provider="claude",
    )


def _install_fake_anthropic_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def fake_make_anthropic_client(settings):
        return httpx.Client(base_url=settings.base_url, transport=transport)

    monkeypatch.setattr(llm, "_make_anthropic_client", fake_make_anthropic_client)


def test_chat_anthropic_clamps_tokens_from_llm_params_json(monkeypatch, tmp_path):
    params_file = tmp_path / "llm_params.json"
    params_file.write_text(
        '{"claude-sonnet-4-6": {"token_param": "max_tokens", "max_tokens_value": 100000}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", params_file)
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    _install_fake_anthropic_client(monkeypatch, handler)
    settings = _make_anthropic_settings("claude-sonnet-4-6", max_tokens=200000)

    result = llm.chat("sys", "user", settings)

    assert result == "ok"
    assert calls[0]["max_tokens"] == 100000  # clamped down from the requested 200000
    assert calls[0]["temperature"] == 0.0


def test_chat_anthropic_ignores_llm_params_json_for_unknown_model(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "LLM_PARAMS_PATH", tmp_path / "missing.json")
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    _install_fake_anthropic_client(monkeypatch, handler)
    settings = _make_anthropic_settings("claude-sonnet-5", max_tokens=8192)

    result = llm.chat("sys", "user", settings)

    assert result == "ok"
    assert calls[0]["max_tokens"] == 8192
