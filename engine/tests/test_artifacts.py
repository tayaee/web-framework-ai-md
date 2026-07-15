import os
import time
from pathlib import Path
import pytest
from aimd.config import Settings
from aimd.artifacts import (
    spec_path,
    html_path,
    py_path,
    artifact_path,
    is_stale,
    atomic_write,
    list_specs,
)


@pytest.fixture
def test_settings(tmp_path):
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


def test_paths(test_settings):
    name = "index.ai.md"
    assert spec_path(name, test_settings) == test_settings.src_dir / "index.ai.md"
    assert html_path(name, test_settings) == test_settings.dist_dir / "index.ai.md.html"
    assert py_path(name, test_settings) == test_settings.dist_dir / "index.ai.md.py"


def test_artifact_path(test_settings):
    name = "index.ai.md"
    # 1. Neither exists
    assert artifact_path(name, test_settings) is None

    # 2. Only py exists
    p_path = py_path(name, test_settings)
    p_path.touch()
    assert artifact_path(name, test_settings) == p_path

    # 3. Both exist (html takes priority)
    h_path = html_path(name, test_settings)
    h_path.touch()
    assert artifact_path(name, test_settings) == h_path

    # 4. Only html exists
    p_path.unlink()
    assert artifact_path(name, test_settings) == h_path


def test_is_stale(test_settings):
    name = "index.ai.md"
    s_path = spec_path(name, test_settings)

    # 1. No spec -> False
    assert not is_stale(name, test_settings)

    # Create spec file
    s_path.touch()

    # 2. No artifact -> True
    assert is_stale(name, test_settings)

    # Create artifact (newer)
    h_path = html_path(name, test_settings)
    h_path.touch()

    # Set mtimes explicitly for a deterministic test
    now = time.time()
    os.utime(s_path, (now, now))
    os.utime(h_path, (now + 10, now + 10))
    # 3. Artifact is newer -> False
    assert not is_stale(name, test_settings)

    # 4. Set spec to a future mtime (spec mtime > artifact mtime) -> True
    os.utime(s_path, (now + 20, now + 20))
    assert is_stale(name, test_settings)


def test_atomic_write(test_settings):
    target = test_settings.dist_dir / "test_write.txt"
    text1 = "hello world"

    # 1. Verify content is written
    atomic_write(target, text1)
    assert target.read_text(encoding="utf-8") == text1

    # 2. Verify overwriting an existing file
    text2 = "new content"
    atomic_write(target, text2)
    assert target.read_text(encoding="utf-8") == text2

    # 3. Verify no leftover tmp files
    # Confirm dist_dir has no files other than target
    files = list(test_settings.dist_dir.iterdir())
    assert len(files) == 1
    assert files[0] == target


def test_atomic_write_sets_readable_permissions(test_settings):
    """issue-54: files written by atomic_write must be readable by other
    users/processes (mode 0o644), not the tempfile.mkstemp default of 0o600 --
    otherwise a separate container (e.g. nginx) serving dist/ directly gets a
    403 even though the file exists."""
    target = test_settings.dist_dir / "tetris.ai.md.html"
    atomic_write(target, "<html></html>")

    mode = target.stat().st_mode & 0o777
    assert mode == 0o644


def test_atomic_write_creates_missing_parent(test_settings):
    """atomic_write must create the parent directory when it doesn't exist on disk
    and write successfully (fix from issue-20)."""
    nested_dir = test_settings.dist_dir / "nested" / "deeper"
    assert not nested_dir.exists()
    target = nested_dir / "leaf.txt"

    atomic_write(target, "deep content")

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "deep content"
    # Confirm the parent directory was also created
    assert nested_dir.is_dir()


def test_list_specs(test_settings):
    # Empty directory
    assert list_specs(test_settings) == []

    # Add files
    (test_settings.src_dir / "b.ai.md").touch()
    (test_settings.src_dir / "a.ai.md").touch()
    (test_settings.src_dir / "other.txt").touch()

    # Create a subdirectory and add a file (issue-53: nested specs are found
    # too, returned as a POSIX-style relative path so it matches the `name`
    # format main.py builds from the URL, regardless of host OS)
    sub_dir = test_settings.src_dir / "sub"
    sub_dir.mkdir()
    (sub_dir / "c.ai.md").touch()

    # Sorted, includes the nested spec
    assert list_specs(test_settings) == ["a.ai.md", "b.ai.md", "sub/c.ai.md"]


def test_list_specs_src_is_regular_file(test_settings):
    """When src_dir is a regular file, iterdir() raises NotADirectoryError, and
    list_specs must return an empty list without crashing in that path."""
    file_path = test_settings.src_dir / "not_a_dir"
    file_path.touch()  # Create a regular file (not a directory)
    broken_settings = Settings(
        api_key="dummy_key",
        base_url="https://api.minimax.io/v1",
        model="MiniMax-M3",
        max_tokens=200000,
        src_dir=file_path,
        dist_dir=test_settings.dist_dir,
    )
    assert list_specs(broken_settings) == []


def test_list_specs_src_does_not_exist(test_settings):
    """Return an empty list when src_dir itself does not exist (preserve existing behavior)."""
    missing = test_settings.src_dir.parent / "missing_src"
    broken_settings = Settings(
        api_key="dummy_key",
        base_url="https://api.minimax.io/v1",
        model="MiniMax-M3",
        max_tokens=200000,
        src_dir=missing,
        dist_dir=test_settings.dist_dir,
    )
    assert list_specs(broken_settings) == []
