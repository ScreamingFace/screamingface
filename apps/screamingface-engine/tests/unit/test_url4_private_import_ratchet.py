"""Ratchet: the engine's imports of url4 private names may only go down (url4 audit HY-4).

STORY: as a url4 maintainer I can change a private helper without breaking the engine with no
warning. Today the engine reaches into ``url4.cli._config``, ``url4.cli._serve`` and a few
other private modules. Each one is a place where a url4 release can break the engine. This
test lists them, and the count can only shrink: promote the name to a public url4 module
instead of raising a baseline.

A private import is ``from url4.<…> import <name>`` (or ``import url4.<…>``) where a module
segment after ``url4`` or the imported name starts with ``_``. The AST walk sees function-local
imports too. The sibling ``test_no_private_url4_dispatch_import.py`` forbids two modules
outright; this one counts the rest.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# Counts measured when this ratchet was added (2026-10-10). Lower an entry when a crossing
# goes away for good; never raise one to make CI pass.
BASELINE = {"src": 8, "tests": 7}


def _is_private(segment: str) -> bool:
    return segment.startswith("_") and not segment.startswith("__")


def _private_url4_imports(source: str, label: str) -> list[str]:
    """Every private url4 import in ``source``, as ``label: module[.name]``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=label)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] != "url4":
                continue
            private_module = any(_is_private(part) for part in parts[1:])
            found.extend(
                f"{label}: {node.module}.{alias.name}"
                for alias in node.names
                if private_module or _is_private(alias.name)
            )
        elif isinstance(node, ast.Import):
            found.extend(
                f"{label}: {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] == "url4"
                and any(_is_private(part) for part in alias.name.split(".")[1:])
            )
    return found


def _tree_imports(root: str) -> list[str]:
    found: list[str] = []
    for path in sorted((_ROOT / root).rglob("*.py")):
        label = path.relative_to(_ROOT).as_posix()
        found.extend(_private_url4_imports(path.read_text(encoding="utf-8"), label))
    return found


def test_the_walk_sees_every_kind_of_private_import() -> None:
    # Without this, a bug in the walk would make the ratchet pass vacuously forever.
    source = (
        "from url4.cli._config import ProviderSpec\n"
        "from url4.dag.nodes._shared import _error_payload\n"
        "from url4.core.grammar import _NAME, parse\n"
        "import url4.peer._owned\n"
        "from url4.peer import dispatch_direct\n"
        "from ._local import thing\n"
    )
    assert _private_url4_imports(source, "x.py") == [
        "x.py: url4.cli._config.ProviderSpec",
        "x.py: url4.dag.nodes._shared._error_payload",
        "x.py: url4.core.grammar._NAME",
        "x.py: url4.peer._owned",
    ]


def test_engine_private_url4_imports_do_not_grow() -> None:
    for root, baseline in BASELINE.items():
        found = _tree_imports(root)
        assert len(found) <= baseline, "\n".join(
            [f"{len(found)} private url4 imports in {root}/ > baseline {baseline}:", *found]
        )
