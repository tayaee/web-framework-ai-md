"""Pure request-shape builders shared by the real runtime (aimd.llm) and the
offline probing scripts (tools/find-<provider>-params.py).

Deliberately zero third-party imports (no openai, no httpx) so that
tools/_llm_ping_common.py can import this module directly -- via a plain
sys.path insert of engine/, no extra PEP 723 dependency needed -- and get the
exact same request shape the engine sends at runtime. That's what makes a
successful probe an actual guarantee about the real call, not just a
similar-looking duplicate.
"""
from __future__ import annotations


def build_openai_params(
    *, model: str, system: str, user: str, token_param: str, tokens: int, omit_temperature: bool = False
) -> dict:
    """Builds the kwargs for client.chat.completions.create(...)."""
    params: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        token_param: tokens,
    }
    if not omit_temperature:
        params["temperature"] = 0.0
    return params


def build_anthropic_body(*, model: str, system: str, user: str, tokens: int, omit_temperature: bool = False) -> dict:
    """Builds the JSON body for POST /messages (Anthropic Messages API)."""
    body: dict = {
        "model": model,
        "max_tokens": tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if not omit_temperature:
        body["temperature"] = 0.0
    return body
