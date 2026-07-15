from pathlib import Path
from types import ModuleType

import pytest
from aimd.validators import (
    extract_code,
    validate_html,
    validate_python,
    load_module,
)


# ---------------------------------------------------------------------------
# extract_code
# ---------------------------------------------------------------------------


def test_extract_code_with_fence_returns_content():
    md = "intro\n```python\nprint('hello')\n```\noutro"
    assert extract_code(md) == "print('hello')"


def test_extract_code_with_language_tag():
    md = "```py\nx = 1\n```"
    assert extract_code(md) == "x = 1"


def test_extract_code_picks_longest_of_two_fences():
    short = "```\nshort\n```"
    long = "```\n" + ("line\n" * 10) + "```"
    md = short + "\n\n" + long
    assert extract_code(md) == ("line\n" * 10).rstrip("\n")


def test_extract_code_no_fence_returns_stripped_text():
    md = "   print('hi')   "
    assert extract_code(md) == "print('hi')"


def test_extract_code_strips_think_block_no_fence():
    # Reasoning models (e.g. MiniMax-M3) prepend <think>...</think> commentary
    # before the actual answer -- it must not be mistaken for code.
    raw = "<think>\nreasoning about the task\n</think>\n\n<!DOCTYPE html><html></html>"
    assert extract_code(raw) == "<!DOCTYPE html><html></html>"


def test_extract_code_strips_think_block_with_fence():
    raw = "<think>\nplanning...\n</think>\n\n```html\n<!DOCTYPE html><html></html>\n```"
    assert extract_code(raw) == "<!DOCTYPE html><html></html>"


def test_extract_code_handles_crlf_fence():
    md = "```python\r\nprint(1)\r\n```"
    assert extract_code(md) == "print(1)"


def test_extract_code_handles_space_after_fence():
    md = "``` python\nprint(1)\n```"
    assert extract_code(md) == "print(1)"


def test_extract_code_handles_space_after_fence_py():
    md = "``` py\nx=1\n```"
    assert extract_code(md) == "x=1"


def test_extract_code_strips_all_trailing_newlines():
    """Whether the trailing newline(s) at the end of code in a fence is 1 or N,
    they are all stripped (issue-23 spec). This is a lossy policy that also
    strips intentional blank lines — if a caller needs blank lines, they must
    be preserved through some other explicit mechanism.
    """
    # Single trailing newline
    md1 = "```\nx = 1\n```"
    assert extract_code(md1) == "x = 1"
    # Multiple trailing newlines (including an intentional blank line)
    md2 = "```\nx = 1\n\n```"  # one intentional blank line
    assert extract_code(md2) == "x = 1"
    md3 = "```\nx = 1\n\n\n```"  # two intentional blank lines
    assert extract_code(md3) == "x = 1"


def test_extract_code_picks_4backtick_over_3backtick():
    """Pattern where an LLM wraps a markdown code example inside a docstring with
    4-backtick fences — with the issue-24 fix, 4-backtick fences must be
    recognized in preference to 3-backtick ones."""
    md = (
        "```python\n"
        "def doc_with_markdown_example():\n"
        '    """This function includes a markdown example in its docstring.\n'
        "\n"
        "    ````markdown\n"
        "    # Title\n"
        "    ```\n"  # this is just an example — 3-backtick, but *inside* the 4-backtick fence
        "    body\n"
        "    ```\n"  # same for this line
        "    ````\n"
        '    """\n'
        "```\n"
    )
    # The 4-backtick block must be captured (the 3-backtick inside it is ignored)
    result = extract_code(md)
    # The result must be the markdown block *inside* the 4-backtick fence
    assert "```markdown" not in result  # the 3-backtick line inside the 4-backtick is trimmed, but the "```markdown" header must survive
    assert "Title" in result
    assert "body" in result


def test_extract_code_4backtick_is_the_only_fence():
    """Also works correctly when the input has only a 4-backtick block (no 3-backtick)."""
    md = (
        "````python\n"
        "x = 1\n"
        "````\n"
    )
    assert extract_code(md) == "x = 1"


def test_extract_code_unclosed_fence_strips_marker():
    """issue-25: when the LLM gets truncated at the token limit and only the
    opening fence remains, strip only the marker line and return the text
    after it as code — this fixes an issue where the exposed marker caused a
    bogus SyntaxError in validate_python's ast.parse."""
    md = "hi\n```python\nprint(1)"
    result = extract_code(md)
    assert result == "print(1)"
    assert "```" not in result


def test_extract_code_unclosed_fence_no_language_tag():
    md = "```\nx = 1\ny = 2"
    result = extract_code(md)
    assert result == "x = 1\ny = 2"
    assert "```" not in result


def test_extract_code_unclosed_4backtick_fence_strips_marker():
    md = "````python\nprint(1)"
    result = extract_code(md)
    assert result == "print(1)"
    assert "````" not in result


# ---------------------------------------------------------------------------
# validate_html
# ---------------------------------------------------------------------------


def test_validate_html_ok_returns_none():
    assert validate_html("<html><body>x</body></html>") is None


def test_validate_html_empty():
    assert validate_html("") == "empty output"


def test_validate_html_missing_tag():
    # "<html" not present (case-insensitive)
    assert validate_html("<div>x</div>") == "missing <html tag"
    assert validate_html("<HTML>".replace("HTML", "head")) == "missing <html tag"


def test_validate_html_contains_fence_marker():
    assert validate_html("<html>```\nfoo") == "markdown fence not stripped"


# ---------------------------------------------------------------------------
# validate_python
# ---------------------------------------------------------------------------


def test_validate_python_ok_returns_none():
    assert validate_python("x = 1\n") is None


def test_validate_python_syntax_error_message():
    err = validate_python("def :")
    assert err is not None
    assert err.startswith("SyntaxError: ")


# ---------------------------------------------------------------------------
# load_module
# ---------------------------------------------------------------------------


def write_module(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_load_module_returns_module_with_app(tmp_path: Path):
    mod_path = tmp_path / "m.py"
    write_module(mod_path, 'app = "dummy"\n')

    module = load_module(mod_path)

    assert isinstance(module, ModuleType)
    assert module.app == "dummy"


def test_load_module_missing_app_raises(tmp_path: Path):
    mod_path = tmp_path / "no_app.py"
    write_module(mod_path, "x = 1\n")

    with pytest.raises(AttributeError, match="no 'app' object"):
        load_module(mod_path)


def test_load_module_propagates_import_exception(tmp_path: Path):
    mod_path = tmp_path / "boom.py"
    write_module(mod_path, "raise RuntimeError('nope')\n")

    with pytest.raises(RuntimeError, match="nope"):
        load_module(mod_path)


def test_load_module_returns_distinct_objects_each_call(tmp_path: Path):
    mod_path = tmp_path / "m.py"
    write_module(mod_path, 'app = "dummy"\n')

    m1 = load_module(mod_path)
    m2 = load_module(mod_path)

    assert m1 is not m2
    assert m1.app == "dummy"
    assert m2.app == "dummy"


def test_load_module_does_not_register_in_sys_modules(tmp_path: Path):
    import sys

    mod_path = tmp_path / "m.py"
    write_module(mod_path, 'app = "x"\n')
    before = set(sys.modules)

    load_module(mod_path)

    after = set(sys.modules)
    # No new module should have been added
    assert after == before
