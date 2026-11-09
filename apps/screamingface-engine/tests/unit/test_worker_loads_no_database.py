"""E5 P1 spec §9: the worker never loads the Run registry or the database stack.

FEATURE: first-class Runs (OME-1785). WHY a real import and not only `check_layering.py`: the
script checks direct imports, and the worker already imports control-plane modules (`config`,
`adapters.factory`, `metrics`) that may import `runs`. One added line in `adapters/factory.py`
would load Tortoise into every worker while the script still passed. Importing the worker's
modules in a fresh process and reading `sys.modules` follows every hop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# The worker's modules, the child it launches, and `adapters.factory`, which the worker imports
# inside a function, so a plain import of the loop would not reach it.
_WORKER_MODULES = (
    "screamingface_engine.worker.loop",
    "screamingface_engine.worker.supervisor",
    "screamingface_engine.worker.warm_pool",
    "screamingface_engine.worker.metrics",
    "screamingface_engine.worker.exec_wrapper",
    "screamingface_engine.runner.main",
    "screamingface_engine.adapters.factory",
)
_FORBIDDEN_ROOTS = ("tortoise", "asyncpg", "aiosqlite")
_REGISTRY = "screamingface_engine.runs"


def _probe(modules: tuple[str, ...]) -> str:
    """A script that imports ``modules`` and prints every database or registry module loaded."""
    return f"""
import importlib, json, sys
for name in {modules!r}:
    importlib.import_module(name)
print(json.dumps(sorted(
    name for name in sys.modules
    if name.split(".")[0] in {_FORBIDDEN_ROOTS!r}
    or name == {_REGISTRY!r} or name.startswith({_REGISTRY!r} + ".")
)))
"""


def _loaded(probe: str, env: dict[str, str] | None = None) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
        env=env,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_worker_loads_no_registry_and_no_database_stack() -> None:
    assert _loaded(_probe(_WORKER_MODULES)) == []


def test_the_probe_sees_a_database_module_loaded_one_hop_away(tmp_path: Path) -> None:
    # WHY: proves the probe would catch the drift it exists for, not just pass on an empty set.
    # A stand-in worker module that imports a stand-in `tortoise`, the way a stray line in
    # `adapters/factory.py` would; the probe imports only the worker module.
    (tmp_path / "tortoise").mkdir()
    (tmp_path / "tortoise" / "__init__.py").write_text("")
    (tmp_path / "stray_worker_module.py").write_text("import tortoise\n")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), *sys.path])}

    assert "tortoise" in _loaded(_probe((*_WORKER_MODULES, "stray_worker_module")), env)
