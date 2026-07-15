import os
import tempfile
from pathlib import Path

from .config import Settings


def spec_path(name: str, settings: Settings) -> Path:
    """src/<name>. E.g.: index.ai.md -> src/index.ai.md"""
    return settings.src_dir / name


def html_path(name: str, settings: Settings) -> Path:
    """dist/<name>.html"""
    return settings.dist_dir / (name + ".html")


def py_path(name: str, settings: Settings) -> Path:
    """dist/<name>.py"""
    return settings.dist_dir / (name + ".py")


def artifact_path(name: str, settings: Settings) -> Path | None:
    """Returns the existing artifact path. Prefers html, falls back to py, or None if neither exists."""
    h_path = html_path(name, settings)
    if h_path.exists():
        return h_path
    p_path = py_path(name, settings)
    if p_path.exists():
        return p_path
    return None


def is_stale(name: str, settings: Settings) -> bool:
    """True if a compile is needed.
    - True if there's no artifact at all
    - True if spec_path's mtime > the artifact's mtime
    - False if the spec file itself doesn't exist (not stale since it can't be compiled)
    """
    s_path = spec_path(name, settings)
    if not s_path.exists():
        return False

    art_path = artifact_path(name, settings)
    if art_path is None:
        return True

    return s_path.stat().st_mtime > art_path.stat().st_mtime


def atomic_write(path: Path, text: str) -> None:
    """Creates a tmp file in the same directory via tempfile.mkstemp, writes
    text to it, then atomically swaps it in with os.replace(tmp, path). On
    failure, the tmp file is deleted.

    Automatically creates path's parent directory if it doesn't exist (the
    issue-20 fix). At the original issue-3 point, the spec didn't mention
    "whether to create the parent" so this was omitted, but in practice,
    calling this when the dist/ subdirectory structure doesn't exist yet
    crashed with FileNotFoundError.
    """
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise e


def list_specs(settings: Settings) -> list[str]:
    """Sorted list of *.ai.md paths in src_dir, recursing into subdirectories
    (issue-53). Each entry is src_dir-relative, POSIX-slash-joined (e.g.
    "app/tetris.ai.md") to match the `name` format main.py builds from the
    URL. [] if src_dir doesn't exist, isn't a directory, or isn't accessible."""
    src = settings.src_dir
    if not src.exists() or not src.is_dir():
        return []
    try:
        names = [
            p.relative_to(src).as_posix()
            for p in src.rglob("*.ai.md")
            if p.is_file()
        ]
    except OSError:
        return []
    return sorted(names)
