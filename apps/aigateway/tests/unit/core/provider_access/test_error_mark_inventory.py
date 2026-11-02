"""G0 error-mark inventory — every direct `mark_error` call in the app is classified (OME-1497).

# FEATURE: OME-1138 D18, G0 part 3 (contract §5.3: "a missed persistence path fails acceptance").
# A Connection error mark on a `none` or unmarked pair must go through `mark_error_checked`;
# only the `migrated` paths, which keep their own fences, call the store directly. A NEW direct
# call fails here until its author routes it through the check or proves its pair is migrated.
"""

from __future__ import annotations

import ast
from pathlib import Path

import aigateway

SOURCE = Path(aigateway.__file__).parent

# Callers allowed to call `mark_error` directly, with the reason.
DIRECT = {
    # The check itself.
    "core.provider_access.writer_floor:mark_error_checked": 2,
    # `migrated` pairs only (§5.3: migrated paths keep the fences they already have).
    "core.provider_access.connection_authority:authorize_migrated": 1,
    "core.provider_access.connection_authority:record_dispatch_failure_migrated": 1,
}


def _direct_calls() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        module = ".".join(path.relative_to(SOURCE).with_suffix("").parts)
        tree = ast.parse(path.read_text(), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "mark_error"
                ):
                    site = f"{module}:{function.name}"
                    found[site] = found.get(site, 0) + 1
    return found


def test_every_direct_error_mark_is_the_check_or_a_migrated_path() -> None:
    assert _direct_calls() == DIRECT


def test_the_inventory_scan_finds_a_new_direct_call(tmp_path, monkeypatch) -> None:
    # Falsifier: the scan is not vacuous — an unclassified caller shows up.
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "rogue.py").write_text(
        "async def mark_it(store, row):\n    await store.mark_error(row, 'x')\n"
    )
    monkeypatch.setattr(f"{__name__}.SOURCE", package)

    assert _direct_calls() == {"rogue:mark_it": 1}
