import json
import logging
from pathlib import Path

import httpx
import openai

from .config import Settings
from .request_builders import build_anthropic_body, build_openai_params

log = logging.getLogger("aimd.llm")

_MIN_TOKENS = 4096
_MAX_CLAMP_RETRIES = 6
_ANTHROPIC_VERSION = "2023-06-01"

# Populated and kept up to date by tools/ping-<provider>-models.py, which
# fires real requests at each model and records which token-limit param name
# (and safe value) it actually accepts. Keyed by exact model name.
LLM_PARAMS_PATH = Path(__file__).resolve().parent / "llm_params.json"

# Model name prefixes known to require "max_completion_tokens" instead of
# "max_tokens" (OpenAI reasoning/newer models). Matched against
# settings.model.lower(). Used only when the model has no entry in
# llm_params.json. Anything matching neither starts with "max_tokens" and
# falls back to runtime trial-and-error (see _chat_openai_compatible).
_MAX_COMPLETION_TOKENS_MODEL_PREFIXES = (
    "o1",
    "o3",
    "o4",
    "gpt-5",
)


def _load_llm_params() -> dict:
    try:
        with LLM_PARAMS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        log.warning("llm_params.json is invalid JSON, ignoring: %s", LLM_PARAMS_PATH)
        return {}


def _resolve_call_params(model: str, requested_tokens: int) -> tuple[str, int, bool, str]:
    """Returns (token_param, tokens, omit_temperature, source) for the given model.

    source is one of "llm_params.json" (exact match found -- known-good
    param name, and tokens clamped to the model's known-good value),
    "prefix-heuristic" (no entry, but the model name matches a known
    reasoning-model prefix), or "default" (no info at all; runtime
    trial-and-error in _chat_openai_compatible takes it from here).

    omit_temperature is True for models recorded (via
    tools/find-<provider>-params.py) as rejecting temperature=0.0 outright
    (e.g. gpt-5.6-luna, which only accepts the default temperature=1), and
    also for the prefix-heuristic path -- every model matching
    _MAX_COMPLETION_TOKENS_MODEL_PREFIXES is an OpenAI reasoning model, and
    those all reject temperature=0.0 the same way (e.g. o4-mini: "Unsupported
    value: 'temperature' does not support 0.0 with this model").
    """
    known = _load_llm_params().get(model)
    if known:
        token_param = known.get("token_param", "max_tokens")
        known_max = known.get("max_tokens_value")
        tokens = min(requested_tokens, known_max) if known_max else requested_tokens
        return token_param, tokens, bool(known.get("omit_temperature")), "llm_params.json"
    if model.lower().startswith(_MAX_COMPLETION_TOKENS_MODEL_PREFIXES):
        return "max_completion_tokens", requested_tokens, True, "prefix-heuristic"
    return "max_tokens", requested_tokens, False, "default"


def _make_client(settings: Settings) -> openai.OpenAI:
    """Kept separate so it can be monkeypatched in tests."""
    return openai.OpenAI(api_key=settings.api_key, base_url=settings.base_url)


def chat(system: str, user: str, settings: Settings) -> str:
    """Single completion call with messages=[{system},{user}], temperature=0.0.

    The call style branches on settings.provider:
    - "claude": Anthropic Messages API (x-api-key header, /messages endpoint)
    - anything else ("openai" default): an OpenAI Chat Completions-compatible
      endpoint (openai / deepseek / minimax / openrouter, etc.)

    Both paths follow the same max_tokens clamp-and-retry rule: start with
    settings.max_tokens, and if it's an HTTP 400 whose error string contains
    "max_tokens" or "token", halve it and retry. Up to _MAX_CLAMP_RETRIES
    times, with a floor of _MIN_TOKENS. Any other exception propagates as-is.

    Returns the response text (str) on success. Raises RuntimeError on an empty response.
    """
    log.info("llm call start provider=%s model=%s", settings.provider, settings.model)
    if settings.provider == "claude":
        result = _chat_anthropic(system, user, settings)
    else:
        result = _chat_openai_compatible(system, user, settings)
    log.info("llm call done provider=%s model=%s", settings.provider, settings.model)
    return result


