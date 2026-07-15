"""Contract tests for main.py from issue-10.

Verifies the ASGI dispatcher's URL routing, SPA/API branching, cache behavior,
and stale serving. Calls it directly via httpx.AsyncClient(transport=ASGITransport).
compile_spec is mocked via monkeypatch (no real LLM calls allowed).
"""
import time
from pathlib import Path

import httpx
import pytest

from aimd import artifacts, compiler
from aimd.config import Settings
from aimd.main import AIMDDispatcher, create_app


@pytest.fixture
def test_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    src_dir = tmp_path / "src"
    dist_dir = tmp_path / "dist"
    src_dir.mkdir()
    dist_dir.mkdir()
    return Settings(
        api_key="dummy_key",
        base_url="https://api.minimax.io/v1",
        model="MiniMax-M3",
        max_tokens=200000,
        src_dir=src_dir,
        dist_dir=dist_dir,
    )


@pytest.fixture
def dispatcher(test_settings: Settings) -> AIMDDispatcher:
    return AIMDDispatcher(settings=test_settings)


def _client(dispatcher: AIMDDispatcher) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=dispatcher),
        base_url="http://t",
    )


# Case 1: GET / -> 404. Root is a plain static page served directly by nginx
# (ADR-0001 revision); it's outside the .ai.md pipeline, so the engine doesn't
# handle it specially -- it just falls through the _AIMD_RE non-match branch.
@pytest.mark.asyncio
async def test_root_not_handled_by_engine(dispatcher: AIMDDispatcher) -> None:
    async with _client(dispatcher) as c:
        r = await c.get("/", follow_redirects=False)
    assert r.status_code == 404


# Case 2: GET /nonexistent.ai.md -> 404
@pytest.mark.asyncio
async def test_missing_spec_returns_404(
    dispatcher: AIMDDispatcher, test_settings: Settings
) -> None:
    # Not found if the spec file doesn't exist
    async with _client(dispatcher) as c:
        r = await c.get("/nonexistent.ai.md")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "not_found"


