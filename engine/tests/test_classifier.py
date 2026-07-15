from pathlib import Path

from aimd import classifier
from aimd.config import Settings


# Source text of src/index.ai.md and src/convert.ai.md (issue-7 spec — copied into the test)
INDEX_SPEC = """\
# AIMD main landing page
This page is a landing page with an embedded Tetris game that proves out the AIMD project's concept.

## Design rules
- Theme: terminal dark mode (black background, green text).
- Rendering: render a 10x20 grid Tetris board at the center of the screen.

## Functional requirements
- Users must be able to move blocks using the keyboard arrow keys.
- The scoreboard must work in real time, going up by 100 points each time a line is cleared.
"""

CONVERT_SPEC = """\
# Temperature conversion microservice API

## Routing rules
- Expose a POST /convert endpoint.
- Input schema (JSON): {"temperature": 30, "type": "C"} (type is C or F)

## Business logic
- If type is "C", convert Celsius to Fahrenheit and return it.
- If type is "F", convert Fahrenheit to Celsius and return it.
- Output schema (JSON): {"result": converted_value}
"""


def make_settings() -> Settings:
    return Settings(
        api_key="k",
        base_url="http://t",
        model="MiniMax-M3",
        max_tokens=8192,
        src_dir=Path("./src"),
        dist_dir=Path("./dist"),
    )


def test_classify_by_keywords_spa_wins_on_index_spec():
    # A simple comparison that counts every occurrence of SPA keywords
    # (HTML, UI, screen, page, rendering, design, button, game) or
    # API keywords (POST, GET, PUT, DELETE, JSON, API, endpoint, endpoint).
    # index.ai.md has many SPA keywords -> "spa"
    assert classifier.classify_by_keywords(INDEX_SPEC) == "spa"


def test_classify_by_keywords_api_wins_on_convert_spec():
    # convert.ai.md has POST, JSON, API, endpoint -> "api"
    assert classifier.classify_by_keywords(CONVERT_SPEC) == "api"


def test_classify_returns_spa_when_llm_says_spa(monkeypatch):
    settings = make_settings()
    monkeypatch.setattr(classifier, "classify_with_llm", lambda text, s: "spa")
    assert classifier.classify("anything", settings) == "spa"


def test_classify_returns_api_when_llm_says_api(monkeypatch):
    settings = make_settings()
    monkeypatch.setattr(classifier, "classify_with_llm", lambda text, s: "api")
    assert classifier.classify("anything", settings) == "api"


def test_classify_falls_back_to_keywords_when_llm_raises(monkeypatch):
    settings = make_settings()

    def boom(text, s):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(classifier, "classify_with_llm", boom)
    assert classifier.classify(CONVERT_SPEC, settings) == "api"


def test_classify_logs_unified_format_on_exception(monkeypatch, caplog):
    """issue-42: the Exception path must also use the same single log format."""
    settings = make_settings()

    def boom(text, s):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(classifier, "classify_with_llm", boom)

    import logging

    with caplog.at_level(logging.WARNING, logger="aimd.classifier"):
        result = classifier.classify(CONVERT_SPEC, settings)

    assert result == "api"
    assert any(
        "LLM classification failed, falling back to keywords" in record.message
        for record in caplog.records
    ), f"unexpected log records: {[r.message for r in caplog.records]}"


def test_build_model_uses_openai_for_default_provider():
    settings = make_settings()
    model = classifier._build_model(settings)
    assert isinstance(model, classifier.OpenAIChatModel)


def test_build_model_uses_anthropic_for_claude_provider():
    settings = Settings(
        api_key="k",
        base_url="http://t",
        model="claude-x",
        max_tokens=8192,
        src_dir=Path("./src"),
        dist_dir=Path("./dist"),
        provider="claude",
    )
    model = classifier._build_model(settings)
    assert isinstance(model, classifier.AnthropicModel)