def _chat_openai_compatible(system: str, user: str, settings: Settings) -> str:
    client = _make_client(settings)
    token_param, tokens, omit_temperature, source = _resolve_call_params(settings.model, settings.max_tokens)
    log.info(
        "llm params resolved provider=openai model=%s source=%s token_param=%s tokens=%d omit_temperature=%s",
        settings.model,
        source,
        token_param,
        tokens,
        omit_temperature,
    )

    halving_attempts = 0
    while True:
        params = build_openai_params(
            model=settings.model,
            system=system,
            user=user,
            token_param=token_param,
            tokens=tokens,
            omit_temperature=omit_temperature,
        )
        log.debug("llm request params provider=openai %r", params)
        try:
            response = client.chat.completions.create(**params)
        except openai.BadRequestError as e:
            message = str(e)
            log.debug("llm error response provider=openai body=%s", getattr(e, "body", None))
            if "max_completion_tokens" in message and token_param != "max_completion_tokens":
                # Some newer models (e.g. gpt-5.x) reject max_tokens outright and
                # require max_completion_tokens instead -- switch the param name,
                # not the token value, and retry without consuming the clamp budget.
                token_param = "max_completion_tokens"
                log.warning("max_tokens unsupported, switching to max_completion_tokens")
                continue
            if "temperature" in message and not omit_temperature:
                # Defense in depth for reasoning models not yet covered by
                # llm_params.json or the prefix heuristic: they reject
                # temperature=0.0 and only accept the default (1).
                omit_temperature = True
                log.warning("temperature unsupported, omitting it and retrying")
                continue
            if "max_tokens" not in message and "token" not in message:
                raise
            if tokens <= _MIN_TOKENS or halving_attempts >= _MAX_CLAMP_RETRIES:
                raise
            halving_attempts += 1
            tokens = max(tokens // 2, _MIN_TOKENS)
            log.warning("max_tokens rejected, retrying with %d", tokens)
            continue

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("empty LLM response")
        return content


def _make_anthropic_client(settings: Settings) -> httpx.Client:
    """Kept separate so it can be monkeypatched in tests."""
    return httpx.Client(
        base_url=settings.base_url,
        headers={
            "x-api-key": settings.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )


def _chat_anthropic(system: str, user: str, settings: Settings) -> str:
    client = _make_anthropic_client(settings)
    # Anthropic always uses "max_tokens" (no max_completion_tokens split), so
    # only the tokens/omit_temperature half of _resolve_call_params applies
    # here -- it's shared with the openai path purely to clamp to whatever
    # tools/find-<provider>-params.py already verified for this model
    # (e.g. claude-sonnet-4-6 -> 100000) instead of blindly sending
    # settings.max_tokens and burning halving retries to find that out again.
    _, tokens, omit_temperature, source = _resolve_call_params(settings.model, settings.max_tokens)
    log.info(
        "llm params resolved provider=claude model=%s source=%s tokens=%d omit_temperature=%s",
        settings.model,
        source,
        tokens,
        omit_temperature,
    )

    last_error: httpx.HTTPStatusError | None = None
    for _ in range(_MAX_CLAMP_RETRIES + 1):
        body = build_anthropic_body(
            model=settings.model, system=system, user=user, tokens=tokens, omit_temperature=omit_temperature
        )
        log.debug("llm request params provider=claude %r", body)
        response = client.post("/messages", json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_body = response.text
            log.debug("llm error response provider=claude body=%s", error_body)
            if response.status_code != 400 or (
                "max_tokens" not in error_body and "token" not in error_body
            ):
                raise
            last_error = e
            if tokens <= _MIN_TOKENS:
                raise
            tokens = max(tokens // 2, _MIN_TOKENS)
            log.warning("max_tokens rejected, retrying with %d", tokens)
            continue

        data = response.json()
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise RuntimeError("empty LLM response")
        return text

    assert last_error is not None
    raise last_error
