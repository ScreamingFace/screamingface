"""C11 layering rules for the scoreboard, enforced by AST walk (contracts.md C11, D7 X-18).

FEATURE: OME-1307 (E14) — the scoreboard may import `url4`, never `screamingface`; the registry
core is pure; only one adapter touches `url4`.

WHY tests and not `.claude/scripts/check_layering.py`: D7 X-18 puts the scoreboard rules here.
INVARIANT: the walk reads the syntax tree, never the text, so a docstring that names a banned
module (this one does) is not a violation.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src/scoreboard"
REGISTRY_CORE = SRC / "core" / "registry"
URL4_ADAPTER = SRC / "adapters" / "url4_fingerprinter.py"

# The top-level names, and the dotted prefixes, the pure registry core must never import.
CORE_BANNED = {
    "tortoise",
    "fastapi",
    "pydantic",
    "url4",
    "scoreboard.scores",
    "scoreboard.routes",
    "scoreboard.adapters",
}


def _forbidden_imports(source: str, banned: set[str]) -> list[str]:
    """The imported module names in `source` that equal or sit under a `banned` name."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        found.extend(
            name
            for name in names
            if any(name == entry or name.startswith(f"{entry}.") for entry in banned)
        )
    return found


def _violations(paths: list[Path], banned: set[str]) -> dict[str, list[str]]:
    hits = {
        str(path.relative_to(SRC)): _forbidden_imports(path.read_text(), banned) for path in paths
    }
    return {path: names for path, names in hits.items() if names}


def test_the_checker_reports_a_banned_import_in_a_literal_source() -> None:
    # WHY: a guard that cannot fail proves nothing. This pins that the helper bites, for every
    # import shape it must see.
    assert _forbidden_imports("import tortoise", CORE_BANNED) == ["tortoise"]
    assert _forbidden_imports("from tortoise import fields", CORE_BANNED) == ["tortoise"]
    assert _forbidden_imports("import scoreboard.scores.models", CORE_BANNED) == [
        "scoreboard.scores.models"
    ]
    assert _forbidden_imports("import os\nimport re", CORE_BANNED) == []
    # A relative import is inside the package, never a banned third-party module.
    assert _forbidden_imports("from .names import x", CORE_BANNED) == []


def test_c11_scoreboard_never_imports_the_sdk() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert files, "no scoreboard sources found; the guard is watching nothing"

    assert _violations(files, {"screamingface"}) == {}


def test_c11_registry_core_imports_only_the_standard_library() -> None:
    files = sorted(REGISTRY_CORE.rglob("*.py"))
    assert files, "no registry core sources found; the guard is watching nothing"

    assert _violations(files, CORE_BANNED) == {}


def test_c11_only_the_adapter_imports_url4() -> None:
    assert URL4_ADAPTER.is_file()
    others = [path for path in sorted(SRC.rglob("*.py")) if path != URL4_ADAPTER]

    assert _violations(others, {"url4"}) == {}
    # The one import site really imports it: the guard is not vacuously green.
    assert _forbidden_imports(URL4_ADAPTER.read_text(), {"url4"})
