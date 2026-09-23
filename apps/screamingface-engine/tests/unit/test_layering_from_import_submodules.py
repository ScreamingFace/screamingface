"""FX-94 — the layering gate sees a submodule imported BY NAME from its package.

# WHY this file exists. `check_layering.py` recorded the imported names as submodules only for
# `from screamingface_engine import X`. For `from screamingface_engine.world import serving` it
# recorded `world` alone, so the runner/`world.serving` rule (and the `adapters.factory` rule)
# could be passed by moving one dotted segment from the module path to the imported name. The
# tests drive the real script against synthetic trees, so they pin the RULE, not today's tree.
"""

from __future__ import annotations

import importlib.util
import pathlib
import types

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / ".claude/scripts/check_layering.py"


def _layering() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_layering_fx94", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offenders(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, relative: str, source: str
) -> list[str]:
    layering = _layering()
    src = tmp_path / "apps/screamingface-engine/src/screamingface_engine"
    target = src / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)
    monkeypatch.setattr(layering, "SRC", src)
    monkeypatch.setattr(layering, "ROOT", tmp_path)
    return layering.check_layers()


@pytest.mark.parametrize(
    "source",
    [
        "from screamingface_engine.world import serving\n",
        "from screamingface_engine.world import serving as composed\n",
        "from ..world import serving\n",
    ],
    ids=["absolute", "absolute-aliased", "relative"],
)
def test_a_runner_module_importing_world_serving_by_name_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    offenders = _offenders(tmp_path, monkeypatch, "runner/by_name.py", source)
    # INVARIANT: the offence names the forbidden SUBMODULE, not just the package it lives in.
    assert any("runner/by_name.py" in o and "world.serving" in o for o in offenders), offenders


def test_a_runner_module_importing_the_adapter_factory_by_name_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    offenders = _offenders(
        tmp_path,
        monkeypatch,
        "runner/by_name.py",
        "from screamingface_engine.adapters import factory\n",
    )
    assert any("runner/by_name.py" in o and "adapters.factory" in o for o in offenders), offenders


@pytest.mark.parametrize(
    "source",
    [
        "from screamingface_engine.world import build_world\n",
        "from ..world import factory\n",
    ],
    ids=["absolute", "relative"],
)
def test_a_runner_module_importing_other_world_names_still_passes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    offenders = _offenders(tmp_path, monkeypatch, "runner/by_name.py", source)
    assert not any("runner/by_name.py" in o for o in offenders), offenders
