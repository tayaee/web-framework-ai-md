import logging
from typing import Literal, TypeAlias, cast

from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from .config import Settings
from .prompts import CLASSIFY_SYSTEM

log = logging.getLogger("aimd.classifier")

Target: TypeAlias = Literal["spa", "api"]

_API_KEYWORDS = ["POST", "GET", "PUT", "DELETE", "JSON", "API", "endpoint", "endpoint"]
_SPA_KEYWORDS = ["HTML", "UI", "screen", "page", "rendering", "design", "button", "game"]


def _count_occurrences(text: str, keywords: list[str]) -> int:
    return sum(text.count(k) for k in keywords)


def classify_by_keywords(spec_text: str) -> Target:
    """Case-sensitive keyword count. Returns "api" if the api score exceeds the
    spa score, otherwise "spa".
    (On a tie, "spa" — the landing-page side is the safer default)"""
    api_score = _count_occurrences(spec_text, _API_KEYWORDS)
    spa_score = _count_occurrences(spec_text, _SPA_KEYWORDS)
    return "api" if api_score > spa_score else "spa"


def _build_model(settings: Settings) -> Model:
    if settings.provider == "claude":
        return AnthropicModel(
            settings.model,
            provider=AnthropicProvider(api_key=settings.api_key, base_url=settings.base_url),
        )
    return OpenAIChatModel(
        settings.model,
        provider=OpenAIProvider(api_key=settings.api_key, base_url=settings.base_url),
    )


def _build_agent(settings: Settings) -> Agent:
    """Builds a pydantic-ai Agent whose output_type=Target forces the model's
    answer into exactly "spa" or "api" (via structured output / tool-call
    validation), instead of relying on parsing a free-text reply."""
    return Agent(
        _build_model(settings),
        # PromptedOutput (JSON-in-text) instead of tool-call-based structured
        # output: reasoning models like MiniMax-M3 emit a <think> block before
        # answering and don't reliably signal a clean tool call, which made
        # the default ToolOutput mode exhaust its retries and always fall
        # back to keywords.
        output_type=PromptedOutput(Target),  # pyright: ignore[reportCallIssue, reportArgumentType]
        system_prompt=CLASSIFY_SYSTEM,
        retries=3,
    )


def classify_with_llm(spec_text: str, settings: Settings) -> Target:
    """Runs the pydantic-ai classification agent. Raises on any failure
    (network error, exhausted output-validation retries, etc.) -- callers
    must catch and fall back to classify_by_keywords."""
    result = _build_agent(settings).run_sync(spec_text)
    return cast(Target, result.output)


def classify(spec_text: str, settings: Settings) -> Target:
    """Classifies via classify_with_llm (pydantic-ai, output forced to
    Target). On any Exception, logs a warning and falls back to
    classify_by_keywords."""
    try:
        return classify_with_llm(spec_text, settings)
    except Exception as e:
        log.warning(
            "LLM classification failed, falling back to keywords: %s", e
        )
        return classify_by_keywords(spec_text)