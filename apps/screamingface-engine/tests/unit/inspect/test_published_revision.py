"""A row may publish a hand-set revision instead of its computed fingerprint (OME-1527).

FEATURE: the published revision is what submissions and the leaderboard key on, so it is
never moved by a computed fingerprint, only by a deliberate bump (OME-1610). A row that sets
``published_revision`` publishes exactly that id, and nothing compares it with the fingerprint
(owner decision, 2026-10-15).

Runs only with the `inspect` extra installed: the revision hashes the pinned inspect packages.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    ImportedBenchmark,
    single_shot_benchmark,
)

#: An older published revision the stand-in keeps (made up; 16 hex like every revision).
_OLD: str = "0123456789abcdef"


def _assemble(key: str, pin: str, published_revision: str | None = None) -> ImportedBenchmark:
    """A stand-in Benchmark whose computed fingerprint moves with ``pin``; nothing is graded."""

    return single_shot_benchmark(
        benchmark_key=key,
        title="Published revision",
        description="A stand-in for a migrated Benchmark.",
        focus="Identity",
        dataset_url="https://example.test/published",
        case_count=3,
        revision_pins=(pin,),
        scorer_factory=lambda: None,
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="easy",
        failure_policy="coverage_declare",
        published_revision=published_revision,
    )


def _routes(benchmark: ImportedBenchmark) -> list[str]:
    """Every route the Benchmark serves under its revision."""

    return [
        benchmark.cases_route,
        benchmark.check_route,
        benchmark.check_surface_route,
        benchmark.case_evaluation_route,
        benchmark.aggregate_route,
    ]


def test_a_published_revision_is_what_the_benchmark_publishes() -> None:
    """A submission recorded under the old id still resolves: ``Benchmark.revision`` and every
    route carry it, never the fingerprint the same exam computes."""

    plain: ImportedBenchmark = _assemble("published-plain", "exam=v1")

    kept: ImportedBenchmark = _assemble("published-kept", "exam=v1", _OLD)

    assert kept.benchmark.revision == _OLD
    assert all(f"/{_OLD}/" in route for route in _routes(kept)), _routes(kept)
    assert not any(plain.benchmark.revision in route for route in _routes(kept))


def test_a_changed_exam_moves_only_an_unset_revision() -> None:
    """Unset, nothing changes: the published revision is the computed fingerprint, so a changed
    exam moves it; only test stand-ins leave it unset, since every catalogue row sets it. Set,
    the same change leaves the published id where it was (WHY: OME-1610, never moved as a side
    effect)."""

    unset_v1: ImportedBenchmark = _assemble("published-unset-v1", "exam=v1")
    unset_v2: ImportedBenchmark = _assemble("published-unset-v2", "exam=v2")
    kept_v2: ImportedBenchmark = _assemble("published-kept-v2", "exam=v2", _OLD)

    assert unset_v1.benchmark.revision != unset_v2.benchmark.revision
    assert all(f"/{unset_v2.benchmark.revision}/" in route for route in _routes(unset_v2))
    assert kept_v2.benchmark.revision == _OLD


def test_every_catalogue_row_sets_its_published_revision() -> None:
    """INVARIANT: no Benchmark publishes a computed id (OME-1610). Every row hand-sets the id
    submissions and the leaderboard key on, so a code change can never move it; the computed
    fingerprint is pinned in ``test_benchmark_fingerprints.py`` and is only an alarm. ``None``
    is for test stand-ins only. A new row sets its own fingerprint here on the day it is added."""

    unset: list[str] = [spec.key for spec in BENCHMARKS if spec.published_revision is None]

    assert unset == [], (
        f"{unset}: set published_revision on each row. A new Benchmark sets the fingerprint it "
        "computes today (just engine benchmark-bump <key> prints it); an existing one keeps the "
        "id it already publishes (test_published_revisions.py)."
    )


def test_a_copied_row_that_kept_the_donors_key_and_id_is_refused() -> None:
    """A copy-pasted row keeps the donor's key AND its hand-set id, so the ids alone cannot
    tell the two apart; their fingerprints differ, so assembly refuses the second one instead of
    serving the donor's routes for the wrong exam."""

    _assemble("published-copied", "exam=donor", _OLD)

    with pytest.raises(ValueError, match="duplicate benchmark_key"):
        _assemble("published-copied", "exam=copy", _OLD)
