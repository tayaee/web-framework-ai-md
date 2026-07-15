import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    max_tokens: int
    src_dir: Path
    dist_dir: Path
    # Compile failure backoff (issue-51). Units: seconds. Defaults init=30, max=600.
    # If 0 or below, backoff is disabled (same unlimited-retry mode as the issue-51 regression).
    compile_backoff_init_s: int = 30
    compile_backoff_max_s: int = 600
    # LLM provider. "openai" uses an OpenAI Chat Completions-compatible endpoint
    # (openai/deepseek/minimax/openrouter, etc.); "claude" uses the Anthropic Messages API.
    provider: str = "openai"


def load_settings() -> Settings:
    """Read settings from environment variables. Raises RuntimeError if LLM_API_KEY is missing."""
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("LLM_API_KEY environment variable is required")
    return Settings(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://api.minimax.io/v1"),
        model=os.environ.get("LLM_MODEL", "MiniMax-M3"),
        max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "100000")),
        src_dir=Path(os.environ.get("AIMD_SRC_DIR", "./src")),
        dist_dir=Path(os.environ.get("AIMD_DIST_DIR", "./dist")),
        compile_backoff_init_s=int(os.environ.get("AIMD_COMPILE_BACKOFF_INIT_S", "30")),
        compile_backoff_max_s=int(os.environ.get("AIMD_COMPILE_BACKOFF_MAX_S", "600")),
        provider=os.environ.get("LLM_API_PROTOCOL", "openai"),
    )
