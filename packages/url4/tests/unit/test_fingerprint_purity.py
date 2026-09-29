"""C11 row 1: `url4.fingerprint` is pure — no I/O, and no import of the SDK, the engine or the
scoreboard (E14 contracts.md C11; decision D7 X-18: unit tests enforce it).

STORY: as a maintainer of the scoreboard I import `url4.fingerprint` into a service that must
not pull in the SDK or the engine, and I want a test to fail if the module ever reaches for them.

# AIDEV-NOTE: these are guards. They pass on correct code by design; the "sees" tests are the
# teeth checks that prove each scan can fail.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import url4.fingerprint as fingerprint_module

_SOURCE = Path(fingerprint_module.__file__).read_text(encoding="utf-8")
_ALLOWED_IMPORTS = {
    "__future__",
    "dataclasses",
    "hashlib",
    "url4.core.nodes",
    "url4.core.parser",
    "url4.core.render",
}
_FORBIDDEN_CALLS = {"open", "print", "input", "exec", "eval", "compile", "__import__"}


def _imports_of(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _bare_calls_of(source: str) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FORBIDDEN_CALLS
    }


def _loaded_after_import(module: str, watch: tuple[str, ...]) -> set[str]:
    """Which of ``watch`` are in `sys.modules` after importing ``module`` in a fresh interpreter."""
    code = (
        f"import {module}, sys;"
        f"print(' '.join(sorted({{n.split('.')[0] for n in sys.modules}} & set({watch!r}))))"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell, test-controlled input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(done.stdout.split())


def test_fingerprint_module_imports_only_core_and_stdlib() -> None:
    assert _imports_of(_SOURCE) <= _ALLOWED_IMPORTS


def test_the_import_scan_sees_a_forbidden_import() -> None:
    found = _imports_of("import screamingface\nfrom scoreboard.x import y\n")
    assert found == {"screamingface", "scoreboard.x"}


def test_importing_url4_fingerprint_loads_no_sdk_engine_or_scoreboard() -> None:
    watch = ("screamingface", "screamingface_engine", "scoreboard", "httpx")
    assert _loaded_after_import("url4.fingerprint", watch) == set()


def test_fingerprint_module_has_no_io_calls() -> None:
    assert _bare_calls_of(_SOURCE) == set()


def test_the_call_scan_sees_open() -> None:
    assert _bare_calls_of("open('x')\n") == {"open"}


def test_fingerprint_module_names_no_sdk_binding() -> None:
    # WHY: the caller owns the name `_sf_recipe` (D3). Equality, not substring: the docstring
    # may talk about it, but no string constant may BE the name.
    constants = [
        node.value
        for node in ast.walk(ast.parse(_SOURCE))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert "_sf_recipe" not in constants
