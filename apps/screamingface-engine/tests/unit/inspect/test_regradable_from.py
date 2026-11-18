# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A Benchmark row declares the old revisions it may be re-graded from (OME-1909).

A re-grade replays an old score's pinned cache under the Benchmark's bumped published
revision, which is only sound when the Cases are the same bytes. The row therefore pairs each
old revision with the Case Digest the Cases computed on the day of the bump, and assembly refuses
a pair whose digest is not the digest the Cases compute now. That catches a Case change made
after the bump; an earlier one, under a held id, is caught by the pinned cache missing instead.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    TASK_REPLAY_CASES,
    BenchmarkSpec,
    _assemble,
)
from screamingface_engine_inspect.single_shot import ImportedBenchmark  # noqa: E402

_KEY: str = "mmlu_pro"
_OLD_REVISION: str = "145edec84bfc2324"
_CURRENT_DIGEST: str = TASK_REPLAY_CASES[_KEY].case_digest


def _assembled(
    regradable_from: tuple[tuple[str, str], ...] = (),
) -> ImportedBenchmark:
    """Assemble the real mmlu_pro row with a replaced declaration, uncached."""

    row: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == _KEY)
    return _assemble(dataclasses.replace(row, regradable_from=regradable_from))


def test_a_row_lists_the_old_revisions_it_may_be_regraded_from() -> None:
    """The catalogue entry names each old revision whose Cases match the current ones."""

    benchmark: ImportedBenchmark = _assembled(((_OLD_REVISION, _CURRENT_DIGEST),))

    assert benchmark.benchmark.catalog_entry()["regradable_from"] == [_OLD_REVISION]
    assert benchmark.benchmark.resource(1)["regradable_from"] == [_OLD_REVISION]


def test_a_row_whose_cases_changed_since_the_old_revision_is_refused_at_assembly() -> None:
    """INVARIANT: a re-grade is only for the same Cases; a stale digest fails the build."""

    with pytest.raises(ValueError, match="Case Digest"):
        _assembled(((_OLD_REVISION, "0" * 64),))


def test_regradable_from_moves_no_fingerprint() -> None:
    """Declaring old revisions changes nothing a score depends on."""

    declared: ImportedBenchmark = _assembled(((_OLD_REVISION, _CURRENT_DIGEST),))

    assert declared.fingerprint == _assembled().fingerprint
    assert declared.benchmark.revision == _assembled().benchmark.revision


def test_no_declaration_serves_an_empty_list() -> None:
    """Every entry carries the key, so no reader needs an absent-key branch."""

    assert _assembled().benchmark.catalog_entry()["regradable_from"] == []
