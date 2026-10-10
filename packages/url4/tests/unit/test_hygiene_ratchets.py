"""Hygiene ratchets from the url4 audit (report §7): counts that may only go down.

STORY: as a contributor I see at once when a change adds a coverage escape, a test-side type
suppression, a skipped import or a sleep in a test, and the count of each does not grow
silently. ``scripts/check_suppressions.py`` covers ``# type: ignore`` and ``# noqa`` in
``src``; this file covers the rest.

Lower an entry when its count drops for good. Never raise one to make CI pass: remove the
new escape instead, or say in review why it is the right call and lower something else.

The public export pin is different: it is exact, not a ceiling. Adding public API is
legitimate, but it must be a visible decision, so any change to a package's ``__all__``
size changes the number here in the same diff.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import url4

_SRC = Path(url4.__file__).parent
_TESTS = Path(__file__).resolve().parents[1]

# Counts measured when these ratchets were added (2026-10-10).
BASELINE = {
    "pragma-no-cover in src": 8,
    "type-ignore in tests": 25,
    "importorskip in tests": 0,
    "sleep in tests": 21,
    "assert in src": 20,
}

# Exact ``__all__`` size of every package that declares one (H2: the public surface).
EXPORTS = {
    "url4": 54,
    "url4.dag": 36,
    "url4.dag.nodes": 23,
    "url4.peer": 5,
    "url4.streaming.interfaces": 17,
    "url4.streaming.protocol": 34,
    "url4.streaming.testing": 3,
}

_PATTERNS = {
    "pragma-no-cover in src": (_SRC, re.compile(r"pragma: no cover")),
    "type-ignore in tests": (_TESTS, re.compile(r"#\s*type:\s*ignore")),
    "importorskip in tests": (_TESTS, re.compile(r"\bimportorskip\(")),
    "sleep in tests": (_TESTS, re.compile(r"\bsleep\(")),
}


def _sources(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _line_hits(root: Path, pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for path in _sources(root):
        if path == Path(__file__).resolve():
            continue  # this file names every pattern it counts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(root.parent).as_posix()}:{number}")
    return hits


def _asserts_in_src() -> list[str]:
    # streaming/testing is a test-helper package: its asserts are the point of it.
    hits: list[str] = []
    for path in _sources(_SRC):
        rel = path.relative_to(_SRC).as_posix()
        if rel.startswith("streaming/testing/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        hits.extend(
            f"{rel}:{node.lineno}" for node in ast.walk(tree) if isinstance(node, ast.Assert)
        )
    return hits


def _counts() -> dict[str, list[str]]:
    found = {name: _line_hits(root, pattern) for name, (root, pattern) in _PATTERNS.items()}
    found["assert in src"] = _asserts_in_src()
    return found


def test_every_baseline_has_a_counter() -> None:
    assert set(_counts()) == set(BASELINE)


def test_hygiene_counts_do_not_grow() -> None:
    over = [
        "\n".join([f"{name}: {len(hits)} > baseline {BASELINE[name]}", *hits])
        for name, hits in _counts().items()
        if len(hits) > BASELINE[name]
    ]
    assert over == [], "\n\n".join(over)


def test_the_public_export_counts_are_pinned() -> None:
    actual: dict[str, int] = {}
    for path in sorted(_SRC.rglob("__init__.py")):
        module = ".".join(("url4", *path.relative_to(_SRC).parts[:-1]))
        exported = getattr(importlib.import_module(module), "__all__", ())
        if exported:
            actual[module] = len(exported)
    assert actual == EXPORTS, "a package's __all__ changed: update EXPORTS in the same diff"
