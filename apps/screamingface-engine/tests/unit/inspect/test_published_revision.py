"""A row may publish a hand-set revision instead of its computed fingerprint (OME-1527).

FEATURE: the published revision is what submissions and the leaderboard key on, so it is
never moved by a computed fingerprint, only by a deliberate bump (OME-1610). A row that sets
``published_revision`` publishes exactly that id, and the assembled Benchmark still exposes
its ``computed_revision`` for the tests to pin: the alarm lives in CI, never in a deployed
Engine (``test_published_revisions`` pins each hand-set row's fingerprint).

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
    route carry it. The fingerprint is still computed (and not moved by the field, which is
    no revision input) for the tests to pin. WHY no comparison at assembly: a changed exam
    moves only the fingerprint, so it fails CI (test_published_revisions), never a deployed
    Engine."""

    plain: ImportedBenchmark = _assemble("published-plain", "exam=v1")

    kept: ImportedBenchmark = _assemble("published-kept", "exam=v1", _OLD)

    assert kept.benchmark.revision == _OLD
    assert all(f"/{_OLD}/" in route for route in _routes(kept)), _routes(kept)
    assert not any(plain.computed_revision in route for route in _routes(kept))
    assert kept.computed_revision == plain.computed_revision


def test_no_published_revision_publishes_the_computed_fingerprint() -> None:
    """Unset, nothing changes: the published revision is the computed fingerprint, as for every
    row today but the two healthbench Benchmarks."""

    unset: ImportedBenchmark = _assemble("published-unset", "exam=v1")

    assert unset.benchmark.revision == unset.computed_revision
    assert all(f"/{unset.computed_revision}/" in route for route in _routes(unset))


def test_only_rows_with_an_equivalence_proof_set_a_published_revision() -> None:
    """INVARIANT: a hand-set published id is a per-Benchmark owner decision backed by proof
    that the exam is unchanged (a golden that replays with zero misses), never a default. Any
    row joining this list is a new decision and must be named here, and its fingerprint pinned
    in test_published_revisions."""

    hand_set: dict[str, str] = {
        spec.key: spec.published_revision
        for spec in BENCHMARKS
        if spec.published_revision is not None
    }

    # ifeval (OME-1527 row 15): the hand-built revision, kept on the local Task.
    assert hand_set == {
        "ifeval": "1cba769ece27f7ef",
    }
