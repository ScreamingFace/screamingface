# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""DRACO as a LOCAL inspect Task (OME-1527) — the hand-built folder, moved.

What these tests pin, and why:

- conservation: four canned Cases, each rubric line answered by a scripted judge once per
  pass, grade exactly as the hand-built grader graded them — the same Case scores, the same
  MET / UNMET per line and pass, the same lines left out of a pass, the same failed Case, the
  same headline. The literals were produced by driving the hand-built verdict parser and
  scoring (`verdict.build_evidence_record` → `case_results.valid_verdicts` →
  `group_by_judge_pass` → `scoring.score_case`, then `grade.draco_scorer`'s round-4 mean) on
  these replies at 3a1d9afbb, before the folder was deleted, so "same exam, same score" is a
  test. Where the hand-built grader saw one reply with no verdict, the script here repeats it
  on the two redraws, so both sides leave that line out of that pass;
- the one place the grader deliberately differs: a reply with no verdict is redrawn, and a
  redraw that parses counts (the hand-built grader dropped the line);
- the judge's wire: each call sends the paper's instructions as the system message and one
  criterion as the user message, to the same route with the same pinned params in the same
  order, then ``seed=<pass>`` — the hand-built judge request byte for byte, so the recorded
  draco-3pass golden still replays;
- the Candidate's prompt: the `problem` column untouched;
- the rows: ids `draco` and `draco-3pass`, origin `screamingface`, the judge pinned with a
  seed per pass, the retrieval policy declared, no Draft Feedback.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.request_scope import RequestScope, request_scope  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.local_tasks.draco.draco import (  # noqa: E402
    judge_criteria,
    record_to_sample,
)
from screamingface_engine_inspect.local_tasks.draco.prompts import JUDGE_SYSTEM  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
    prepared_case,
)
from screamingface_engine_inspect.single_shot import benchmark_aggregate_async  # noqa: E402
from url4.wire.subrequest import decode_subrequest_http, extract_expression_params  # noqa: E402

_MET: str = '{"explanation": "Present.", "criterion_status": "MET"}'
_UNMET: str = '{"explanation": "Absent.", "criterion_status": "UNMET"}'

#: Four Cases: (question, answer, rubric sections, replies). Each rubric line is
#: (id, weight, requirement); its replies are one list per pass, in draw order. A pass whose
#: first reply has no verdict repeats it on both redraws (see the module doc). They cover a
#: fenced and a prose-prefixed reply; a met penalty (Cases 1 and 3, the second clamped to 0);
#: a pass with no verdict BETWEEN two valid ones, which scores 0 (Case 2); a reply missing its
#: explanation, left out of its pass (Case 3); and a Case with no verdict at all (Case 4).
_CASES: list[tuple[str, str, list[tuple[str, list[tuple[str, int, str]]]], dict[str, Any]]] = [
    (
        "Compare TWFE and Callaway-Sant'Anna for case-1.",
        "Report one.",
        [
            ("factual-accuracy", [("c1-a", 3, "States the TWFE weights.")]),
            (
                "completeness",
                [("c1-b", 1, "Covers staggered timing."), ("c1-c", -2, "Claims TWFE is unbiased.")],
            ),
        ],
        {
            "c1-a": [
                [_MET],
                [_MET],
                ['```json\n{"explanation": "Yes.", "criterion_status": "MET"}\n```'],
            ],
            "c1-b": [
                [_UNMET],
                [_MET],
                ['Verdict follows.\n{"explanation": "Missing.", "criterion_status": "UNMET"}'],
            ],
            "c1-c": [[_UNMET], [_MET], [_MET]],
        },
    ),
    (
        "Summarise the 2025 rate decision for case-2.",
        "Report two.",
        [("factual-accuracy", [("c2-a", 2, "Names the new rate.")])],
        {"c2-a": [[_MET], ["maybe", "maybe", "maybe"], [_MET]]},
    ),
    (
        "Advise on the dosage for case-3.",
        "Report three.",
        [
            (
                "factual-accuracy",
                [("c3-a", 1, "Cites the label."), ("c3-b", -5, "Recommends a double dose.")],
            )
        ],
        {
            "c3-a": [[_MET], [_MET], [_UNMET]],
            "c3-b": [[_MET], [_UNMET], ['{"criterion_status": "MET"}'] * 3],
        },
    ),
    (
        "List the treaty signatories for case-4.",
        "Report four.",
        [("completeness", [("c4-a", 4, "Lists all signatories.")])],
        {"c4-a": [[""] * 3, ["no idea"] * 3, ["```json\n{}\n```"] * 3]},
    ),
]

