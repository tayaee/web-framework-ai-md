"""issue-10: ASGI dispatcher -- URL contract (ADR-0001) + lazy compile trigger (ADR-0003).

Run with uvicorn "aimd.main:create_app" --factory. Only the create_app() factory
is exposed, so load_settings() is not called at module import time.
"""
import asyncio
import logging
import re
import time
from pathlib import Path

from . import artifacts, compiler
from .config import Settings, load_settings
from .registry import AppRegistry

log = logging.getLogger("aimd.main")

# Regex that matches the /<name>.ai.md[/<subpath>] shape, where <name> may
# itself contain directory segments (issue-53), e.g. /app/tetris.ai.md or
# /api/v1/convert.ai.md. The ^/ anchor restricts it to host-only root;
# subpath is optional as /(one or more slashes, then .*).
_AIMD_RE = re.compile(r"^/((?:[^/]+/)*[^/]+\.ai\.md)(/.*)?$")


def create_app() -> "AIMDDispatcher":
    """uvicorn factory entrypoint. Creates and returns an AIMDDispatcher instance.

    Placing `app = AIMDDispatcher()` at module level would call load_settings()
    at import time, which makes testing inconvenient -- it must always go through
    create_app().
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return AIMDDispatcher(watch=True)


class AIMDDispatcher:
    """The host ASGI app. Handles URL routing, SPA/API branching, stale serving,
    and compile backoff.

    Compile backoff (the state field) is the issue-51 fix:
    if `compile_spec` fails for the same (name, spec_mtime), retries within the
    backoff window are blocked and only the stale artifact is served -- this
    prevents a DoS where every request triggers an LLM call.
    """

    def __init__(self, settings: Settings | None = None, watch: bool = False) -> None:
        self.settings = settings or load_settings()
        self.registry = AppRegistry()
        # (name, spec_mtime) → LazyCompileState
        self._compile_state: dict[tuple[str, float], "LazyCompileState"] = {}
        self._state_guard = asyncio.Lock()  # only for serializing dict updates
        
        self.watcher = None
        if watch:
            from .watcher import start_watcher
            self.watcher = start_watcher(self.settings)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return  # ignore things like lifespan (run with uvicorn --lifespan off)

        path = scope["path"]
        m = _AIMD_RE.match(path)
        if not m:
            return await _plain(send, 404, "not found")

        name = m.group(1)
        subpath = m.group(2)

        if not artifacts.spec_path(name, self.settings).exists():
            return await _json(
                send, 404,
                {"status": "not_found", "message": f"App '{name}' was not found."},
            )

        # lazy compile -- issue-51 backoff applied
        state = None
        if artifacts.is_stale(name, self.settings):
            spec_path = artifacts.spec_path(name, self.settings)
            spec_mtime = spec_path.stat().st_mtime
            artifact_exists = artifacts.artifact_path(name, self.settings) is not None
            state = await self._maybe_compile(name, spec_mtime, artifact_exists)

        html = artifacts.html_path(name, self.settings)
        py = artifacts.py_path(name, self.settings)

        if html.exists():
            # SPA: ignore subpath and return html
            return await _file(send, html)

        if py.exists():
            if not subpath and scope["method"] == "GET":
                return await _redirect(send, f"/{name}/docs")
            # py artifact -> delegate to the registered ASGI app (offload to
            # to_thread since it's blocking)
            app = await asyncio.to_thread(self.registry.get, name, py)
            sub_scope = dict(scope)
            sub_scope["root_path"] = f"/{name}"
            sub_scope["path"] = subpath or "/"
            # Per the ASGI spec, scope["raw_path"] is the original URI as bytes.
            # Sub-apps that strictly follow the ASGI spec (e.g. Quart) prefer
            # raw_path for routing, so it must be updated alongside path
            # (issue-10 review must-fix -- gemini+sonnet). The subpath-only
            # path is always an ASCII-safe URL path, so latin-1 encoding is
            # guaranteed to succeed.
            if "raw_path" in sub_scope:
                sub_scope["raw_path"] = sub_scope["path"].encode("latin-1")
            return await app(sub_scope, receive, send)

        # No artifact yet -- either this is the first-ever compile attempt for
        # this spec (just failed synchronously above) or a retry is still
        # inside the issue-51 backoff window from an earlier failure. Either
        # way, tell the caller the app is (still) being generated rather than
        # implying it doesn't exist -- that's `not_found`, handled above.
        message = "The app is being generated. Please try again shortly."
        if state is not None and state.last_error is not None:
            message = f"An error occurred while generating the app. Please try again shortly. ({state.last_error})"
        return await _json(send, 502, {"status": "generating", "message": message})

    async def _maybe_compile(
        self, name: str, spec_mtime: float, artifact_exists: bool
    ) -> "LazyCompileState":
        """issue-51: Calls compile_spec within the backoff window per (name, spec_mtime).

        - No state, or backoff has expired -> try once. On success, remove the state.
        - On failure -> update the backoff window (init -> 2x init -> ... -> max);
          requests within the window get stale serving (if an artifact exists) / 502
          (if not).
        - Concurrent requests are serialized per name via the state's asyncio.Lock.

        Returns the LazyCompileState so the caller can report last_error to the client.
        """
        # Hold the dict update only briefly, then release -- the critical section
        # is the lock inside state.
        async with self._state_guard:
            state = self._compile_state.get((name, spec_mtime))
            if state is None:
                state = LazyCompileState(
                    now_ts=time.monotonic,
                    init_s=self.settings.compile_backoff_init_s,
                    max_s=self.settings.compile_backoff_max_s,
                )
                self._compile_state[(name, spec_mtime)] = state
        await state.run(name, self.settings, artifact_exists)
        return state


class LazyCompileState:
    """Per-(name, spec_mtime) compile attempt state (issue-51).

    Even if multiple requests for the same (name, spec_mtime) arrive concurrently,
    compile_spec is called only once, inside the asyncio.Lock. On failure, the next
    backoff window doubles, capped at max_s.
    """

    def __init__(self, now_ts, init_s: int, max_s: int) -> None:
        self._now = now_ts  # injectable -- for time determinism in tests
        self._lock = asyncio.Lock()
        self._backoff_s: float = 0.0  # 0 means backoff is inactive or just succeeded
        self._next_attempt_at: float = 0.0  # monotonic seconds
        self._init_s = max(0, init_s)
        self._max_s = max(self._init_s, max_s)
        self.last_error: str | None = None

    def _compute_next_window(self) -> float:
        """Computes the next backoff window on failure (exponential backoff, capped at max).

        First failure -> init_s, second -> 2x init_s, ..., capped at max_s.
        """
        if self._backoff_s == 0:
            return float(self._init_s)
        return min(self._backoff_s * 2, float(self._max_s))

    async def run(self, name: str, settings: Settings, artifact_exists: bool) -> None:
        """Serializes a single compile attempt. Returns immediately if within the window.

        The caller just needs to await; the result (success/failure/skip) is
        expressed via self._backoff_s and self._next_attempt_at.
        """
        if self._init_s == 0:
            # backoff disabled -- issue-51 disabled mode. Try on every request.
            await self._attempt(name, settings, artifact_exists)
            return

        now = self._now()
        if now < self._next_attempt_at:
            # Within the backoff window -- block the retry. The caller entered
            # via the is_stale=True branch but the compile is skipped -> the
            # stale-serving logic further down takes over.
            return

        async with self._lock:
            # Re-check after acquiring the lock -- skip if another coroutine
            # already attempted it.
            now = self._now()
            if now < self._next_attempt_at:
                return
            await self._attempt(name, settings, artifact_exists)

    async def _attempt(self, name: str, settings: Settings, artifact_exists: bool) -> None:
        try:
            await asyncio.to_thread(compiler.compile_spec, name, settings)
        except Exception as e:
            if not artifact_exists:
                # No cache -> the 502 response is decided by the caller in the
                # is_stale branch. But if we called the LLM on every request with
                # no cache either, cost would explode, so we set the same backoff
                # window regardless.
                log.error("compile failed (no cache) for %s: %s", name, e)
            else:
                log.error(
                    "recompile failed for %s, serving stale artifact: %s", name, e
                )
            window = self._compute_next_window()
            self._backoff_s = window
            self._next_attempt_at = self._now() + window
            self.last_error = str(e)
        else:
            # Success -- reset the backoff state.
            self._backoff_s = 0.0
            self._next_attempt_at = 0.0
            self.last_error = None


# -- Low-level ASGI response helpers --------------------------------------


async def _plain(send, status: int, text: str) -> None:
    body = text.encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
    })
    await send({"type": "http.response.body", "body": body})


async def _json(send, status: int, obj: dict) -> None:
    import json

    # ensure_ascii=False: emit non-ASCII characters (e.g. Korean) as raw UTF-8
    # rather than \uXXXX escapes, so the JSON body is human-readable as-is.
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json; charset=utf-8")],
    })
    await send({"type": "http.response.body", "body": body})


async def _redirect(send, location: str) -> None:
    await send({
        "type": "http.response.start",
        "status": 302,
        "headers": [(b"location", location.encode("utf-8"))],
    })
    await send({"type": "http.response.body", "body": b""})


async def _file(send, path: Path) -> None:
    body = path.read_bytes()
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/html; charset=utf-8")],
    })
    await send({"type": "http.response.body", "body": body})
