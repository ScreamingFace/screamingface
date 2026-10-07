# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A row's extra, named and dropped scorers are Benchmark identity (OME-1268, PR 3 of 5).

FEATURE: a Benchmark with several scorers declares them on its row (`scorer` stays the
Headline Score's scorer; `extra_scorers` the rest; `named_scores` the keys, headline
first; `dropped_scorers` any left out by name), and the three pin into the Revision.

INVARIANT: the pins exist only when set, so every published single-scorer Revision is
unchanged; assembly refuses a row whose names do not cover its scorers, or that both
drops and declares one scorer.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect import benchmarks, single_shot  # noqa: E402
from screamingface_engine_inspect.benchmarks import BenchmarkSpec  # noqa: E402


def _spec(**overrides: Any) -> BenchmarkSpec:
    """A SQuAD-shaped row on gsm8k's real Cases: inspect's f1 as the headline, exact beside."""

    values: dict[str, Any] = {
        "key": "gsm8k",  # reuses the real cases row; the benchmark caches are patched
        "title": "Named Scores Test Benchmark",
        "description": "test",
        "focus": "test",
        "dataset_url": "https://example.test/ds",
        "difficulty": "easy",
        "scorer": "inspect_ai.scorer:f1",
    }
    values.update(overrides)
    return BenchmarkSpec(**values)


def _assembled(spec: BenchmarkSpec, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(benchmarks, "BENCHMARKS", (spec,))
    monkeypatch.setattr(benchmarks, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    return benchmarks.imported_benchmark(spec.key)


def test_a_single_scorer_row_has_no_score_pins() -> None:
    # INVARIANT: the default row contributes nothing — test_published_revisions holds.
    assert benchmarks._named_score_pins(_spec()) == ()


def test_extra_scorers_pin_into_the_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    plain: str = str(_assembled(_spec(), monkeypatch).benchmark.revision)
    multi: str = str(
        _assembled(
            _spec(extra_scorers=("inspect_ai.scorer:exact",), named_scores=("f1", "exact")),
            monkeypatch,
        ).benchmark.revision
    )
    assert multi != plain


def test_a_dropped_scorer_pins_into_the_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    kept = _spec(extra_scorers=("inspect_ai.scorer:exact",), named_scores=("f1", "exact"))
    dropped = replace(kept, dropped_scorers=("expression_equivalance",))
    assert str(_assembled(kept, monkeypatch).benchmark.revision) != str(
        _assembled(dropped, monkeypatch).benchmark.revision
    )


def test_the_pins_name_every_declared_fact() -> None:
    pins = benchmarks._named_score_pins(
        _spec(
            extra_scorers=("inspect_ai.scorer:exact",),
            named_scores=("f1", "exact"),
            dropped_scorers=("expression_equivalance",),
        )
    )
    assert pins == (
        'extra_scorers=["inspect_ai.scorer:exact"]',
        'named_scores=["f1", "exact"]',
        'dropped_scorers=["expression_equivalance"]',
    )


def test_assembly_refuses_named_scores_that_do_not_cover_the_scorers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="named_scores"):
        _assembled(
            _spec(extra_scorers=("inspect_ai.scorer:exact",), named_scores=("f1",)), monkeypatch
        )


def test_assembly_refuses_extra_scorers_without_names(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="named_scores"):
        _assembled(_spec(extra_scorers=("inspect_ai.scorer:exact",)), monkeypatch)


def test_assembly_refuses_a_dropped_scorer_that_is_also_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="dropped_scorers"):
        _assembled(
            _spec(
                extra_scorers=("inspect_ai.scorer:exact",),
                named_scores=("f1", "exact"),
                dropped_scorers=("exact",),
            ),
            monkeypatch,
        )


def test_assembly_refuses_duplicate_or_blank_names(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="named_scores"):
        _assembled(
            _spec(extra_scorers=("inspect_ai.scorer:exact",), named_scores=("f1", "f1")),
            monkeypatch,
        )
    with pytest.raises(ValueError, match="named_scores"):
        _assembled(_spec(named_scores=("",)), monkeypatch)


@pytest.mark.asyncio
async def test_the_declared_scorers_reach_the_adapter_through_the_real_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row's extra scorer and names bind into the grading hook the aggregate runs."""

    assembled: Any = _assembled(
        _spec(extra_scorers=("inspect_ai.scorer:exact",), named_scores=("f1", "exact")), monkeypatch
    )
    hook = assembled.aggregation().grade_case
    outcome = await hook(
        GradeRequest(
            case_id=1,
            input=TextPayload(text="q"),
            answer=TextPayload(text="1889"),
            row={"case": {"status": "answered"}},
            material={"target": ["1889", "1887–1889"]},
        )
    )
    assert outcome.scores == {"f1": 1.0, "exact": 1.0}
    assert assembled.aggregation().named_scores == ("f1", "exact")
