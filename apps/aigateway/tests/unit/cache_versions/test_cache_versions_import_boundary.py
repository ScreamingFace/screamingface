"""Support: the C11 import boundary of `core/cache_versions` (OME-1307, GW-capture).

# FEATURE: OME-1307 (E14) - the chat route reaches capture only through the `CaptureSink` port.
# INVARIANT (C11 row 4): no provider plugin imports `aigateway.core.cache_versions`. Outside the
# package and `main.py` (the composition root), a module imports the package itself or its `ports`
# module, and never `.models`, `.capture_store`, `.maintenance` or a later adapter module. The
# package imports nothing from `aigateway.plugins` and `aigateway.routes`, so the core never
# depends on a plugin.
# AIDEV-NOTE: this checks the SOURCE with an AST walk. A lazy import inside a function is still a
# dependency, and the walk sees it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import aigateway

_SRC = Path(inspect.getfile(aigateway)).resolve().parent
_PACKAGE = "aigateway.core.cache_versions"
_ALLOWED_OUTSIDE = frozenset({_PACKAGE, f"{_PACKAGE}.ports"})
_COMPOSITION_ROOT = "main.py"


def _module_exists(root: Path, dotted: str) -> bool:
    relative = Path(*dotted.split(".")[1:])
    return (root / relative).with_suffix(".py").is_file() or (root / relative).is_dir()


def _targets(root: Path, path: Path, node: ast.Import | ast.ImportFrom) -> list[str]:
    """The absolute dotted modules that one import statement names."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        package = ["aigateway", *path.relative_to(root).parent.parts]
        base_parts = package[: len(package) - (node.level - 1)]
        base = ".".join([*base_parts, *([node.module] if node.module else [])])
    else:
        base = node.module or ""
    found = [base]
    # `from aigateway.core import cache_versions` names the submodule, not a symbol.
    found.extend(
        f"{base}.{alias.name}"
        for alias in node.names
        if _module_exists(root, f"{base}.{alias.name}")
    )
    return found


def _violations(root: Path) -> list[str]:
    """Every boundary violation under ``root`` (a package directory named like ``aigateway``)."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            for target in _targets(root, path, node):
                if _breaks_a_rule(relative, target):
                    found.append(f"{relative}: imports {target}")
    return found


def _breaks_a_rule(relative: str, target: str) -> bool:
    names_package = target == _PACKAGE or target.startswith(f"{_PACKAGE}.")
    if relative.startswith("plugins/") and names_package:
        return True
    inside = relative.startswith("core/cache_versions/")
    if names_package and not inside and relative != _COMPOSITION_ROOT:
        return target not in _ALLOWED_OUTSIDE
    banned_from_inside = ("aigateway.plugins", "aigateway.routes")
    return inside and any(target == b or target.startswith(f"{b}.") for b in banned_from_inside)


def test_no_plugin_imports_cache_versions() -> None:
    found = [line for line in _violations(_SRC) if line.startswith("plugins/")]

    assert found == []


def test_only_the_composition_root_imports_cache_version_adapters() -> None:
    found = [line for line in _violations(_SRC) if not line.startswith("plugins/")]

    assert found == [], (
        "outside `core/cache_versions/` and `main.py`, import the package or its `ports` only: "
        f"{found}"
    )


def test_the_boundary_check_finds_a_planted_violation(tmp_path: Path) -> None:
    (tmp_path / "plugins" / "demo").mkdir(parents=True)
    (tmp_path / "core" / "cache_versions").mkdir(parents=True)
    (tmp_path / "plugins" / "demo" / "plugin.py").write_text(
        "from aigateway.core.cache_versions.ports import CaptureSink\n", encoding="utf-8"
    )
    (tmp_path / "core" / "cache_versions" / "ports.py").write_text("", encoding="utf-8")

    assert _violations(tmp_path) == [
        "plugins/demo/plugin.py: imports aigateway.core.cache_versions.ports"
    ]
