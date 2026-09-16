#!/usr/bin/env python3
"""Gate: every config catalog in the repo is well-formed.

WHY A GATE AND NOT JUST A TEST: `x-scope` is not a JSON Schema keyword, and 2020-12 §6.5
REQUIRES a validator to ignore keywords it does not recognise. So every schema validator
on earth calls a catalog with a scopeless leaf valid. Nothing but this walk will say
otherwise, and a catalog with a hole in it serves a permission model that cannot be
enforced — `resolve_item` does not find the leaf and `enforce` calls a legitimate value an
unknown item.

THE VACUOUS-GREEN TRAP: today no catalog is committed, so a naive gate discovers zero
files, prints nothing, and exits 0 — indistinguishable from a gate that works. That is the
same failure `verify_chart_wiring.py` was written to avoid ("helm lint reports 0 chart(s)
failed for a chart that cannot render at all"). So this gate PROVES ITSELF FIRST: it lints
a known-bad fixture and fails if the defect is not caught. A broken import or a linter
that silently returns nothing is then a red build, not a green one.

Usage:
    python .github/scripts/lint_catalogs.py [--root .] [--require-at-least N]

Exit codes: 0 clean, 1 a catalog has defects, 2 the gate itself is broken.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

GATE_BROKEN = 2
DEFECTS_FOUND = 1

# A catalog with exactly one defect, used to prove the linter is alive before trusting a
# clean result from it. Deliberately minimal: if this ever lints clean, the linter is not
# doing its job, whatever the real catalogs say.
SELF_CHECK: dict[str, Any] = {
    "$id": "url4-config",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "broken": {
            "type": "object",
            "additionalProperties": False,
            # No `x-scope`: the defect no JSON Schema validator will ever report.
            "properties": {
                "item": {"type": "string", "description": "A scopeless leaf."}
            },
        }
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--require-at-least",
        type=int,
        default=0,
        help="fail if fewer than N catalogs are found; raise this once catalogs are "
        "committed, so a deletion becomes a red build rather than a quiet no-op",
    )
    args = parser.parse_args(argv)

    linter = _working_linter()
    if linter is None:
        return GATE_BROKEN
    lint_catalog, format_defects = linter

    catalogs = discover(args.root)
    print(f"catalogs found: {len(catalogs)}")
    if len(catalogs) < args.require_at_least:
        print(
            f"GATE BROKEN: expected at least {args.require_at_least} catalog(s), found "
            f"{len(catalogs)} — did they move, or did discovery break?",
            file=sys.stderr,
        )
        return GATE_BROKEN

    failed = 0
    for path in catalogs:
        defects = lint_catalog(json.loads(path.read_text()))
        relative = path.relative_to(args.root)
        if defects:
            failed += 1
            print(f"{relative}: {len(defects)} defect(s)")
            print(format_defects(defects))
        else:
            print(f"{relative}: ok")

    if failed:
        print(f"\n{failed} catalog(s) failed", file=sys.stderr)
    else:
        print("\nall catalogs well-formed")
    return DEFECTS_FOUND if failed else 0


def _working_linter() -> tuple[Any, Any] | None:
    """The linter, PROVEN to work, or None with the reason already printed.

    Importing it is not enough. A linter that imports and then reports nothing would make
    every catalog pass, so it is run against a known-bad fixture first and the gate
    refuses to continue if that comes back clean.
    """
    try:
        from url4.discovery.catalog import format_defects, lint_catalog
    except ImportError as exc:
        print(f"GATE BROKEN: cannot import the catalog linter: {exc}", file=sys.stderr)
        return None

    if not lint_catalog(SELF_CHECK):
        print(
            "GATE BROKEN: the linter found no defect in the known-bad fixture, so a clean "
            "result from it means nothing",
            file=sys.stderr,
        )
        return None
    return lint_catalog, format_defects


def discover(root: Path) -> list[Path]:
    """Every committed config catalog, found by CONTENT rather than by filename.

    A catalog is anything whose `$id` is `url4-config`, wherever it lives — keying on a
    naming convention instead would silently skip one that did not follow it, and a
    skipped catalog is exactly the thing this gate exists to notice.
    """
    found: list[Path] = []
    for path in sorted(root.rglob("*.json")):
        if any(part in _SKIP for part in path.parts):
            continue
        try:
            doc = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, ValueError):
            continue  # not our file; the JSON's own owner reports it
        if isinstance(doc, dict) and doc.get("$id") == "url4-config":
            found.append(path)
    return found


_SKIP = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".codegraph",
    }
)


if __name__ == "__main__":
    raise SystemExit(main())
