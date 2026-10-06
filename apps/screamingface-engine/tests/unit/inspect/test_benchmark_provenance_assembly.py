"""An imported row's provenance reaches the assembled Benchmark untouched (OME-1455, box ②/③).

FEATURE: Benchmark Provenance on Imported Benchmarks.
WHY a separate file from test_benchmark_provenance.py: this one needs the inspect extra,
because it assembles a real row through the plugin's own `_assemble`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.provenance import (  # noqa: E402
    FrontierScore,
    HumanBaseline,
    NotPublished,
)
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    _assemble,
    imported_benchmark,
)

_PAPER = "https://arxiv.org/abs/2110.14168"
_HARNESS = "https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/gsm8k"


def _gsm8k_row() -> BenchmarkSpec:
    return next(spec for spec in BENCHMARKS if spec.key == "gsm8k")


def test_a_row_with_provenance_assembles_into_a_benchmark_that_serves_it() -> None:
    # The row is the Imported Benchmark's one authoring site (the OME-1257 rule for
    # difficulty), so every provenance field is a row field, threaded through verbatim.
    row = replace(
        _gsm8k_row(),
        paper_url=_PAPER,
        authors="Cobbe et al., 2021",
        citation="@article{cobbe2021gsm8k}",
        inspect_contributors=("jjallaire",),
        harness_url=_HARNESS,
        license="MIT",
        human_baseline=NotPublished(reason="the paper reports no human study"),
        frontier_score=FrontierScore(score=0.97, model="m", source_url=_PAPER, as_of="2026-09"),
        notebook="12_inspect_evals_benchmarks",
        upstream_case_count=1319,
    )

    benchmark = _assemble(row).benchmark
    entry = benchmark.catalog_entry()

    assert benchmark.paper_url == _PAPER
    assert benchmark.inspect_contributors == ("jjallaire",)
    assert benchmark.human_baseline == NotPublished(reason="the paper reports no human study")
    assert entry["authors"] == "Cobbe et al., 2021"
    assert entry["inspect_contributors"] == ["jjallaire"]
    assert entry["harness_url"] == _HARNESS
    frontier = entry["frontier_score"]
    assert isinstance(frontier, dict) and frontier["score"] == 0.97
    assert entry["saturation"] == "saturated"
    assert "human_baseline" not in entry


def test_provenance_on_a_row_never_moves_the_published_revision() -> None:
    # INVARIANT (F6): the §6 revision hashes the pinned packages, the dataset pins and the
    # protocol constants; a provenance edit on the row must leave every recorded Leaderboard
    # Score attached. test_published_revisions.py pins the literal; this pins the invariance.
    plain = imported_benchmark("gsm8k").benchmark.revision
    with_provenance = _assemble(
        replace(
            _gsm8k_row(),
            paper_url=_PAPER,
            human_baseline=HumanBaseline(score=0.9, source_url=_PAPER),
            upstream_case_count=1319,
        )
    ).benchmark.revision

    assert with_provenance == plain


def test_the_upstream_case_count_stays_on_the_row() -> None:
    # WHY not a Benchmark field: it is inspect's declared size, the thing the conformance
    # test compares `case_count` against (spec §3.1), not a fact the catalogue serves.
    row = replace(_gsm8k_row(), upstream_case_count=1319)

    benchmark = _assemble(row).benchmark

    assert row.upstream_case_count == 1319
    assert "upstream_case_count" not in benchmark.catalog_entry()


def _declares_a_size_deviation(cases_spec: object) -> bool:
    """A Named Deviation that changes the Case count: a question filter or excluded Samples."""

    return bool(
        getattr(cases_spec, "question_filter_task_args", None)
        or getattr(cases_spec, "excluded_sample_ids", None)
    )


@pytest.mark.parametrize(
    "spec",
    [spec for spec in BENCHMARKS if spec.upstream_case_count is not None],
    ids=lambda spec: spec.key,
)
def test_the_case_count_matches_inspects_declared_size_unless_a_deviation_is_named(
    spec: BenchmarkSpec,
) -> None:
    # F2 (spec §3.1): inspect's `dataset_samples` is written on the row by the importer; a
    # Benchmark whose Case count differs is a different exam than inspect says, unless its
    # Cases declaration names the deviation (a question filter, excluded Samples). It runs
    # here in CI, never at Engine boot, so a metadata mismatch cannot take the Engine down.
    from screamingface_engine_inspect.benchmarks import _cases_declaration

    benchmark = imported_benchmark(spec.key).benchmark
    if benchmark.case_count == spec.upstream_case_count:
        return
    assert _declares_a_size_deviation(_cases_declaration(spec.key)), (
        f"{spec.key}: inspect declares {spec.upstream_case_count} Samples, the Benchmark has "
        f"{benchmark.case_count} Cases, and the row names no deviation"
    )
