"""Workbench UI skeleton (unit 4 plan, Task 1): the dev env can render notebooks to HTML."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"


def test_nbconvert_is_importable_in_the_dev_env() -> None:
    from nbconvert import HTMLExporter  # noqa: F401  # pyright: ignore[reportUnusedImport]


def test_nbconvert_is_a_direct_dev_dependency_not_only_transitive() -> None:
    # WHY: nbconvert already arrives transitively through jupyterlab; the UI imports it
    # directly, so the dev group must name it (and the runtime extra must not).
    data = tomllib.loads(_PYPROJECT.read_text())
    names = {
        re.split(r"[\s<>=!~\[;]", spec, maxsplit=1)[0] for spec in data["dependency-groups"]["dev"]
    }
    assert "nbconvert" in names
    runtime = data["project"]["optional-dependencies"].get("runtime", [])
    assert not any(spec.startswith("nbconvert") for spec in runtime)
