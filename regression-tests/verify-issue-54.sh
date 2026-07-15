#!/usr/bin/env bash
# verify-issue-54.sh — mechanical checks for issue-54 (dist artifact permissions / 403 fix).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail() { echo "FAIL: $1" >&2; exit 1; }

# 1. atomic_write must chmod the tmp file to 0o644 before the atomic replace
grep -q 'os.chmod(tmp_path, 0o644)' engine/aimd/artifacts.py \
    || fail "artifacts.atomic_write does not chmod tmp file to 0o644"

# 2. the chmod must happen before os.replace (order matters: os.replace preserves mode)
chmod_line=$(grep -n 'os.chmod(tmp_path, 0o644)' engine/aimd/artifacts.py | head -1 | cut -d: -f1)
replace_line=$(grep -n 'os.replace(tmp_path, path)' engine/aimd/artifacts.py | head -1 | cut -d: -f1)
[ -n "$chmod_line" ] && [ -n "$replace_line" ] || fail "could not locate both os.chmod and os.replace lines in atomic_write"
[ "$chmod_line" -lt "$replace_line" ] || fail "os.chmod must run before os.replace in atomic_write"

# 3. new permission test exists
grep -q "def test_atomic_write_sets_readable_permissions" engine/tests/test_artifacts.py \
    || fail "test_artifacts.py missing test_atomic_write_sets_readable_permissions"

# 4. existing dist artifacts are group/other readable (no leftover 0600 files)
while IFS= read -r -d '' f; do
    perm=$(stat -c "%a" "$f")
    case "$perm" in
        644|664|666|755|775|777) ;;
        *) fail "$f has non-readable permissions ($perm)" ;;
    esac
done < <(find dist -type f \( -name '*.html' -o -name '*.py' \) -print0)

# 5. targeted unit test actually passes
if [ -f engine/.venv/Scripts/python.exe ]; then
    PYTHON=engine/.venv/Scripts/python.exe
elif [ -f engine/.venv/bin/python ]; then
    PYTHON=engine/.venv/bin/python
else
    PYTHON=python3
fi
PYTHONPATH=engine "$PYTHON" -m pytest -q engine -k "atomic_write" \
    || fail "issue-54 targeted tests did not pass"

echo OK
