from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[3] / "src" / "aigateway"
CORE = SRC / "core" / "usage_accounting"
CORE_ROOT = SRC / "core"
TAXONOMY = SRC / "plugins" / "taxonomy"


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    package = ["aigateway", *path.relative_to(SRC).parent.parts]
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                modules.add(".".join([*base, node.module]))
            else:
                modules.add(node.module)
    return modules


def test_core_contains_only_public_signal_and_hook_modules() -> None:
    assert {path.name for path in CORE.iterdir() if path.is_file()} == {
        "__init__.py",
        "hooks.py",
        "signals.py",
    }


def test_taxonomy_plugin_owns_policy_and_schema() -> None:
    assert {path.name for path in TAXONOMY.iterdir() if path.is_file()} == {
        "__init__.py",
        "classify.py",
        "collector.py",
        "entry_metadata.py",
        "mapper.py",
        "money.py",
        "plugin.py",
        "render.py",
        "session.py",
        "settings.py",
        "types.py",
        "usage_accounting.schema.json",
    }


def test_core_does_not_import_taxonomy_plugin() -> None:
    for path in CORE_ROOT.rglob("*.py"):
        assert not any(
            module.startswith("aigateway.plugins.taxonomy") for module in _imports(path)
        ), path


def test_taxonomy_production_modules_have_public_filenames() -> None:
    assert not [path.name for path in TAXONOMY.glob("_*.py") if path.name != "__init__.py"]