#: What the hand-built grader recorded for each Case above: its score and, per line and pass,
#: MET (True) or UNMET (False) for the verdicts it accepted — a missing key is a line left out
#: of that pass; None for Case 4, which it failed (`judge_reply_invalid`, no valid verdict).
#: Captured from `benchmarks/draco` at 3a1d9afbb before its deletion.
_HAND_BUILT: list[tuple[float, dict[str, bool]] | None] = [
    (
        0.5,
        {
            "c1-a#1": True,
            "c1-a#2": True,
            "c1-a#3": True,
            "c1-b#1": False,
            "c1-b#2": True,
            "c1-b#3": False,
            "c1-c#1": False,
            "c1-c#2": True,
            "c1-c#3": True,
        },
    ),
    (0.6667, {"c2-a#1": True, "c2-a#3": True}),
    (
        0.3333,
        {"c3-a#1": True, "c3-a#2": True, "c3-a#3": False, "c3-b#1": True, "c3-b#2": False},
    ),
    None,
]

#: The hand-built headline over the three graded Cases: round((0.5 + 0.6667 + 0.3333) / 3, 4).
_HAND_BUILT_HEADLINE: float = 0.5

#: The hand-built judge route and its JUDGE_PARAMS, in wire order; each pass adds its seed.
_JUDGE_ROUTE: str = "/openrouter/google/gemini-3.1-pro-preview"
_JUDGE_PARAMS: list[tuple[str, str]] = [
    ("web_search", "false"),
    ("temperature", "0.2"),
    ("reasoning_effort", "low"),
    ("max_tokens", "4096"),
]

#: sha256 of the hand-built judge instruction bytes as the gateway received them (its url4
#: intent, `$$` unescaped), computed from `benchmarks/draco/prompts.py` at 3a1d9afbb.
_HAND_BUILT_SYSTEM_SHA256: str = "09f62367cbd70e8c62cc12ae2104732a55022cf3c51a08e72db210746c983a67"


def _rubric(sections: list[tuple[str, list[tuple[str, int, str]]]]) -> dict[str, Any]:
    """The dataset's rubric JSON for one canned Case."""

    return {
        "sections": [
            {
                "id": axis,
                "criteria": [
                    {"id": criterion_id, "weight": weight, "requirement": requirement}
                    for criterion_id, weight, requirement in criteria
                ],
            }
            for axis, criteria in sections
        ]
    }


class _ScriptedJudge:
    """A fake node fetch standing in for the gateway judge: answers each line's pass from its
    script, in draw order, and keeps every call's decoded (path, params, messages).

    WHY keyed by requirement and seed, not call order: the aggregate grades several Cases at
    once, so their calls interleave. It simulates the judge's replies only; whether a real judge
    would answer so is not what these tests prove."""

    def __init__(self) -> None:
        self.scripts: dict[tuple[str, int], list[str]] = {
            (requirement, judge_pass): list(replies[criterion_id][judge_pass - 1])
            for _, _, sections, replies in _CASES
            for _, criteria in sections
            for criterion_id, _, requirement in criteria
            for judge_pass in (1, 2, 3)
        }
        self.calls: list[tuple[str, list[tuple[str, str]], list[dict[str, str]], str]] = []

    async def __call__(self, target: str) -> str:
        path, _, query = target.partition("?")
        params, q = extract_expression_params(query)
        assert q is not None
        context, intent = decode_subrequest_http(q)
        messages: list[dict[str, str]] = json.loads(context)["messages"]
        self.calls.append((path, list(params.items()), messages, intent))
        requirement: str = messages[1]["content"].split(" ")[4]
        return self.scripts[(requirement, int(params["seed"]))].pop(0)


@pytest.fixture
def judge() -> Iterator[_ScriptedJudge]:
    """The scripted judge, bound as draco-3pass's judge with its pinned params and a seed per
    pass, inside a run's request scope (a redraw rebinds that scope to leave the cache)."""

    scripted: _ScriptedJudge = _ScriptedJudge()
    spec = imported_benchmark("draco-3pass").judge
    assert spec is not None
    transport = JudgeTransport(
        fetch=scripted,
        params=spec.params,
        benchmark_id="draco-3pass",
        seed_per_pass=spec.seed_per_pass,
    )
    with request_scope(RequestScope(origin="run")), bound_judge_transport(transport):
        yield scripted


