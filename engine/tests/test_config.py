import pytest
from pathlib import Path
from aimd.config import load_settings, Settings


def test_load_settings_default(monkeypatch):
    # Verify default values when only LLM_API_KEY is set
    monkeypatch.setenv("LLM_API_KEY", "test-api-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("AIMD_SRC_DIR", raising=False)
    monkeypatch.delenv("AIMD_DIST_DIR", raising=False)

    settings = load_settings()
    assert settings.api_key == "test-api-key"
    assert settings.base_url == "https://api.minimax.io/v1"
    assert settings.model == "MiniMax-M3"
    assert settings.max_tokens == 100000
    assert settings.src_dir == Path("./src")
    assert settings.dist_dir == Path("./dist")


def test_load_settings_missing_api_key(monkeypatch):
    # Verify RuntimeError is raised when LLM_API_KEY is missing
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        load_settings()
    assert "LLM_API_KEY environment variable is required" in str(excinfo.value)


def test_load_settings_override(monkeypatch):
    # Verify all variables are correctly reflected when overridden
    monkeypatch.setenv("LLM_API_KEY", "override-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://custom.api/v1")
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    monkeypatch.setenv("LLM_MAX_TOKENS", "50000")
    monkeypatch.setenv("AIMD_SRC_DIR", "/tmp/custom_src")
    monkeypatch.setenv("AIMD_DIST_DIR", "/tmp/custom_dist")

    settings = load_settings()
    assert settings.api_key == "override-key"
    assert settings.base_url == "https://custom.api/v1"
    assert settings.model == "custom-model"
    assert settings.max_tokens == 50000
    assert settings.src_dir == Path("/tmp/custom_src")
    assert settings.dist_dir == Path("/tmp/custom_dist")
