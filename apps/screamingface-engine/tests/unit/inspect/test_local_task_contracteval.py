# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""ContractEval as a LOCAL inspect Task (OME-1527) — the hand-built folder, moved.

What these tests pin, and why:

- conservation: on eight canned replies the Task grades every Case exactly as the hand-built
  checker did, and the run's headline equals the hand-built F1. The literals below were
  produced by running the hand-built folder end to end (prepare → check route → aggregate)
  on these replies before it was deleted, so "same exam, same score" is a test, not a promise;
- the prompt bytes: a synthetic row renders to a pinned literal, byte-identical to the
  hand-built `render_case_input` (all 4,182 real Cases were compared at import);
- the answer key survives Case Preparation as a list: `[]` on a no-clause Case (so only a
  decline is correct) and a one-span list on a keyed Case;
- the re-blessed golden: the hand-built golden's Delaware reply now lands as the plugin's
  Check, with the same verdict facts it carried in the old check record;
- the row: id `contracteval`, origin `screamingface`, the whole-run metric honoured.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import SampleScore, Score  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    _task_replay_pins,
    imported_benchmark,
)
from screamingface_engine_inspect.local_tasks.contracteval.contracteval import (  # noqa: E402
    contracteval_f1,
    record_to_sample,
)
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
    prepared_case,
)
from screamingface_engine_inspect.single_shot import benchmark_aggregate_async  # noqa: E402

_LAW: str = "This Agreement shall be governed by the laws of the State of Delaware."
_TERM: str = "The term of this Agreement is five (5) years."
_RENEW: str = "It renews automatically for successive one-year periods."

#: (gold clause sentences, the Candidate's reply) — eight Cases hand-written to fill every
#: confusion-matrix cell, with P != R so a precision/recall swap would show: three found
#: clauses (fenced, two spans with prose around them, bare), two missed (one of two spans
#: quoted; a decline on a Case that has a clause), two rightful declines (one shouting it
#: mid-sentence) and one quote where no clause exists.
_CASES: list[tuple[list[str], str]] = [
    ([_LAW], f"```\n{_LAW}\n```"),
    ([_TERM, _RENEW], f"Relevant: {_TERM} {_RENEW} That is all."),
    ([_TERM], _TERM),
    ([_TERM, _RENEW], _TERM),
    ([_LAW], "No related clause."),
    ([], "No related clause."),
    ([], "After review, NO RELATED CLAUSE applies here."),
    ([], _TERM),
]

#: What the hand-built checker recorded for each Case above (correct, is_positive, abstained,
#: jaccard), captured from `benchmarks/contracteval` at 72045115d before its deletion.
_HAND_BUILT_VERDICTS: list[tuple[bool, bool, bool, float]] = [
    (True, True, False, 1.0),
    (True, True, False, 0.8421052631578947),
    (True, True, False, 1.0),
    (False, True, False, 0.5625),
    (False, True, True, 0.0),
    (True, False, True, 0.0),
    (True, False, True, 0.0),
    (False, False, False, 0.0),
]

#: The hand-built aggregate's headline on these eight replies: TP 3, FN 2, TN 2, FP 1 →
#: precision 0.75, recall 0.6, F1 0.6667. (Its accuracy, the mean, was 0.625.)
_HAND_BUILT_F1: float = 0.6667


def _material(case_id: int, gold: list[str]) -> dict[str, Any]:
    """The Case's Grading Material as the real row prepares it, after its JSON round trip."""

    row: dict[str, Any] = {
        "id": f"Doc__Q{case_id}",
        "title": "Doc",
        "context": "Contract text.",
        "question": f"Q{case_id}?",
        "answers": {"text": gold, "answer_start": [0] * len(gold)},
    }
    sample: Sample = record_to_sample(row)
    case: PreparedCase = prepared_case(
        sample, case_id, str(sample.input), TASK_REPLAY_CASES["contracteval"]
    )
    return json.loads(json.dumps(case["grading_material"]))