def _material(index: int) -> dict[str, Any]:
    """Case ``index``'s Grading Material as the real row prepares it, after its JSON round trip."""

    question, _, sections, _ = _CASES[index - 1]
    row: dict[str, Any] = {
        "problem": question,
        "answer": json.dumps(_rubric(sections)),
        "domain": "Academic",
    }
    sample: Sample = record_to_sample(row, index)
    case: PreparedCase = prepared_case(
        sample, index, str(sample.input), TASK_REPLAY_CASES["draco-3pass"]
    )
    return json.loads(json.dumps(case["grading_material"]))


async def _grade(index: int) -> CaseGradeOutcome:
    """Grade canned Case ``index`` through draco-3pass's real per-Case grading hook."""

    question, answer, _, _ = _CASES[index - 1]
    hook = imported_benchmark("draco-3pass").aggregation().grade_case
    return await hook(
        GradeRequest(
            case_id=index,
            input=TextPayload(text=question),
            answer=TextPayload(text=answer),
            row={"case": {"status": "answered"}},
            material=_material(index),
        )
    )


# ── conservation: the hand-built grader's numbers, pinned as literals ─────────────────────


@pytest.mark.asyncio
async def test_each_case_is_graded_as_the_hand_built_grader_graded_it(
    judge: _ScriptedJudge,
) -> None:
    """Score and per-pass verdicts, Case by Case: a line with no verdict in a pass is left out
    of that pass, as the hand-built grader left it out, and is never counted as UNMET."""

    for index, expected in enumerate(_HAND_BUILT, start=1):
        outcome: CaseGradeOutcome = await _grade(index)
        if expected is None:
            # The hand-built grader failed it too; the plugin names the judge as the cause.
            assert outcome.failure_code == "judge_reply_invalid", outcome.checks
            assert outcome.score is None
            continue
        score, verdicts = expected
        metadata: dict[str, Any] = outcome.checks[0]["evidence"][0]["metadata"]
        assert outcome.failure_code is None, outcome.checks
        assert outcome.score == score, index
        accepted: dict[str, bool] = {
            f"{item['id']}#{verdict['pass']}": verdict["met"]
            for item in metadata["items"]
            for verdict in item["verdicts"]
            if verdict["valid"]
        }
        assert accepted == verdicts, index


@pytest.mark.asyncio
async def test_the_run_headline_is_the_hand_built_mean(
    tmp_path: Path, judge: _ScriptedJudge
) -> None:
    """The headline guarantee: the same replies score 0.5 here and in the hand-built Benchmark —
    the round-4 mean over the three graded Cases; the Case whose judge never gave a verdict is
    left out of the mean and counted against coverage, never scored 0."""

    prepared: list[PreparedCase] = [
        {
            "case": {"id": index, "case_id": str(index), "input": question},
            "grading_material": _material(index),
        }
        for index, (question, _, _, _) in enumerate(_CASES, start=1)
    ]
    _write_cases(prepared, tmp_path)
    rows: str = json.dumps(
        [_row(index, answer) for index, (_, answer, _, _) in enumerate(_CASES, start=1)]
    )

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("draco-3pass"), rows, tmp_path, case_ids=(1, 2, 3, 4)
    )

    assert result["score"] == _HAND_BUILT_HEADLINE
    assert result["metrics"]["scored_cases"] == 3
    codes: list[str] = [failure["code"] for case in result["cases"] for failure in case["failures"]]
    assert codes == ["judge_reply_invalid"]


# ── the one deliberate difference: a reply with no verdict is redrawn ─────────────────────


@pytest.mark.asyncio
async def test_a_redraw_that_parses_counts_where_the_hand_built_grader_dropped_the_line(
    judge: _ScriptedJudge,
) -> None:
    """Case 2's middle pass first answers "maybe". The hand-built grader asked once and left the
    line out of that pass (score 0.6667); the redraw asks again, outside the gateway cache, and
    a verdict on the redraw is that pass's verdict (score 1.0)."""

    judge.scripts[("Names the new rate.", 2)] = ["maybe", _MET]

    outcome: CaseGradeOutcome = await _grade(2)

    assert outcome.score == 1.0
    assert outcome.checks[0]["evidence"][0]["metadata"]["judge_redraws"] == 1


