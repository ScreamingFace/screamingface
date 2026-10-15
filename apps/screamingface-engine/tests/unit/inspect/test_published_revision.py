"""A Benchmark may publish a hand-set revision instead of the fingerprint it computes.

FEATURE (OME-1610): the published revision is what submissions and the leaderboard key on, so it
moves only by a deliberate bump with owner sign-off, never because a computed fingerprint
changed. A row sets ``published_revision`` and the Engine publishes it as is: no runtime
comparison, no refusal, so a mismatch can never take a Benchmark down on prod. The alarm is
``test_published_revisions``, which holds the fingerprint each hand-set revision stands for.

Runs only with the `inspect` extra installed: the fingerprint hashes the pinned inspect packages.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    ImportedBenchmark,
    single_shot_benchmark,
)

#: An older published revision the stand-in publishes (made up; 16 hex like every revision).
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


def _routes(imported: ImportedBenchmark) -> list[str]:
    """Every route the Benchmark serves; each one carries the published revision."""

    return [
        imported.cases_route,
        imported.check_route,
        imported.case_evaluation_route,
        imported.aggregate_route,
    ]


def test_a_published_revision_is_what_the_benchmark_publishes() -> None:
    """The hand-set id is published everywhere a revision shows (``Benchmark.revision`` and
    every route), so a submission recorded under it still resolves. It is published even when
    the exam changed (another pin): no runtime comparison, so prod never refuses the Benchmark;
    the fingerprint still moves, for test_published_revisions to notice. The id never feeds the
    fingerprint either: assembling with it computes what assembling without it does."""

    plain: ImportedBenchmark = _assemble("published-plain", "exam=v1")
    published: ImportedBenchmark = _assemble("published", "exam=v1", _OLD)
    changed: ImportedBenchmark = _assemble("published-changed", "exam=v2", _OLD)

    assert published.benchmark.revision == _OLD
    assert all(f"/{_OLD}/" in route for route in _routes(published)), _routes(published)
    assert published.computed_revision == plain.computed_revision != _OLD
    assert not any(published.computed_revision in route for route in _routes(published))
    assert changed.benchmark.revision == _OLD
    assert changed.computed_revision != published.computed_revision


def test_no_published_revision_publishes_the_computed_fingerprint() -> None:
    """Unset, nothing changes: the published revision is the computed fingerprint. Every
    published row's literal is pinned in test_published_revisions."""

    unset: ImportedBenchmark = _assemble("published-unset", "exam=v1")

    assert unset.benchmark.revision == unset.computed_revision
    assert all(f"/{unset.computed_revision}/" in route for route in _routes(unset))


def test_only_rows_with_an_equivalence_proof_set_a_published_revision() -> None:
    """INVARIANT: a hand-set published revision is a per-Benchmark owner decision backed by a
    golden that replays with zero misses, never a default. Any row joining this list is a new
    decision and must be named here with its proof in the PR, and its fingerprint recorded in
    test_published_revisions."""

    publishing: dict[str, Any] = {
        spec.key: spec.published_revision
        for spec in BENCHMARKS
        if spec.published_revision is not None
    }

    # ifeval (OME-1527 row 15, OME-1610): the hand-built revision, published by the local Task.
    assert publishing == {"ifeval": "1cba769ece27f7ef"}
