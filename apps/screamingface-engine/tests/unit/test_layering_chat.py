"""CR-15: the chat leaf is shared, and the chat world module lives in the world half.

FEATURE: OpenAI-compatible chat endpoint (chat-run §4 Layering). `chat/` is a shared leaf that
both halves import and that imports neither; `world/chat_turn.py` is the world adapter and may
import the leaf and benchmarks, but never a half. Driven against a synthetic tree (so each rule
fails for the right reason) and against the real tree (so it stays clean).
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


def test_layering_gate_lists_chat_leaf_and_chat_world_modules() -> None:
    layering = _layering()

    assert layering._half_of(layering.SRC / "chat" / "input.py") is None
    assert layering._half_of(layering.SRC / "world" / "chat_turn.py") == "world"
    assert layering.check_layers() == []


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("chat/x.py", "from screamingface_engine.rest import routes\n"),
        ("chat/x.py", "from screamingface_engine.runner.executor import Url4Executor\n"),
        ("chat/x.py", "from screamingface_engine.world import chat_turn\n"),
        ("chat/x.py", "def f():\n    from screamingface_engine.app import create_app\n"),
    ],
)
def test_the_chat_leaf_imports_neither_half_nor_the_world(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, relative: str, source: str
) -> None:
    offenders = _offenders(tmp_path, monkeypatch, {relative: source})

    assert any("chat/x.py" in line for line in offenders), offenders


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("world/chat_turn.py", "from screamingface_engine.runner.executor import Url4Executor\n"),
        ("world/chat_turn.py", "from screamingface_engine.rest.routes import _schedule\n"),
        ("world/chat_turn.py", "from screamingface_engine.worker import loop\n"),
    ],
)
def test_the_chat_world_module_imports_neither_half(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, relative: str, source: str
) -> None:
    offenders = _offenders(tmp_path, monkeypatch, {relative: source})

    assert any("world/chat_turn.py" in line for line in offenders), offenders


def test_the_chat_world_module_may_import_the_chat_leaf_and_benchmarks(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    offenders = _offenders(
        tmp_path,
        monkeypatch,
        {
            "world/chat_turn.py": (
                "from screamingface_engine.chat.views import text_view\n"
                "from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe\n"
            ),
        },
    )

    assert not any("world/chat_turn.py" in line for line in offenders), offenders