@pytest.mark.asyncio
async def test_an_empty_middle_pass_scores_zero_but_an_empty_last_pass_drops_out(
    judge: _ScriptedJudge,
) -> None:
    """WHY pinned: which pass the judge failed changes the score, as it did in the hand-built
    grader (its run list stopped at the last valid pass). Case 2 has one line, MET in two
    passes; with no verdict in pass 2 the empty pass still counts and scores 0 → 2/3, with no
    verdict in pass 3 it drops out → 1.0. Whether an empty pass should count as missing
    wherever it sits is an open owner call; this test turns red the day it is decided."""

    middle: CaseGradeOutcome = await _grade(2)
    # The first grading drew every scripted reply; re-script all three passes for the second.
    judge.scripts[("Names the new rate.", 1)] = [_MET]
    judge.scripts[("Names the new rate.", 2)] = [_MET]
    judge.scripts[("Names the new rate.", 3)] = ["maybe"] * 3

    last: CaseGradeOutcome = await _grade(2)

    assert middle.score == 0.6667
    assert last.score == 1.0


# ── the judge's wire ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_judge_call_is_the_hand_built_one(judge: _ScriptedJudge) -> None:
    """Same route, same pinned params in the same order, then the pass's seed; the paper's
    instructions as the system message and one criterion as the user message, both in the
    hand-built bytes (U+2028 between fields and for the instructions' line breaks)."""

    await _grade(3)

    # Two lines, three passes each, and two redraws of the line whose pass-3 reply never
    # carries an explanation: every redraw keeps its pass's seed.
    assert [params[-1] for _, params, _, _ in judge.calls] == [
        ("seed", seed) for seed in ("1", "2", "3", "1", "2", "3", "3", "3")
    ]
    for path, params, messages, intent in judge.calls:
        assert path == _JUDGE_ROUTE
        assert params[:-1] == _JUDGE_PARAMS
        assert intent == ""
        assert messages[0] == {"role": "system", "content": JUDGE_SYSTEM}
    assert hashlib.sha256(JUDGE_SYSTEM.encode()).hexdigest() == _HAND_BUILT_SYSTEM_SHA256
    penalty: list[dict[str, str]] = next(
        messages for _, _, messages, _ in judge.calls if "double dose" in messages[1]["content"]
    )
    assert penalty[1] == {
        "role": "user",
        "content": (
            "<criterion_type> negative </criterion_type> "
            "<criterion> Recommends a double dose. </criterion> "
            "<query> Advise on the dosage for case-3. </query> "
            "<response> Report three. </response>"
        ),
    }


# ── the Candidate's prompt and the judge's view of the rubric ─────────────────────────────


def test_a_row_renders_to_the_untouched_question_and_its_private_rubric() -> None:
    """INVARIANT: the input is the `problem` column byte for byte (the hand-built `cases.json`
    input; all 100 real Cases were compared at import: 0 differ, nor their rubrics), and the
    judge sees each line's sign as its type, never its weight."""

    rubric: dict[str, Any] = _rubric([("axis", [("a", 2, "Does X."), ("b", -1, "Claims Y.")])])
    sample: Sample = record_to_sample(
        {"problem": "  Research Q?\n", "answer": json.dumps(rubric), "domain": None}, 7
    )

    assert (sample.id, sample.input, sample.target) == (7, "  Research Q?\n", "")
    assert sample.metadata == {"domain": "unknown", "rubric": rubric}
    assert judge_criteria(rubric) == [
        {"id": "a", "requirement": "Does X.", "criterion_type": "positive"},
        {"id": "b", "requirement": "Claims Y.", "criterion_type": "negative"},
    ]


# ── the rows ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("key", "passes"), [("draco", 5), ("draco-3pass", 3)])
def test_the_rows_keep_the_hand_built_ids_judge_policy_and_declaration(
    key: str, passes: int
) -> None:
    spec = next(row for row in BENCHMARKS if row.key == key)
    cases = TASK_REPLAY_CASES[key]
    benchmark = imported_benchmark(key)
    assert benchmark.benchmark.id == key  # the hand-built id, kept
    assert benchmark.benchmark.origin == "screamingface"
    assert provenance_gaps(benchmark.benchmark) == []
    assert spec.scorer_kwargs["judge_passes"] == passes
    assert spec.judge is not None and spec.judge.model == _JUDGE_ROUTE.removeprefix("/")
    assert list(spec.judge.params) == _JUDGE_PARAMS
    assert spec.judge.seed_per_pass is True
    assert spec.retrieval_policy is not None
    assert spec.retrieval_policy.policy_id == "draco/reproduction"
    assert len(spec.retrieval_policy.excluded_domains) == 7
    assert spec.with_check_surface is False and spec.whole_run_metric is None
    assert spec.candidate_input_envelope is False  # the hand-built input was plain text
    assert (cases.case_count, cases.has_answer_key, cases.keep_sample_metadata) == (
        100,
        False,
        True,
    )
