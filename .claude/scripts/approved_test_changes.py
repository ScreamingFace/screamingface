"""Fail-closed, byte-exact approvals for owner-directed test contract changes.

The append-only checker has Python ranges but no TS/TSX or JSON parser. Rather than
exempt an entire branch or test directory, an owner-approved contract change pins the
before and after Git blob identities of each affected file. Any other edit fails again.

Two entry points, one matcher (OME-1468):
- `approved_unsupported_change` — files the range parser cannot read: TS/TSX tests, and
  JSON fixtures under a `tests/` directory.
- `approved_python_test_change` — `.py` files under a `tests/` directory whose edit the
  Python AST range check has already rejected.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Any


def _git(root: pathlib.Path, *args: str) -> str | None:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _approved_file(
    approval: dict[str, Any],
    *,
    branch: str,
    issue: str,
    repo_path: str,
    old_blob: str,
    new_blob: str,
) -> bool:
    if approval.get("issue") != issue or approval.get("branch") != branch:
        return False
    if not isinstance(approval.get("reason"), str) or not approval["reason"].strip():
        return False
    files = approval.get("files")
    if not isinstance(files, dict):
        return False
    entry = files.get(repo_path)
    return (
        isinstance(entry, dict)
        and set(entry) == {"base_blob", "approved_blob"}
        and entry["base_blob"] == old_blob
        and entry["approved_blob"] == new_blob
    )


def _under_tests(path: str) -> bool:
    # WHY: scoped to a `tests` directory component, never a whole stack: approvals
    # cover Python tests and JSON fixtures under tests/**, nothing wider (OME-1468).
    return "tests" in pathlib.PurePosixPath(path).parts[:-1]


def approved_unsupported_change(root: pathlib.Path, base: str, path: str) -> str | None:
    """Return an issue ID only for the *exact* owner-approved TS/TSX test edit or JSON
    fixture edit under `tests/`.

    Unlisted files, other branches, changed baseline and subsequent edits fail
    closed. This never exempts Python tests, deletes, renames or type changes.
    """
    suffix = pathlib.PurePosixPath(path).suffix
    if suffix not in {".ts", ".tsx"} and not (suffix == ".json" and _under_tests(path)):
        return None
    return _approved_blob_transition(root, base, path)


def approved_python_test_change(root: pathlib.Path, base: str, path: str) -> str | None:
    """Return an issue ID only for the *exact* owner-approved `.py` edit under `tests/`.

    Same fail-closed, byte-exact rules as `approved_unsupported_change`; called only
    after the AST range check has found a violation in a modified file.
    """
    if pathlib.PurePosixPath(path).suffix != ".py" or not _under_tests(path):
        return None
    return _approved_blob_transition(root, base, path)


def _approved_blob_transition(root: pathlib.Path, base: str, path: str) -> str | None:
    # INVARIANT: every failure to establish branch, both blobs, or a matching manifest
    # returns None — the caller then reports the file as an offender (fail closed).
    repo_text = _git(root, "rev-parse", "--show-toplevel")
    if not repo_text:
        return None
    repo = pathlib.Path(repo_text).resolve()
    try:
        file = (root / path).resolve()
        repo_path = file.relative_to(repo).as_posix()
    except ValueError:
        return None
    branch = _git(repo, "branch", "--show-current")
    old_blob = _git(repo, "rev-parse", "--verify", f"{base}:{repo_path}")
    new_blob = _git(repo, "hash-object", str(file)) if file.is_file() else None
    if not branch or not old_blob or not new_blob:
        return None
    for manifest in sorted((repo / ".claude/test-change-approvals").glob("OME-*.json")):
        try:
            approval = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(approval, dict) and _approved_file(
            approval,
            branch=branch,
            issue=manifest.stem,
            repo_path=repo_path,
            old_blob=old_blob,
            new_blob=new_blob,
        ):
            return manifest.stem
    return None
