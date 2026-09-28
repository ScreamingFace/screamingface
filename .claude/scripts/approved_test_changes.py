"""Fail-closed, byte-exact approvals for owner-directed TS test contract changes.

The append-only checker has Python ranges but no TS/TSX parser. Rather than exempt an
entire branch or test directory, an owner-approved contract change pins the before
and after Git blob identities of each affected file. A different edit fails again.
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


def approved_unsupported_change(root: pathlib.Path, base: str, path: str) -> str | None:
    """Return an issue ID only for the *exact* owner-approved TS/TSX test edit.

    Unlisted files, other branches, changed baseline and subsequent edits fail
    closed. This never exempts Python tests, deletes, renames or type changes.
    """
    if pathlib.PurePosixPath(path).suffix not in {".ts", ".tsx"}:
        return None
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
