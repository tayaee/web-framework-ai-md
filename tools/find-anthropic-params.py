#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27"]
# ///
"""find-anthropic-params — Anthropic(Claude) 모델별로 실제 max_tokens 값을
탐색해서 engine/aimd/llm_params.json에 누적 저장한다.

Anthropic Messages API는 OpenAI 호환이 아니라(x-api-key 헤더, /messages
엔드포인트) 다른 find-*-params.py 스크립트들과 프로토콜이 다르다. 또한
max_tokens/max_completion_tokens 구분이 없고 "max_tokens" 하나만 사용하므로,
여기서 탐색하는 건 그 값(모델의 컨텍스트/출력 한도) 하나뿐이다.

사용법:
    export ANTHROPIC_API_KEY=...     # 또는 LLM_API_KEY
    uv run tools/find-anthropic-params.py
    uv run tools/find-anthropic-params.py --models claude-sonnet-4-6,claude-sonnet-4-5

--models를 생략하면 DEFAULT_MODELS (claude-sonnet-4-6) 고정 목록만 검사한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _llm_ping_common import (  # noqa: E402
    SPA_SYSTEM,
    load_spec_text,
    probe_model_anthropic,
    update_llm_params,
)

BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODELS = ("claude-sonnet-4-6",)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        help=f"comma-separated model names to probe (default: {', '.join(DEFAULT_MODELS)})",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY (or LLM_API_KEY) is not set", file=sys.stderr)
        return 1

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        models = list(DEFAULT_MODELS)

    spec_text = load_spec_text()
    results: dict[str, dict] = {}
    failures: dict[str, str] = {}

    for model in models:
        print(f"probing {model} ...", file=sys.stderr)
        try:
            entry = probe_model_anthropic(
                api_key=api_key, base_url=BASE_URL, model=model, system=SPA_SYSTEM, user=spec_text
            )
        except (httpx.HTTPStatusError, httpx.TimeoutException, TimeoutError) as e:
            failures[model] = str(e)
            print(f"  FAILED: {e}", file=sys.stderr)
            continue
        results[model] = entry
        update_llm_params(model, entry)
        print(f"  OK: {entry}", file=sys.stderr)

    print("\n=== summary ===")
    for model, entry in results.items():
        print(f"  {model}: {entry}")
    for model, error in failures.items():
        print(f"  {model}: FAILED ({error})")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
