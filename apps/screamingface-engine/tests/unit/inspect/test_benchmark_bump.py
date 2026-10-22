# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The bump command prints the cost and the lines to edit, and never edits a file (OME-1610).

FEATURE: a Benchmark's published id moves only by a deliberate, reviewed act. The command is
the one place that act starts, so its WARNING is what a developer or a coding agent reads before
hiding every leaderboard result under the old id.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

_ENGINE: Path = Path(__file__).resolve().parents[3]
_SCRIPT: Path = _ENGINE / "scripts" / "benchmark_bump.py"
#: Every file the printed checklist names: the command must leave each one byte-identical.
_EDITED_BY_HAND: tuple[Path, ...] = (
    _ENGINE / "src" / "screamingface_engine_inspect" / "benchmarks.py",
    _ENGINE / "src" / "screamingface_engine" / "benchmarks" / "medxpert" / "definition.py",
    _ENGINE / "tests" / "unit" / "inspect" / "test_published_revisions.py",
    _ENGINE / "tests" / "unit" / "inspect" / "test_benchmark_fingerprints.py",
    _ENGINE / "CHANGELOG.md",
)


def _bump() -> ModuleType:
    """Load the command by path, as `just engine benchmark-bump` runs it."""

    spec = importlib.util.spec_from_file_location("benchmark_bump", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_held_row_is_offered_its_fingerprint_with_the_warning_and_no_file_changes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """paws publishes 8f4e0e9c0864a6e7 and computes 992540ea3309d384 (OME-1701 held it): the
    command shows both, the cost of moving, the owner sign-off and every line to edit, and
    writes nothing, so the developer still makes the change by hand in a reviewed PR."""

    before: dict[Path, bytes] = {path: path.read_bytes() for path in _EDITED_BY_HAND}

    status: int = _bump().main(["paws"])

    out: str = capsys.readouterr().out
    assert status == 0
    assert "WARNING" in out
    assert "hides every leaderboard result" in out
    assert "owner" in out and "sign-off" in out
    assert 'published_revision="8f4e0e9c0864a6e7"' in out
    assert 'published_revision="992540ea3309d384"' in out
    assert "test_published_revisions.py" in out
    assert "test_benchmark_fingerprints.py" in out
    assert "CHANGELOG.md" in out
    assert {path: path.read_bytes() for path in _EDITED_BY_HAND} == before


def test_an_unchanged_row_is_told_there_is_nothing_to_bump(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """gsm8k computes the id it publishes (075954bfd63059e0), so nothing about its exam moved
    since the id was set: the command says so instead of printing a move to the same id."""

    status: int = _bump().main(["gsm8k"])

    out: str = capsys.readouterr().out
    assert status == 0
    assert "075954bfd63059e0" in out
    assert "nothing to bump" in out


def test_medxpert_points_at_its_own_definition(capsys: pytest.CaptureFixture[str]) -> None:
    """The hand-built Benchmark has no catalogue row, so its id lives in its own definition."""

    status: int = _bump().main(["medxpert"])

    out: str = capsys.readouterr().out
    assert status == 0
    assert "medxpert/definition.py" in out


def test_a_medxpert_move_names_its_own_pins(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """medxpert has no row in test_published_revisions.py (that test reads catalogue rows
    only): its published id is pinned by its migration golden and the early-grade fixture's
    routes, so a move checklist naming the catalogue file would send the developer to the
    wrong test."""

    from screamingface_engine.benchmarks.medxpert import definition

    # WHY a made-up fingerprint: medxpert computes the id it publishes today, and only a
    # moved fingerprint prints the move checklist.
    monkeypatch.setattr(definition, "FINGERPRINT", "fedcba9876543210")

    status: int = _bump().main(["medxpert"])

    out: str = capsys.readouterr().out
    assert status == 0
    assert 'REVISION = "1e5a3b8a461a52f7"  ->  REVISION = "fedcba9876543210"' in out
    assert "test_medxpert_migration_golden.py" in out
    assert "early_grade_compatibility.json" in out
    assert "test_published_revisions.py" not in out


def test_an_unknown_key_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """A typo must not print a checklist for nothing; the error names the key."""

    status: int = _bump().main(["gsm8kk"])

    assert status == 2
    assert "gsm8kk" in capsys.readouterr().err


def test_a_new_row_without_an_id_is_told_to_set_one(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new row with no ``published_revision`` serves its fingerprint, which equals itself, so
    "nothing to bump" would be wrong: the guide and the catalogue test send new rows here to
    learn the id to set."""

    from dataclasses import replace

    from screamingface_engine_inspect import benchmarks, single_shot

    # WHY gsm8k as the stand-in: its fingerprint, 075954bfd63059e0, is also its published id,
    # so unsetting the id leaves a row exactly like a new one.
    spec = next(row for row in benchmarks.BENCHMARKS if row.key == "gsm8k")
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (replace(spec, published_revision=None),))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})

    status: int = _bump().main(["gsm8k"])

    out: str = capsys.readouterr().out
    assert status == 0
    assert 'published_revision="075954bfd63059e0"' in out
    assert "test_published_revisions.py" in out
    assert "test_benchmark_fingerprints.py" in out
    assert "nothing to bump" not in out
