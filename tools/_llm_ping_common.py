"""Shared helpers for tools/find-<provider>-params.py scripts.

Not a standalone script -- imported by the per-provider ping scripts, which
each declare their own PEP 723 dependencies (this module only needs stdlib,
so it adds nothing extra to any of them).

Each ping script's job: given one or more model names, fire a real request at
that provider using src/tetris.ai.md as the spec, discover which token-limit
parameter name and value the model actually accepts, and accumulate the
result into engine/aimd/llm_params.json (keyed by model name) so the engine's
llm.py can load it at runtime instead of guessing via prefix heuristics or
burning retries on trial and error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import openai

ANTHROPIC_VERSION = "2023-06-01"

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "src" / "tetris.ai.md"
ENGINE_DIR = REPO_ROOT / "engine"
LLM_PARAMS_PATH = ENGINE_DIR / "aimd" / "llm_params.json"

# aimd.request_builders has zero third-party imports (no openai/httpx), so
# this import costs nothing extra for any find-<provider>-params.py script's
# PEP 723 dependencies -- it's the actual engine code, not a lookalike copy,
# so a probe succeeding is a real guarantee about the request the engine
# sends at runtime (see engine/aimd/llm.py).
sys.path.insert(0, str(ENGINE_DIR))
from aimd.request_builders import build_anthropic_body, build_openai_params  # noqa: E402

# Kept in sync manually with engine/aimd/prompts.py:SPA_SYSTEM -- duplicated
# here so each ping script stays a single self-contained PEP 723 file with no
# dependency on the engine package's import path.
SPA_SYSTEM = (
    "You are AIMD, a compiler that turns a natural-language specification "
    "into a working web page. Output one complete, self-contained HTML5 file. "
    "Hard constraints:\n"
    "- Single file: all CSS in <style>, all JavaScript in <script>. "
    "No external libraries, no CDN links, no fetch to other origins.\n"
    "- The file must start with <!DOCTYPE html> and contain <html>, <head>, <body>.\n"
    "- Implement every requirement in the specification.\n"
    "- Output ONLY the raw HTML code. No markdown fences, no explanations."
)

# Token-value ladder tried per token-param name, largest first. Mirrors
# engine/aimd/llm.py's _MIN_TOKENS floor / halving steps from a 100000 start.
TOKEN_VALUE_LADDER = (128000, 100000, 50000, 25000, 12500, 6250, 4096)

# Try "max_tokens" first (the older/more common name) before falling back to
# "max_completion_tokens" (required by o1/o3/o4/gpt-5.x-style reasoning models).
TOKEN_PARAM_CANDIDATES = ("max_tokens", "max_completion_tokens")

# Some (esp. free-tier) models take far longer than a normal API call to
# generate a full response, especially when max_tokens is set high -- without
# a bound the openai/httpx client default (minutes) makes a single slow model
# hang the whole probe run. A timeout here is treated the same as a rejected
# combination (see probe_model/probe_model_anthropic): log it and move on to
# the next token_param/value instead of hanging.
REQUEST_TIMEOUT_S = 60.0

# Retries for openai.RateLimitError (429) within a single attempt(), before
# giving up on that combo and moving on (see probe_model).
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_S = 15.0


def load_spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def load_llm_params() -> dict:
    if not LLM_PARAMS_PATH.exists():
        return {}
    try:
        with LLM_PARAMS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def update_llm_params(model: str, entry: dict) -> None:
    """Merge entry into llm_params.json under key `model` and write it back,
    sorted by model name for stable diffs."""
    data = load_llm_params()
    data[model] = entry
    LLM_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LLM_PARAMS_PATH.open("w", encoding="utf-8") as f:
        json.dump(dict(sorted(data.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")


def _call_with_deadline(fn, *, timeout_s: float):
    """Runs fn() with a hard wall-clock deadline.

    httpx's own `timeout=` (used inside fn) only bounds the gap between
    reads/chunks, not the total request time -- a backend that keeps
    trickling bytes (common on free/shared tiers under load) can stay under
    that per-chunk timeout while the overall call runs for minutes. This
    forces an actual deadline: if fn() hasn't returned by timeout_s, raise
    TimeoutError and move on (the leaked background thread is abandoned,
    which is fine for a one-shot probing script)."""
    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        result = future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        pool.shutdown(wait=False)  # abandon the still-running call; don't block on it
        raise TimeoutError(f"no response within {timeout_s}s (wall-clock deadline)") from None
    pool.shutdown(wait=False)
    return result


def probe_model(client: "openai.OpenAI", model: str, system: str, user: str) -> dict:
    """Fires real requests at `model`, walking TOKEN_PARAM_CANDIDATES x
    TOKEN_VALUE_LADDER until one combination succeeds. Raises the last
    openai.BadRequestError if nothing works. Shared by every
    find-<provider>-params.py script since the OpenAI-compatible request
    shape and 400-driven retry rule are identical across providers -- only
    base_url/api_key/model discovery differ per provider.

    Some models (e.g. gpt-5.6-luna) reject temperature=0.0 outright ("Only
    the default (1) value is supported") -- once that's detected, temperature
    is dropped from the request entirely (not retried at 1.0, since callers
    of llm.chat always want deterministic temperature=0.0 when it's
    supported) and the current token_param/tokens combo is retried without
    consuming a ladder step. The returned entry then carries
    "omit_temperature": True so engine/aimd/llm.py knows to skip it too."""
    import time

    import openai  # local import: only needed here, at call time, in the uv-run subprocess

    def attempt(token_param: str, tokens: int, use_temperature: bool):
        params = build_openai_params(
            model=model,
            system=system,
            user=user,
            token_param=token_param,
            tokens=tokens,
            omit_temperature=not use_temperature,
        )
        print(
            f"  trying model={model} token_param={token_param} tokens={tokens} "
            f"temperature={0.0 if use_temperature else 'omitted'} ...",
            file=sys.stderr,
        )
        # Free/shared-tier backends (e.g. openrouter/free) commonly bounce
        # requests off an upstream provider's rate limit -- transient, and
        # unrelated to whether this token_param/tokens combo is valid. Retry
        # the exact same request a few times with a short backoff before
        # giving up on it.
        for rate_limit_attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            try:
                return _call_with_deadline(
                    lambda: client.chat.completions.create(**params, timeout=REQUEST_TIMEOUT_S),
                    timeout_s=REQUEST_TIMEOUT_S,
                )
            except openai.RateLimitError as e:
                if rate_limit_attempt >= RATE_LIMIT_MAX_RETRIES:
                    raise
                print(
                    f"  rate-limited (attempt {rate_limit_attempt + 1}/{RATE_LIMIT_MAX_RETRIES}), "
                    f"retrying in {RATE_LIMIT_BACKOFF_S}s: {e}",
                    file=sys.stderr,
                )
                time.sleep(RATE_LIMIT_BACKOFF_S)
        raise AssertionError("unreachable")

    last_error: Exception | None = None
    omit_temperature = False
    for token_param in TOKEN_PARAM_CANDIDATES:
        for tokens in TOKEN_VALUE_LADDER:
            try:
                response = attempt(token_param, tokens, use_temperature=not omit_temperature)
            except openai.BadRequestError as e:
                message = str(e)
                if not omit_temperature and "temperature" in message:
                    print(
                        f"  temperature=0.0 rejected, dropping temperature for model={model} "
                        "and retrying the same combo",
                        file=sys.stderr,
                    )
                    omit_temperature = True
                    try:
                        response = attempt(token_param, tokens, use_temperature=False)
                    except (openai.BadRequestError, openai.APITimeoutError, openai.RateLimitError, TimeoutError) as e2:
                        last_error = e2
                        continue
                else:
                    last_error = e
                    continue
            except (openai.APITimeoutError, TimeoutError) as e:
                print(
                    f"  timed out after {REQUEST_TIMEOUT_S}s, treating as rejected: model={model} "
                    f"token_param={token_param} tokens={tokens}",
                    file=sys.stderr,
                )
                last_error = e
                continue
            except openai.RateLimitError as e:
                print(
                    f"  rate-limit retries exhausted, treating as rejected: model={model} "
                    f"token_param={token_param} tokens={tokens}",
                    file=sys.stderr,
                )
                last_error = e
                continue
            content = response.choices[0].message.content
            if content:
                entry = {"token_param": token_param, "max_tokens_value": tokens}
                if omit_temperature:
                    entry["omit_temperature"] = True
                return entry
    assert last_error is not None
    raise last_error


def probe_model_anthropic(*, api_key: str, base_url: str, model: str, system: str, user: str) -> dict:
    """Fires real requests at `model` via the Anthropic Messages API, walking
    TOKEN_VALUE_LADDER for "max_tokens" (Anthropic has no
    max_completion_tokens split -- "max_tokens" is the only, mandatory,
    parameter) until one value succeeds. Raises the last httpx.HTTPStatusError
    if nothing works."""
    import httpx

    last_error: Exception | None = None
    with httpx.Client(
        base_url=base_url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        timeout=REQUEST_TIMEOUT_S,
    ) as client:
        for tokens in TOKEN_VALUE_LADDER:
            print(f"  trying model={model} token_param=max_tokens tokens={tokens} ...", file=sys.stderr)
            try:
                response = _call_with_deadline(
                    lambda: client.post(
                        "/messages",
                        json=build_anthropic_body(model=model, system=system, user=user, tokens=tokens),
                    ),
                    timeout_s=REQUEST_TIMEOUT_S,
                )
            except (httpx.TimeoutException, TimeoutError) as e:
                print(
                    f"  timed out after {REQUEST_TIMEOUT_S}s, treating as rejected: model={model} tokens={tokens}",
                    file=sys.stderr,
                )
                last_error = e
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                last_error = e
                continue
            blocks = response.json().get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if text:
                return {"token_param": "max_tokens", "max_tokens_value": tokens}
    assert last_error is not None
    raise last_error