# Case 3: html exists in dist + fresh -> 200, content matches, compile_spec called 0 times
@pytest.mark.asyncio
async def test_fresh_html_served_without_compile(
    dispatcher: AIMDDispatcher,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "x.ai.md"
    (test_settings.src_dir / name).write_text("spec", encoding="utf-8")
    html_file = artifacts.html_path(name, test_settings)
    html_file.write_text("<html><body>cached</body></html>", encoding="utf-8")

    calls = {"n": 0}

    def spy_compile(name, settings):
        calls["n"] += 1
        return None

    monkeypatch.setattr(compiler, "compile_spec", spy_compile)

    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert "cached" in r.text
    assert calls["n"] == 0


# Case 4: dist is empty -> compile_spec called once (mock creates html) -> 200
@pytest.mark.asyncio
async def test_empty_dist_triggers_compile(
    dispatcher: AIMDDispatcher,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "y.ai.md"
    (test_settings.src_dir / name).write_text("spec", encoding="utf-8")

    calls = {"n": 0}

    def mock_compile(name_, settings):
        calls["n"] += 1
        # Create SPA artifact html
        out = artifacts.html_path(name_, settings)
        out.write_text("<html><body>fresh</body></html>", encoding="utf-8")
        return out

    monkeypatch.setattr(compiler, "compile_spec", mock_compile)

    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert "fresh" in r.text
    assert calls["n"] == 1


# Case 5: compile_spec raises + no cache -> 502 JSON
@pytest.mark.asyncio
async def test_compile_failure_without_cache_returns_502(
    dispatcher: AIMDDispatcher,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "z.ai.md"
    (test_settings.src_dir / name).write_text("spec", encoding="utf-8")

    def fail_compile(name_, settings):
        raise RuntimeError("boom")

    monkeypatch.setattr(compiler, "compile_spec", fail_compile)

    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 502
    body = r.json()
    assert body["status"] == "generating"
    assert "boom" in body["message"]


# Case 6: compile_spec raises + cache exists (stale) -> 200 (serves stale)
@pytest.mark.asyncio
async def test_compile_failure_serves_stale(
    dispatcher: AIMDDispatcher,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "w.ai.md"
    (test_settings.src_dir / name).write_text("spec v1", encoding="utf-8")
    # Write the spec again to make it stale (spec mtime greater than artifact's)
    time.sleep(0.05)
    (test_settings.src_dir / name).write_text("spec v2", encoding="utf-8")
    html_file = artifacts.html_path(name, test_settings)
    html_file.write_text("<html><body>stale</body></html>", encoding="utf-8")

    def fail_compile(name_, settings):
        raise RuntimeError("boom")

    monkeypatch.setattr(compiler, "compile_spec", fail_compile)

    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert "stale" in r.text


# Case 7: py artifact + GET /x.ai.md -> 302 /x.ai.md/docs
@pytest.mark.asyncio
async def test_py_artifact_root_redirects_to_docs(
    dispatcher: AIMDDispatcher, test_settings: Settings
) -> None:
    name = "api.ai.md"
    (test_settings.src_dir / name).write_text("api spec", encoding="utf-8")
    py_file = artifacts.py_path(name, test_settings)
    py_file.write_text("app = object()\n", encoding="utf-8")

    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 302
    assert r.headers["location"] == f"/{name}/docs"


# Case 8: same py + POST /x.ai.md/convert -> the sub-app's received scope has
#          root_path == "/x.ai.md", path == "/convert"
@pytest.mark.asyncio
async def test_py_subapp_receives_correct_scope(
    dispatcher: AIMDDispatcher, test_settings: Settings
) -> None:
    name = "api.ai.md"
    (test_settings.src_dir / name).write_text("api spec", encoding="utf-8")

    py_file = artifacts.py_path(name, test_settings)

    # The subapp embeds the received scope into the response body — the test parses
    # the body to verify root_path/scope/method (load_module creates a new module
    # each time, so a captured dict can't be exposed to the outside).
    py_file.write_text(
        "import json\n"
        "async def app(scope, receive, send):\n"
        "    raw = scope.get('raw_path')\n"
        "    raw_str = raw.decode('latin-1') if isinstance(raw, (bytes, bytearray)) else raw\n"
        "    body = json.dumps({\n"
        "        'root_path': scope.get('root_path'),\n"
        "        'path': scope.get('path'),\n"
        "        'method': scope.get('method'),\n"
        "        'raw_path': raw_str,\n"
        "    }).encode('utf-8')\n"
        "    await send({'type': 'http.response.start', 'status': 200,\n"
        "                'headers': [(b'content-type', b'application/json')]})\n"
        "    await send({'type': 'http.response.body', 'body': body})\n",
        encoding="utf-8",
    )

    async with _client(dispatcher) as c:
        r = await c.post(f"/{name}/convert")
    assert r.status_code == 200
    body = r.json()
    assert body["root_path"] == f"/{name}"
    assert body["path"] == "/convert"
    assert body["method"] == "POST"
    # issue-49 regression lock: even if the ASGI strict subapp routes by raw_path,
    # matching must succeed (= same bytes as path).
    assert body["raw_path"] == "/convert"



# issue-53: .ai.md routing must work for specs nested under a directory
# prefix, not just root-level names. GET /app/tetris.ai.md should map to
# src/app/tetris.ai.md and dist/app/tetris.ai.md.html -- same mechanics as a
# flat name, just with a slash in it.
@pytest.mark.asyncio
async def test_nested_dir_spa_served(
    dispatcher: AIMDDispatcher, test_settings: Settings
) -> None:
    name = "app/tetris.ai.md"
    spec_file = test_settings.src_dir / name
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("spec", encoding="utf-8")

    html_file = artifacts.html_path(name, test_settings)
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text("<html><body>nested</body></html>", encoding="utf-8")

    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert "nested" in r.text


# issue-53: nested-directory py sub-app must receive the same root_path/
# raw_path scope adjustment as a root-level one, just with the directory
# prefix included.
@pytest.mark.asyncio
async def test_nested_dir_py_subapp_receives_correct_scope(
    dispatcher: AIMDDispatcher, test_settings: Settings
) -> None:
    name = "api/v1/convert.ai.md"
    spec_file = test_settings.src_dir / name
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("api spec", encoding="utf-8")

    py_file = artifacts.py_path(name, test_settings)
    py_file.parent.mkdir(parents=True, exist_ok=True)
    py_file.write_text(
        "import json\n"
        "async def app(scope, receive, send):\n"
        "    body = json.dumps({\n"
        "        'root_path': scope.get('root_path'),\n"
        "        'path': scope.get('path'),\n"
        "    }).encode('utf-8')\n"
        "    await send({'type': 'http.response.start', 'status': 200,\n"
        "                'headers': [(b'content-type', b'application/json')]})\n"
        "    await send({'type': 'http.response.body', 'body': body})\n",
        encoding="utf-8",
    )

    async with _client(dispatcher) as c:
        r = await c.post(f"/{name}/convert")
    assert r.status_code == 200
    body = r.json()
    assert body["root_path"] == f"/{name}"
    assert body["path"] == "/convert"


# Case 9: non-http types like lifespan are ignored
@pytest.mark.asyncio
async def test_non_http_scope_ignored(dispatcher: AIMDDispatcher) -> None:
    sent: list = []

    async def send(msg):
        sent.append(msg)

    scope = {"type": "lifespan"}
    await dispatcher(scope, lambda: None, send)
    assert sent == []


# Case 10: create_app() factory returns an AIMDDispatcher instance
def test_create_app_returns_dispatcher_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Inject a dummy key via env var so load_settings doesn't raise RuntimeError
    monkeypatch.setenv("LLM_API_KEY", "dummy_key")
    app = create_app()
    assert isinstance(app, AIMDDispatcher)


# issue-51 (must-fix — gemini+sonnet CONFIRMED) regression lock:
# When compilation keeps failing, compile_spec must not be called again within
# the backoff window. On a successful compile, the backoff state must reset.
@pytest.mark.asyncio
async def test_compile_failure_within_backoff_skips_recompile(
    dispatcher: AIMDDispatcher,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a long backoff to block re-requests within the window.
    test_settings_compiled = Settings(
        api_key=test_settings.api_key,
        base_url=test_settings.base_url,
        model=test_settings.model,
        max_tokens=test_settings.max_tokens,
        src_dir=test_settings.src_dir,
        dist_dir=test_settings.dist_dir,
        compile_backoff_init_s=60,
        compile_backoff_max_s=60,
    )
    dispatcher.settings = test_settings_compiled

    name = "stale.ai.md"
    # Existing stale artifact
    html_file = artifacts.html_path(name, test_settings)
    html_file.write_text("<html><body>stale</body></html>", encoding="utf-8")
    time.sleep(0.05)
    # Write a newer spec to induce the stale state
    (test_settings.src_dir / name).write_text("spec v2", encoding="utf-8")


    calls = {"n": 0}

    def fail_compile(name_, settings):
        calls["n"] += 1
        raise RuntimeError("LLM down")

    monkeypatch.setattr(compiler, "compile_spec", fail_compile)

    # All 5 requests return 200 + serve stale + compile_spec called only once
    async with _client(dispatcher) as c:
        for _ in range(5):
            r = await c.get(f"/{name}")
            assert r.status_code == 200
            assert "stale" in r.text
    assert calls["n"] == 1, (
        f"backoff within window — compile_spec should be called at most once, "
        f"got {calls['n']}"
    )


@pytest.mark.asyncio
async def test_compile_success_clears_backoff_state(
    dispatcher: AIMDDispatcher,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep backoff short (test remains deterministic; short init reduces mtime precision impact)
    test_settings_compiled = Settings(
        api_key=test_settings.api_key,
        base_url=test_settings.base_url,
        model=test_settings.model,
        max_tokens=test_settings.max_tokens,
        src_dir=test_settings.src_dir,
        dist_dir=test_settings.dist_dir,
        compile_backoff_init_s=1,
        compile_backoff_max_s=2,
    )
    dispatcher.settings = test_settings_compiled

    name = "recover.ai.md"
    # Existing stale artifact
    html_file = artifacts.html_path(name, test_settings)
    html_file.write_text("<html><body>v1</body></html>", encoding="utf-8")
    time.sleep(0.05)
    # Write a newer spec to induce the stale state
    (test_settings.src_dir / name).write_text("spec", encoding="utf-8")


    call_log: list[bool] = []  # True = success, False = failure

    def flaky_compile(name_, settings):
        if len(call_log) == 0:
            call_log.append(False)
            raise RuntimeError("LLM down")
        call_log.append(True)
        # On success, update html (served fresh on next request)
        out = artifacts.html_path(name_, settings)
        out.write_text("<html><body>fresh</body></html>", encoding="utf-8")

    monkeypatch.setattr(compiler, "compile_spec", flaky_compile)

    # First request: compile fails, serves stale
    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert "v1" in r.text
    assert len(call_log) == 1
    assert call_log[0] is False

    # Within the backoff window: retries with the same spec_mtime are blocked
    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert len(call_log) == 1  # No change — confirms backoff behavior

    # After init_s expires via time.sleep -> one retry -> succeeds
    time.sleep(test_settings_compiled.compile_backoff_init_s + 0.5)
    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert "fresh" in r.text
    assert len(call_log) == 2
    assert call_log[1] is True

    # Confirm backoff reset — the next request serves fresh as-is, without retrying
    async with _client(dispatcher) as c:
        r = await c.get(f"/{name}")
    assert r.status_code == 200
    assert "fresh" in r.text
    assert len(call_log) == 2