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
    exam moves it, as for every row today but the two healthbench Benchmarks. Set, the same
    change leaves the published id where it was (WHY: OME-1610, never moved as a side effect)."""

    unset_v1: ImportedBenchmark = _assemble("published-unset-v1", "exam=v1")
    unset_v2: ImportedBenchmark = _assemble("published-unset-v2", "exam=v2")
    kept_v2: ImportedBenchmark = _assemble("published-kept-v2", "exam=v2", _OLD)

    assert unset_v1.benchmark.revision != unset_v2.benchmark.revision
    assert all(f"/{unset_v2.benchmark.revision}/" in route for route in _routes(unset_v2))
    assert kept_v2.benchmark.revision == _OLD


def test_only_rows_with_an_equivalence_proof_set_a_published_revision() -> None:
    """INVARIANT: a hand-set published id is a per-Benchmark owner decision, never a default,
    backed by proof that the exam is unchanged (a golden that replays with zero misses) or, for
    a grading fix that keeps every Case, by the owner's hold with no leaderboard result under the
    old grading (OME-1701). Any row joining this list is a new decision and must be named here."""

    hand_set: dict[str, str] = {
        spec.key: spec.published_revision
        for spec in BENCHMARKS
        if spec.published_revision is not None
    }

    # healthbench (OME-1527 row 20) and ifeval (row 15): the hand-built revisions, kept on the
    # local Tasks.
    assert hand_set == {
        "healthbench-worst30": "39cfd96b068f7230",
        "healthbench-professional": "d8fb037307f35415",
        "ifeval": "1cba769ece27f7ef",
        # OME-1701 (owner decision, 2026-10-22: revisions are frozen): grading fixes adopted
        # from inspect_evals that keep every Case; each computed fingerprint is pinned in
        # test_benchmark_fingerprints.py.
        "paws": "8f4e0e9c0864a6e7",
        "boolq": "00d4443ca7e66d43",
        "chembench": "a36d91b7eb601253",
        "infinite_bench_math_find": "eb87494cb4dab437",
        "math": "0fb750cf19e00c11",
        "aime24": "2e4ce70a8953233a",
        "aime25": "b207e9fe34ea7517",
        "aime26": "c3ccaa828160f661",
    }
