# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The bump command prints the `regradable_from` line a move needs (OME-1909).

FEATURE: OME-1909. A re-grade onto a moved id is refused unless the row lists the old id with
its Case Digest, so a move that forgets the line strands every old entry. The bump checklist is
where a developer learns the move's edits, so it prints the exact line, ahead of the re-grade
step that depends on it.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.benchmarks import TASK_REPLAY_CASES  # noqa: E402

_ENGINE: Path = Path(__file__).resolve().parents[3]
_SCRIPT: Path = _ENGINE / "scripts" / "benchmark_bump.py"


def _bump() -> ModuleType:
    """Load the command by path, as `just engine benchmark-bump` runs it."""

    spec = importlib.util.spec_from_file_location("benchmark_bump", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_move_prints_the_regradable_from_line_before_the_regrade_step(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """paws publishes 8f4e0e9c0864a6e7 and computes a new fingerprint: the checklist prints
    the pair (old id, the Case Digest its Cases compute now) the row must declare, before the
    step that re-grades old entries, because that re-grade is refused without it."""

    digest: str = TASK_REPLAY_CASES["paws"].case_digest

    status: int = _bump().main(["paws"])

    out: str = capsys.readouterr().out
    line: str = f'regradable_from=(("8f4e0e9c0864a6e7", "{digest}"),),'
    assert status == 0
    assert line in out
    assert out.index(line) < out.index("After the deploy, re-grade")


def test_a_medxpert_move_says_it_has_no_regradable_from_path(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """medxpert is hand-built, with no catalogue row to declare `regradable_from` on: the
    checklist says its old entries need a fresh run instead of printing a line nothing reads."""

    from screamingface_engine.benchmarks.medxpert import definition

    # WHY a made-up fingerprint: medxpert computes the id it publishes today, and only a
    # moved fingerprint prints the move checklist.
    monkeypatch.setattr(definition, "FINGERPRINT", "fedcba9876543210")

    status: int = _bump().main(["medxpert"])

    out: str = capsys.readouterr().out
    assert status == 0
    assert "no regradable_from path yet" in out
    assert "regradable_from=((" not in out
