"""C11 layering rules for the scoreboard, enforced by AST walk (contracts.md C11, D7 X-18).

FEATURE: OME-1307 (E14) — the scoreboard may import `url4`, never `screamingface`; the registry
core is pure; only one adapter touches `url4`.

WHY tests and not `.claude/scripts/check_layering.py`: D7 X-18 puts the scoreboard rules here.
INVARIANT: the walk reads the syntax tree, never the text, so a docstring that names a banned
module (this one does) is not a violation.
"""

from __future__ import annotations

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src/scoreboard"
REGISTRY_CORE = SRC / "core" / "registry"
URL4_ADAPTER = SRC / "adapters" / "url4_fingerprinter.py"

# C11-SB-2 is an allowlist: the pure registry core may import the standard library and itself.
CORE_ALLOWED = ("scoreboard.core.registry",)

# The dotted package a source under `core/registry` sits in, for the literal self-tests.
CORE_PACKAGE = "scoreboard.core.registry"


def _package_of(path: Path) -> str:
    """The dotted package of a source file, so a relative import resolves against it."""
    return ".".join(path.relative_to(SRC.parent).parent.parts)


def _imports(source: str, package: str) -> list[tuple[str, list[str]]]:
    """Each import of `source` as (absolute module, the absolute names it binds).

    INVARIANT: a relative import is resolved against `package` first. `from ...scores.models
    import System` in `scoreboard.core.registry` is `scoreboard.scores.models`, and
    `from scoreboard import scores` binds `scoreboard.scores`, so neither slips past a check
    that reads the module name alone.
    """
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((alias.name, [alias.name]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_name("." * node.level + (node.module or ""), package)
            found.append((module, [f"{module}.{alias.name}" for alias in node.names]))
    return found


def _under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


def _forbidden_imports(source: str, banned: set[str], package: str) -> list[str]:
    """The imported names in `source` that equal or sit under a `banned` name (a denylist)."""
    found: list[str] = []
    for module, names in _imports(source, package):
        if any(_under(module, entry) for entry in banned):
            found.append(module)
        else:
            found.extend(n for n in names if any(_under(n, entry) for entry in banned))
    return found


def _outside_allowlist(source: str, allowed: tuple[str, ...], package: str) -> list[str]:
    """The imported names in `source` that are neither standard library nor under `allowed`."""
    return [
        name
        for _, names in _imports(source, package)
        for name in names
        if name.split(".")[0] not in sys.stdlib_module_names
        and not any(_under(name, entry) for entry in allowed)
    ]


def _violations(paths: list[Path], banned: set[str]) -> dict[str, list[str]]:
    hits = {
        str(path.relative_to(SRC)): _forbidden_imports(path.read_text(), banned, _package_of(path))
        for path in paths
    }
    return {path: names for path, names in hits.items() if names}


def _outside(paths: list[Path], allowed: tuple[str, ...]) -> dict[str, list[str]]:
    hits = {
        str(path.relative_to(SRC)): _outside_allowlist(path.read_text(), allowed, _package_of(path))
        for path in paths
    }
    return {path: names for path, names in hits.items() if names}


def test_the_checker_reports_a_banned_import_in_a_literal_source() -> None:
    # WHY: a guard that cannot fail proves nothing. This pins that the helper bites, for every
    # import shape it must see, relative ones included.
    banned = {"screamingface", "scoreboard.scores", "scoreboard.adapters", "tortoise"}

    def check(source: str, package: str = CORE_PACKAGE) -> list[str]:
        return _forbidden_imports(source, banned, package)

    assert check("import tortoise") == ["tortoise"]
    assert check("from tortoise import fields") == ["tortoise"]
    assert check("import scoreboard.scores.models") == ["scoreboard.scores.models"]
    assert check("import os\nimport re") == []
    # A relative import inside the package is clean.
    assert check("from .names import x") == []
    # A sibling-package relative import resolves to `scoreboard.scores.models`.
    assert check("from ...scores.models import System") == ["scoreboard.scores.models"]
    # `from pkg import name` binds `pkg.name`, and `...` from core/registry is `scoreboard`.
    assert check("from scoreboard import scores") == ["scoreboard.scores"]
    assert check("from ... import adapters") == ["scoreboard.adapters"]
    # The same text from another package resolves elsewhere: `..` here is `scoreboard`.
    assert check("from ..scores.models import System", "scoreboard.routes") == [
        "scoreboard.scores.models"
    ]


def test_the_allowlist_reports_everything_but_the_standard_library_and_the_core() -> None:
    def outside(source: str) -> list[str]:
        return _outside_allowlist(source, CORE_ALLOWED, CORE_PACKAGE)

    assert (
        outside("from __future__ import annotations\nimport hashlib\nfrom dataclasses import x")
        == []
    )
    assert outside("from .names import x\nfrom . import errors") == []
    assert outside("from scoreboard.core.registry.errors import E") == []
    assert outside("from ...scores.models import System") == ["scoreboard.scores.models.System"]
    assert outside("from ...config import Settings") == ["scoreboard.config.Settings"]
    assert outside("from .. import adapters") == ["scoreboard.core.adapters"]
    assert outside("from scoreboard import scores") == ["scoreboard.scores"]
    assert outside("import httpx") == ["httpx"]
    assert outside("from scoreboard.db import init_db") == ["scoreboard.db.init_db"]


def test_c11_scoreboard_never_imports_the_sdk() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert files, "no scoreboard sources found; the guard is watching nothing"

    assert _violations(files, {"screamingface"}) == {}


def test_c11_registry_core_imports_only_the_standard_library() -> None:
    files = sorted(REGISTRY_CORE.rglob("*.py"))
    assert files, "no registry core sources found; the guard is watching nothing"

    assert _outside(files, CORE_ALLOWED) == {}


def test_c11_only_the_adapter_imports_url4() -> None:
    assert URL4_ADAPTER.is_file()
    others = [path for path in sorted(SRC.rglob("*.py")) if path != URL4_ADAPTER]

    assert _violations(others, {"url4"}) == {}
    # The one import site really imports it: the guard is not vacuously green.
    assert _forbidden_imports(URL4_ADAPTER.read_text(), {"url4"}, _package_of(URL4_ADAPTER))
