"""DEC-4 / DC-D2: no module imports the removed node tier or the App's forwarder to it.

The rule is driven against a synthetic source tree (so it can fail for the right reason) and
against the real tree (so the removal stays done). It holds for EXEMPT modules too: `local.py`
and `cli.py` skip the half-disjointness rules, never this one.
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


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("local.py", "from screamingface_engine.world.node_tier import build_node_tier\n"),
        ("cli.py", "def f():\n    from screamingface_engine.world import node_tier\n"),
        ("app.py", "from screamingface_engine.rest.forwarder import install_forwarder\n"),
        ("rest/mounts.py", "from .forwarder import forwarded_headers\n"),
    ],
)
def test_no_module_imports_node_tier(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, relative: str, source: str
) -> None:
    layering = _layering()
    src = tmp_path / "apps/screamingface-engine/src/screamingface_engine"
    target = src / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)
    monkeypatch.setattr(layering, "SRC", src)
    monkeypatch.setattr(layering, "ROOT", tmp_path)

    offenders = layering.check_layers()

    assert any(relative in line and "was removed" in line for line in offenders), offenders


def test_the_real_tree_imports_no_removed_module() -> None:
    offenders = [line for line in _layering().check_layers() if "was removed" in line]
    assert offenders == []


def test_the_removed_modules_are_gone() -> None:
    package = _REPO_ROOT / "apps/screamingface-engine/src/screamingface_engine"
    assert not (package / "world/node_tier").exists()
    assert not (package / "rest/forwarder.py").exists()
