#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.0"]
# ///
"""find-deepseek-params — DeepSeek 모델별로 실제 max_tokens/max_completion_tokens
파라미터 조합을 탐색해서 engine/aimd/llm_params.json에 누적 저장한다.

사용법:
    export DEEPSEEK_API_KEY=...     # 또는 LLM_API_KEY
    uv run tools/find-deepseek-params.py
    uv run tools/find-deepseek-params.py --models deepseek-v4-flash,deepseek-chat

--models를 생략하면 DEFAULT_MODELS (deepseek-v4-flash) 고정 목록만 검사한다.

검사 방식은 tools/find-openai-params.py와 동일: src/tetris.ai.md 스펙으로 실제
chat.completions.create 호출 -> token_param/값을 바꿔가며 재시도 -> 성공한
조합을 llm_params.json[model]에 기록.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import openai

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _llm_ping_common import (  # noqa: E402
    SPA_SYSTEM,
    load_spec_text,
    probe_model,
    update_llm_params,
)

BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODELS = ("deepseek-v4-flash",)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        help=f"comma-separated model names to probe (default: {', '.join(DEFAULT_MODELS)})",
    )
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY (or LLM_API_KEY) is not set", file=sys.stderr)
        return 1

    client = openai.OpenAI(api_key=api_key, base_url=BASE_URL)

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
            entry = probe_model(client, model, SPA_SYSTEM, spec_text)
        except (openai.BadRequestError, openai.APITimeoutError, openai.RateLimitError, TimeoutError) as e:
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
