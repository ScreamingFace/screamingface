"""DEC-7 / DC-D5: no doc describes the removed node tier as live (uniform executor PRD 05).

The node tier — a separate Deployment that served mount calls, the App's `NodeForwarder`, the
settings `node_base_url` / `node_forward_timeout_s`, the chart's `node:` block — is gone. A mount
call is now a route of the App (`rest/mounts.py`), run as a `shape=direct` run on the runner
pool's warm children. This test scans every doc for a leftover live description and requires each
match to be either marked in place ("removed"/"superseded") or under a heading that says so.

A whole file is exempt when it carries the `docs/plans/uniform-executor/` banner in its first
five lines — that is the historical-plan-doc case (`docs/plans/00-overview.md`,
`docs/plans/erd.md`, `docs/plans/contracts.md`, `docs/plans/test-plan.md`,
`docs/plans/04-review-fixes.md`, `docs/plans/prd/02-config-and-mount-guard.md`,
`docs/plans/prd/03-node-tier-and-sync-surface.md`), kept as history rather than rewritten line by
line. `docs/plans/uniform-executor/**` (the current, authoritative plan) is out of scope outright.
"""

from __future__ import annotations

import pathlib
import re

_ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[2]
_UNIFORM_EXECUTOR_DIR = _ENGINE_ROOT / "docs/plans/uniform-executor"
_SUPERSEDED_MARK = "Superseded by `docs/plans/uniform-executor/`"

_LIVE_NODE_TIER = re.compile(
    r"node tier|node-tier|screamingface-engine node\b|node\.enabled|NodeForwarder"
    r"|install_forwarder|node_base_url|node_forward_timeout",
    re.IGNORECASE,
)
_MARKED_INLINE = re.compile(r"removed|superseded", re.IGNORECASE)
_HEADING = re.compile(r"^(#+)\s+(.*)$")
_MARKED_HEADING = re.compile(r"superseded|removed", re.IGNORECASE)


def _scanned_paths() -> list[pathlib.Path]:
    paths = [_ENGINE_ROOT / "README.md"]
    paths += sorted((_ENGINE_ROOT / "docs").rglob("*.md"))
    paths += sorted((_ENGINE_ROOT / "deploy").rglob("*.md"))
    return [p for p in paths if p.is_file()]


def _is_superseded_whole_file(path: pathlib.Path) -> bool:
    if _UNIFORM_EXECUTOR_DIR in path.parents:
        return True
    first_lines = "\n".join(path.read_text(encoding="utf-8").splitlines()[:5])
    return _SUPERSEDED_MARK in first_lines


def _offenders_in(path: pathlib.Path) -> list[str]:
    offenders: list[str] = []
    under_superseded_heading = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        heading = _HEADING.match(line)
        if heading:
            under_superseded_heading = bool(_MARKED_HEADING.search(heading.group(2)))
        if not _LIVE_NODE_TIER.search(line):
            continue
        if _MARKED_INLINE.search(line) or under_superseded_heading:
            continue
        offenders.append(f"{path}:{lineno}: {line.strip()}")
    return offenders


def test_docs_have_no_live_node_tier_reference() -> None:
    offenders: list[str] = []
    for path in _scanned_paths():
        if _is_superseded_whole_file(path):
            continue
        offenders.extend(_offenders_in(path))
    assert offenders == [], "live node-tier reference(s) found:\n" + "\n".join(offenders)


def test_superseded_banners_are_present() -> None:
    banner_files = [
        _ENGINE_ROOT / "docs/plans/00-overview.md",
        _ENGINE_ROOT / "docs/plans/prd/03-node-tier-and-sync-surface.md",
    ]
    for path in banner_files:
        first_lines = "\n".join(path.read_text(encoding="utf-8").splitlines()[:5])
        assert _SUPERSEDED_MARK in first_lines, f"{path} is missing the superseded banner"
