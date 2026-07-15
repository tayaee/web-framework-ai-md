import ast
import importlib
import importlib.machinery
import importlib.util
import itertools
import re
from pathlib import Path
from types import ModuleType

_FENCE_RE = re.compile(
    r"^[ \t]*``` ?[a-zA-Z0-9]*\r?\n(.*?)\r?\n^[ \t]*```",
    re.DOTALL | re.MULTILINE,
)
# Prefer 4-backtick fences (issue-24): the LLM sometimes wraps a markdown code
# example inside a docstring with 4-backtick fences — in that case, the 3-backtick
# lazy match could mistake the inner 3-backtick fence as the closing fence, so we
# extract 4-backtick fences first.
# Both patterns allow leading indentation on the fence line (^[ \t]* + MULTILINE).
_4FENCE_RE = re.compile(
    r"^[ \t]*````[a-zA-Z0-9]*\r?\n(.*?)\r?\n^[ \t]*````",
    re.DOTALL | re.MULTILINE,
)
# Detect an unclosed fence (issue-25): the LLM output got truncated at the token
# limit, leaving only an opening fence (``` or ````) with no closing fence. This is
# only tried as a fallback when the two patterns above fail to match; on a match,
# the marker line itself is stripped and only the text after it is treated as code.
_UNCLOSED_FENCE_RE = re.compile(
    r"^[ \t]*`{3,4}[ \t]*[a-zA-Z0-9]*[ \t]*\r?\n",
    re.MULTILINE,
)
# Reasoning models (e.g. MiniMax-M3) prepend a <think>...</think> block of
# chain-of-thought commentary before the actual answer. Strip it up front so
# it never gets mistaken for code -- otherwise a stray "<html" mentioned
# inside the reasoning text can make validate_html's substring check pass
# while the "code" is really just commentary followed by unrelated HTML.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_counter = itertools.count()


def extract_code(llm_output: str) -> str:
    """Extract the code body from LLM output.

    - Any <think>...</think> block (reasoning-model chain-of-thought, e.g.
      MiniMax-M3) is stripped first, before fence detection.
    - If a markdown code fence (```) is present: return the content of the longest fence block
    - Otherwise: return the whole thing stripped

    Trailing-newline policy (specified by the issue-23 fix):
    In the fence case, *all* trailing newlines of the matched block are removed (rstrip).
    This loses intentional blank lines too, but it stays consistent with the ``strip()``
    behavior of the no-fence path. Callers that need a trailing blank line must add it
    explicitly to the input.

    4-backtick fence priority (issue-24 fix):
    If a 4-backtick (````) fence is present, it is recognized first. This correctly
    handles the common pattern where the LLM wraps a markdown example inside a
    docstring with 4-backtick fences.
    Known limitation: when the docstring contains *only* a 3-backtick (```` sequence,
    not ```) internally, the lazy match can still catch the wrong closing fence —
    avoidable if the caller follows the convention of using 4-backtick fences.

    Unclosed-fence policy (issue-25 fix):
    When there's an opening fence (``` or ````) but no closing fence (LLM output
    truncated at the token limit) — strip only the marker line and return the rest
    of the text as code.
    Previously, the raw text was stripped and returned as-is, leaving the marker in
    the result; that marker then flowed straight into `validate_python`'s
    `ast.parse` and caused a "marker-induced" SyntaxError. Stripping just the marker
    means subsequent validation reflects only the actual completeness of the code.
    """
    llm_output = _THINK_BLOCK_RE.sub("", llm_output)
    # Prefer 4-backtick blocks (issue-24)
    matches_4 = _4FENCE_RE.findall(llm_output)
    if matches_4:
        return max(matches_4, key=len).rstrip("\n")
    # 3-backtick block fallback (original behavior)
    matches = _FENCE_RE.findall(llm_output)
    if matches:
        # The newline right before the closing fence is a block separator and is
        # removed — this also strips any trailing blank line the user left
        # (policy: consistent strip regardless of intent).
        return max(matches, key=len).rstrip("\n")
    # Unclosed fence (issue-25): strip only the marker line, treat the rest as code
    unclosed = _UNCLOSED_FENCE_RE.search(llm_output)
    if unclosed:
        return llm_output[unclosed.end():].rstrip("\n")
    return llm_output.strip()


def validate_html(code: str) -> str | None:
    """Loose validation for SPA artifacts. Returns None if OK, else an English error message."""
    if code == "":
        return "empty output"
    if "<html" not in code.lower():
        return "missing <html tag"
    if "```" in code:
        return "markdown fence not stripped"
    return None


def validate_python(code: str) -> str | None:
    """Stage-1 syntax validation. Returns None on ast.parse success, or an English
    message shaped like f"SyntaxError: {e}" on SyntaxError."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    return None


def load_module(path: Path) -> ModuleType:
    """Stage-2 validation and loader. Imports the py file at `path` as a fresh
    module object every time.

    - The module name is made unique as f"aimd_dyn_{next(_counter)}" (guarantees a
      fresh object on reload)
    - importlib.util.spec_from_file_location + module_from_spec + exec_module
    - Exceptions during import are propagated as-is (the caller catches them)
    - After success, if hasattr(module, "app") is False, raises
      AttributeError("module has no 'app' object")
    - Note: the counter still advances even when module loading fails (keep this
      in mind if the caller tracks the new module name).

    Hot-swap workaround: bypasses importlib's pyc timestamp-based cache
    validation. SourceFileLoader's get_code validates the pyc's int-second
    timestamp via _validate_timestamp_pyc; if the py file is written twice within
    the same second (e.g. write→write within <1s in a test), int(mtime) is
    identical, so a stale pyc passes through and returns the wrong module.app.
    To avoid this, the source is read directly via get_data and the module is
    built with compile + exec — this path never touches the pyc cache.
    Also calls importlib.invalidate_caches() right before exec_module to
    invalidate stale pyc on the FileFinder path too (belt and suspenders).
    """
    importlib.invalidate_caches()
    module_name = f"aimd_dyn_{next(_counter)}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        # spec_from_file_location almost never returns None, but handle it
        # defensively as a consistent AttributeError.
        raise AttributeError("module has no 'app' object")
    module = importlib.util.module_from_spec(spec)
    # Bypass the pyc timestamp cache: read the source directly and compile + exec
    # (avoiding the loader path). The source must be exposed identically in both
    # exec's globals and module.__dict__ for instrumentation like
    # `from __future__ import` to work.
    source = spec.loader.get_data(str(path))  # type: ignore[union-attr]
    code = compile(source, str(path), "exec")
    exec(code, module.__dict__)
    # Exceptions raised inside spec.loader.exec_module are propagated as-is.

    if not hasattr(module, "app"):
        raise AttributeError("module has no 'app' object")
    return module