"""E5 P1 spec §9: every database write goes through the App.

FEATURE: first-class Runs (OME-1785). The Run registry is the App's; the runner, the worker and
every shared leaf may not import it, and only the registry imports the database stack. Driven
against a synthetic tree (so each rule fails for the right reason) and against the real tree (so
it stays clean).
"""

from __future__ import annotations

import importlib.util
import pathlib
import types

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / ".claude/scripts/check_layering.py"


def _layering() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_layering", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offenders(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]
) -> list[str]:
    layering = _layering()
    src = tmp_path / "apps/screamingface-engine/src/screamingface_engine"
    for relative, source in files.items():
        target = src / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    monkeypatch.setattr(layering, "SRC", src)
    monkeypatch.setattr(layering, "ROOT", tmp_path)
    return layering.check_layers()


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("worker/supervisor.py", "from screamingface_engine.runs.registry import RunRegistry\n"),
        ("worker/claim.py", "from ..runs import model\n"),
        (
            "worker/supervisor.py",
            "from screamingface_engine.adapters.run_registry_tortoise import TortoiseRunRegistry\n",
        ),
        ("runner/main.py", "from screamingface_engine.runs.state import derive_state\n"),
        ("candidate_outcomes.py", "from screamingface_engine.runs.model import RunRecord\n"),
    ],
)
def test_nothing_outside_the_control_plane_imports_the_registry(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, relative: str, source: str
) -> None:
    offenders = _offenders(tmp_path, monkeypatch, {relative: source})

    assert any(relative in line for line in offenders), offenders


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("worker/supervisor.py", "import tortoise\n"),
        ("runner/main.py", "from tortoise import Tortoise\n"),
        ("candidate_outcomes.py", "import asyncpg\n"),
        ("app.py", "import aiosqlite\n"),
        # WHY local.py too: it is exempt from the half-disjointness rules, never from this one.
        ("local.py", "def f():\n    from tortoise.models import Model\n"),
    ],
)
def test_only_the_registry_imports_the_database_stack(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, relative: str, source: str
) -> None:
    offenders = _offenders(tmp_path, monkeypatch, {relative: source})

    assert any(relative in line and "database stack" in line for line in offenders), offenders


def test_the_registry_and_the_app_may_use_what_they_own(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    offenders = _offenders(
        tmp_path,
        monkeypatch,
        {
            "app.py": "from screamingface_engine.runs.registry import RunRegistry\n",
            "runs/db.py": "from tortoise import Tortoise\nimport asyncpg\n",
            "adapters/run_registry_tortoise.py": (
                "from tortoise.transactions import in_transaction\n"
                "from screamingface_engine.runs.model import RunRecord\n"
            ),
        },
    )

    assert offenders == []


def test_the_registry_adapter_may_grow_into_a_package(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    offenders = _offenders(
        tmp_path,
        monkeypatch,
        {
            "adapters/run_registry_tortoise/__init__.py": "from tortoise import Tortoise\n",
            "adapters/run_registry_tortoise/models.py": "from tortoise.models import Model\n",
        },
    )

    assert offenders == []


def test_the_real_tree_keeps_database_writes_in_the_app() -> None:
    offenders = [
        line
        for line in _layering().check_layers()
        if "screamingface_engine.runs" in line
        or "run_registry_tortoise" in line
        or "database stack" in line
    ]
    assert offenders == []