def _request(case_id: int, gold: list[str], reply: str) -> GradeRequest:
    return GradeRequest(
        case_id=case_id,
        input=TextPayload(text="contract"),
        answer=TextPayload(text=reply),
        row={"case": {"status": "answered"}},
        material=_material(case_id, gold),
    )


async def _run(tmp_path: Path, cases: list[tuple[list[str], str]]) -> dict[str, Any]:
    """Grade one reply per Case through the plugin's own aggregate, whole-run metric included."""

    prepared: list[PreparedCase] = [
        {
            "case": {"id": index, "case_id": str(index), "input": f"contract {index}"},
            "grading_material": _material(index, gold),
        }
        for index, (gold, _) in enumerate(cases, start=1)
    ]
    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(index, reply) for index, (_, reply) in enumerate(cases, 1)])
    return await benchmark_aggregate_async(
        imported_benchmark("contracteval"), rows, tmp_path, case_ids=tuple(range(1, len(cases) + 1))
    )


# ── conservation: the hand-built grader's numbers, pinned as literals ─────────────────────


@pytest.mark.asyncio
async def test_each_case_is_graded_as_the_hand_built_checker_graded_it() -> None:
    hook = imported_benchmark("contracteval").aggregation().grade_case
    for case_id, ((gold, reply), expected) in enumerate(
        zip(_CASES, _HAND_BUILT_VERDICTS, strict=True), start=1
    ):
        outcome: CaseGradeOutcome = await hook(_request(case_id, gold, reply))
        correct, is_positive, abstained, overlap = expected
        evidence: dict[str, Any] = outcome.checks[0]["evidence"][0]["metadata"]
        assert outcome.failure_code is None, outcome.checks
        assert outcome.score == (1.0 if correct else 0.0), (case_id, reply)
        assert (evidence["is_positive"], evidence["abstained"]) == (is_positive, abstained)
        assert evidence["jaccard"] == pytest.approx(overlap, abs=1e-12)


@pytest.mark.asyncio
async def test_the_run_headline_is_the_hand_built_f1_not_the_mean(tmp_path: Path) -> None:
    """The headline guarantee: the same eight replies score 0.6667 here and in the hand-built
    Benchmark. The mean of the Case scores would be 0.625 — the number a row without the
    whole-run metric would have published."""

    result: dict[str, Any] = await _run(tmp_path, _CASES)

    assert result["score"] == _HAND_BUILT_F1
    assert result["coverage"] == 1.0
    assert result["metrics"] == {"correct": 5, "scored_cases": 8}


@pytest.mark.asyncio
async def test_always_declining_scores_zero_where_the_mean_would_be_0_375(tmp_path: Path) -> None:
    """The hand-built Benchmark's named deviation, kept: no true positive is F1 0.0 (the
    reference raises ZeroDivisionError), although declining is right on 3 of 8 Cases."""

    declined: list[tuple[list[str], str]] = [(gold, "No related clause.") for gold, _ in _CASES]

    result: dict[str, Any] = await _run(tmp_path, declined)

    assert result["score"] == 0.0
    assert result["metrics"] == {"correct": 3, "scored_cases": 8}


def test_the_metric_refuses_a_score_without_its_cell_facts() -> None:
    """WHY loud: a Score missing `is_positive` cannot be placed in the matrix; guessing would
    file it in the wrong cell with no failure anywhere. The tally names the metric."""

    # WHY Any: inspect's `Metric` protocol still types its argument as `list[Score]`, while
    # the metric (as inspect calls it) reads `SampleScore`s.
    compute: Any = contracteval_f1()
    with pytest.raises(KeyError, match="is_positive"):
        compute([SampleScore(score=Score(value=1.0), sample_id=1)])


