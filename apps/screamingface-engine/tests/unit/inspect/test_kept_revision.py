"""A migrated Benchmark may keep its published revision, but only while the exam is unchanged.

FEATURE (OME-1527): the published revision is what submissions and the leaderboard key on, so
a migration that moves it hides every existing result. A row that proves its exam unchanged
(its recorded golden replays with zero misses) sets ``kept_revision=(published, stands_for)``:
the Benchmark publishes ``published`` while its revision computes to exactly ``stands_for``.

INVARIANT: a kept revision never hides a real exam change. When the computed revision is
anything else, assembly refuses by name.

Runs only with the `inspect` extra installed: the revision hashes the pinned inspect packages.
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

#: An older published revision the stand-in keeps (made up; 16 hex like every revision).
_OLD: str = "0123456789abcdef"


def _assemble(
    key: str, pin: str, kept_revision: tuple[str, str] | None = None
) -> ImportedBenchmark:
    """A stand-in Benchmark whose computed revision moves with ``pin``; nothing is graded."""

    return single_shot_benchmark(
        benchmark_key=key,
        title="Kept revision",
        description="A stand-in for a migrated Benchmark.",
        focus="Identity",
        dataset_url="https://example.test/kept",
        case_count=3,
        revision_pins=(pin,),
        scorer_factory=lambda: None,
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="easy",
        kept_revision=kept_revision,
    )


def _computed(key: str, pin: str) -> str:
    """The revision the stand-in computes for ``pin``, with no revision kept."""

    return _assemble(key, pin).benchmark.revision


def test_a_kept_revision_is_published_while_the_revision_computes_to_what_it_stands_for() -> None:
    """The old id is published everywhere a revision shows: ``Benchmark.revision`` and every
    route, so a submission recorded under it still resolves."""

    computed: str = _computed("kept-matches-plain", "exam=v1")

    kept: ImportedBenchmark = _assemble("kept-matches", "exam=v1", (_OLD, computed))

    assert kept.benchmark.revision == _OLD
    routes: list[str] = [
        kept.cases_route,
        kept.check_route,
        kept.case_evaluation_route,
        kept.aggregate_route,
    ]
    assert all(f"/{_OLD}/" in route or route.endswith(f"/{_OLD}") for route in routes), routes
    assert not any(computed in route for route in routes)


def test_a_kept_revision_is_refused_by_name_once_the_exam_changes() -> None:
    """WHY: the pin stands for one exact fingerprint. The exam changed (another pin), so the
    revision computes to something else, and publishing the old id would hide that change
    under results recorded for a different exam."""

    before: str = _computed("kept-changed-plain", "exam=v1")
    after: str = _computed("kept-changed-plain-v2", "exam=v2")

    with pytest.raises(
        ValueError,
        match=(
            rf"inspect-kept-changed: kept_revision stands for {before} but the revision now "
            rf"computes to {after}; the exam changed"
        ),
    ):
        _assemble("kept-changed", "exam=v2", (_OLD, before))


def test_no_kept_revision_publishes_the_computed_revision() -> None:
    """Unset, nothing changes: the published revision is the computed one. (The pin never
    feeds the hash either: the first test assembles with it and still computes the value it
    stands for.) Every published row's literal is pinned in test_published_revisions."""

    computed: str = _computed("kept-unset-twin", "exam=v1")

    unset: ImportedBenchmark = _assemble("kept-unset", "exam=v1", None)

    assert unset.benchmark.revision == computed
    assert f"/{computed}/" in unset.aggregate_route or unset.aggregate_route.endswith(computed)


def test_only_rows_with_an_equivalence_proof_keep_a_revision() -> None:
    """INVARIANT: keeping a revision is a per-Benchmark owner decision backed by a golden that
    replays with zero misses, never a default. Any row joining this list is a new decision and
    must be named here with its proof in the PR."""

    keeping: dict[str, Any] = {
        spec.key: spec.kept_revision for spec in BENCHMARKS if spec.kept_revision is not None
    }

    # healthbench (OME-1527 row 20): the hand-built revisions, kept on the local Task.
    assert keeping == {
        "healthbench-worst30": ("39cfd96b068f7230", "f12c3e30661ea9d3"),
        "healthbench-professional": ("d8fb037307f35415", "44ddda05be338699"),
    }