@pytest.mark.asyncio
async def test_the_answer_key_survives_preparation_as_a_list() -> None:
    """R5 on the real row: a no-clause Case keeps `[]`, so only a decline is correct (a frozen
    "" would be a blank answer found in every reply); a one-span Case keeps its list of one."""

    assert _material(1, [])["target"] == []
    assert _material(2, [_LAW])["target"] == [_LAW]
    hook = imported_benchmark("contracteval").aggregation().grade_case
    quoted: CaseGradeOutcome = await hook(_request(1, [], _LAW))
    declined: CaseGradeOutcome = await hook(_request(2, [_LAW], "No related clause."))
    found: CaseGradeOutcome = await hook(_request(3, [_LAW], f"It says: {_LAW}"))
    assert (quoted.score, declined.score, found.score) == (0.0, 0.0, 1.0)


# ── the re-blessed golden ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_hand_built_golden_reply_lands_as_the_same_verdict() -> None:
    """The hand-built golden (revision f9a076a10a6ae4c6) pinned this reply's check record:
    correct, a clause Case, not declined, Jaccard 0.7. The record's bytes moved with the
    serving path (the plugin's Check replaces `contracteval-check.v1`); its facts did not."""

    gold: list[str] = ["This Agreement is governed by Delaware law."]
    hook = imported_benchmark("contracteval").aggregation().grade_case
    outcome: CaseGradeOutcome = await hook(
        _request(1, gold, "The clause reads: This Agreement is governed by Delaware law.")
    )

    check: Mapping[str, Any] = outcome.checks[0]
    assert outcome.score == 1.0
    assert check["outcome"] == "MET"
    assert check["evidence"][0]["metadata"] == {
        "value": 1.0,
        "answer": None,
        "is_positive": True,
        "abstained": False,
        "jaccard": 0.7,
    }


# ── the prompt bytes ──────────────────────────────────────────────────────────────────────


def test_a_row_renders_to_the_pinned_prompt_bytes() -> None:
    """INVARIANT: these bytes are Benchmark identity (they sit inside the Case Digest) and
    equal the hand-built Benchmark's; the literal below is the review act. Note `Context:`
    with no trailing space (the reference has one; the documented one-byte delta)."""

    sample: Sample = record_to_sample(
        {
            "id": "Doc__Governing Law",
            "title": "Doc",
            "context": "1. Governing Law. Delaware.",
            "question": "Which law governs?",
            "answers": {"text": ["Delaware."], "answer_start": [18]},
        }
    )
    assert sample.input == (
        "You are an assistant with strong legal knowledge, supporting senior lawyers by "
        "preparing reference materials.\n"
        "Given a Context and a Question, extract and return only the sentence(s) from the "
        "Context that directly address or relate to the Question.\n"
        "Do not rephrase or summarize in any way—respond with exact sentences from the Context "
        "relevant to the Question. If a relevant sentence contains unrelated elements such as "
        "page numbers or whitespace, include them exactly as they appear.\n"
        'If no part of the Context is relevant to the Question, respond with: "No related '
        'clause."\n'
        "\n"
        "Context:\n"
        "```\n"
        "1. Governing Law. Delaware.\n"
        "```\n"
        "Question:\n"
        "```\n"
        "Which law governs?\n"
        "```\n"
    )
    assert sample.target == ["Delaware."]
    assert sample.metadata == {"source_id": "Doc__Governing Law"}


# ── the row ───────────────────────────────────────────────────────────────────────────────


def test_the_row_keeps_the_hand_built_id_and_honours_its_own_f1() -> None:
    spec = next(row for row in BENCHMARKS if row.key == "contracteval")
    cases = TASK_REPLAY_CASES["contracteval"]
    benchmark = imported_benchmark("contracteval")
    assert benchmark.benchmark.id == "contracteval"  # the hand-built id, kept
    assert benchmark.benchmark.origin == "screamingface"
    assert provenance_gaps(benchmark.benchmark) == []
    assert spec.whole_run_metric is not None and spec.whole_run_metric.endswith(":contracteval_f1")
    assert spec.with_check_surface is False
    assert (cases.case_count, cases.empty_answer_key_allowed, cases.keep_sample_metadata) == (
        4182,
        True,
        True,
    )
    source = [pin for pin in _task_replay_pins(cases) if pin.startswith("task_source=")]
    assert len(source) == 1
