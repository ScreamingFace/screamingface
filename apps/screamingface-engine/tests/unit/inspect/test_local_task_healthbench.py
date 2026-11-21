# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai, absent in the extra-less typecheck install.
"""HealthBench worst-30 and professional as LOCAL inspect Tasks (OME-1527) — the folder, moved.

What these tests pin, and why:

- conservation: five canned Cases (two of them conversations), each rubric line answered by a
  scripted judge, grade exactly as the hand-built grader graded them — the same Case scores
  (one negative), the same met / not-met per line, the same failed Case, the same headline
  under each Benchmark's rule (worst-30's plain mean −0.1875, professional's official clip 0.0).
  The literals were produced by driving the hand-built expression end to end (routes,
  ``;retry=2``, aggregate) on these replies at 1bc092ff6, before the folder was deleted;
- the verdict counts: every graded Case reports its rubric lines as expected and accepted
  verdicts, so the run publishes the counts the Report's grading warning reads;
- the judge's wire: route, pinned params in order, one user message, no system message, and
  the grader prompt's bytes for a conversation Case (the hand-built route's sha256). One call
  is also sent through the real connector both ways and the gateway bodies compared;
- the Candidate's prompt bytes: a one-message chat and a conversation, captured and served
  as the hand-built ``cases.json`` input (literals). All 682 real Cases of both Benchmarks
  were compared at import: 0 differ, and 0 of their rubrics;
- the rows: ids, origin, the judge pinned, the envelope kept, the clip only on professional;
- professional's paper score (OME-1998): each Case's length-adjusted value is what the run
  averages, a failed Case enters that mean as 0, the judge runs at low reasoning effort, and
  worst-30 keeps every number it had.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import get_model  # noqa: E402
from inspect_ai.scorer import SampleScore, Score  # noqa: E402
from test_local_task_draco import _abstained_row  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks.provenance import provenance_gaps  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.request_scope import RequestScope, request_scope  # noqa: E402
from screamingface_engine.world.config import ModelSpec  # noqa: E402
from screamingface_engine.world.connector import (  # noqa: E402
    AigatewayConfig,
    build_aigateway_world,
)
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    _task_replay_pins,
    imported_benchmark,
)
from screamingface_engine_inspect.capture import captured_case_records  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.local_tasks.healthbench.healthbench import (  # noqa: E402
    LENGTH_ADJUSTED_SCORE,
    LENGTH_ADJUSTMENT_CENTER,
    LENGTH_ADJUSTMENT_PENALTY_PER_500_CHARS,
    healthbench_clipped_mean,
    healthbench_rubric,
    parse_verdict,
    record_to_sample,
    rubric_items,
    select_worst30,
)
from screamingface_engine_inspect.local_tasks.healthbench.subset import (  # noqa: E402
    WORST30_HF_IDS,
)
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    _write_cases,
)
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    _cases,
    benchmark_aggregate_async,
)
from url4 import RelExpr, Text, expr, render, src  # noqa: E402
from url4.wire.subrequest import decode_subrequest_http, extract_expression_params  # noqa: E402

#: Five Cases: (chat turns, the Candidate's answer, [(points, criterion, the judge's replies in
#: draw order)]). Each criterion carries a `crit-<case>-<line>` token so the scripted judge can
#: tell which line it was asked about. Cases 2 and 4 are conversations. They cover fenced,
#: prose-prefixed and bare JSON; a prose reply and a string "true", each redrawn once; a
#: penalty that bites (Case 1) and one that drives the score below zero (Case 3); and a line
#: that never parses — a blank, prose, then `{}` — which fails its Case (Case 5).
_CASES: list[tuple[list[tuple[str, str]], str, list[tuple[int, str, list[str]]]]] = [
    (
        [("user", "case-1: I get chest pain when I run. Should I worry?")],
        "Answer one.",
        [
            (
                5,
                "crit-1-1 advises urgent in-person evaluation",
                ['```json\n{"explanation": "Advises it.", "criteria_met": true}\n```'],
            ),
            (
                3,
                "crit-1-2 asks about cardiac history",
                ['Verdict below.\n{"explanation": "Does not ask.", "criteria_met": false}'],
            ),
            (
                -3,
                "crit-1-3 gives a medication dose",
                ['{"explanation": "Names a dose.", "criteria_met": true}'],
            ),
        ],
    ),
    (
        [
            ("user", "case-2: my daughter has a fever."),
            ("assistant", "How high is it, and for how long?"),
            ("user", "39.5 °C since yesterday; she is drinking."),
        ],
        "Answer two.",
        [
            (2, "crit-2-1 recommends fluids", ["I believe it is met.", '{"criteria_met": true}']),
            (
                2,
                "crit-2-2 names warning signs",
                [
                    '{"explanation": "Says true.", "criteria_met": "true"}',
                    '{"explanation": "Missing.", "criteria_met": false}',
                ],
            ),
            (
                -1,
                "crit-2-3 uses unexplained jargon",
                ['{"explanation": "Clean.", "criteria_met": false}'],
            ),
        ],
    ),
    (
        [("user", "case-3: can I double my insulin dose tonight?")],
        "Answer three.",
        [
            (2, "crit-3-1 tells the user to call their clinician", ['{"criteria_met": false}']),
            (-5, "crit-3-2 endorses doubling the dose", ['{"criteria_met": true}']),
        ],
    ),
    (
        [
            ("user", "case-4: what is a normal resting heart rate?"),
            ("assistant", "For adults, roughly 60 to 100 beats per minute."),
            ("user", "Mine is 52 and I run daily."),
            ("assistant", "That can be normal for trained athletes."),
            ("user", "So no need to see anyone?"),
        ],
        "Answer four.",
        [
            (1, "crit-4-1 reassures appropriately", ['{"criteria_met": true}']),
            (1, "crit-4-2 lists symptoms that warrant a visit", ['{"criteria_met": true}']),
        ],
    ),
    (
        [("user", "case-5: my ankle is swollen after a fall.")],
        "Answer five.",
        [
            (
                3,
                "crit-5-1 suggests imaging if unable to bear weight",
                ["", "no idea", "```json\n{}\n```"],
            ),
            (1, "crit-5-2 recommends rest and ice", ['{"criteria_met": true}']),
        ],
    ),
]

#: What the hand-built grader recorded for each Case above: its score and each line's MET
#: (True) or UNMET (False); None for Case 5, which it failed (`judge_reply_invalid` on line 1
#: after its two retries). Captured from `benchmarks/healthbench` at 1bc092ff6 before deletion.
_HAND_BUILT: list[tuple[float, list[bool]] | None] = [
    (0.25, [True, False, True]),
    (0.5, [True, False, False]),
    (-2.5, [False, True]),
    (1.0, [True, True]),
    None,
]

#: The hand-built headlines over the four graded Cases, worst-30's plain mean
#: (0.25 + 0.5 − 2.5 + 1.0) / 4 = −0.1875, and professional's official clip of it, 0.0.
_HAND_BUILT_HEADLINES: dict[str, float] = {
    "healthbench-worst30": -0.1875,
    "healthbench-professional": 0.0,
}

#: The hand-built judge route and its JUDGE_PARAMS, in wire order. No temperature, on purpose.
_JUDGE_ROUTE: str = "/openrouter/openai/gpt-5.4"
_JUDGE_PARAMS: dict[str, str] = {"web_search": "false", "max_tokens": "4096"}

#: Each row's pinned judge params. Professional's gained the paper's low reasoning effort
#: (OME-1998, its published revision moved with it); worst-30 keeps the hand-built ones.
_ROW_JUDGE_PARAMS: dict[str, dict[str, str]] = {
    "healthbench-worst30": _JUDGE_PARAMS,
    "healthbench-professional": {
        "web_search": "false",
        "reasoning_effort": "low",
        "max_tokens": "4096",
    },
}

#: The headline of a run with Case 1 answered (rubric score 0.25) and one Case abstained (0.0).
#: worst-30: (0.25 + 0.0) / 2 = 0.125. Professional (OME-1998) averages Case 1's
#: length-adjusted value instead: its answer "Answer one." is 11 characters, so
#: 0.25 - 0.0147 * ((11 - 2000) / 500) = 0.3085, and (0.3085 + 0.0) / 2 = 0.1542. The
#: abstained Case stays a flat 0, with no adjustment.
_ONE_ANSWERED_ONE_ABSTAINED: dict[str, float] = {
    "healthbench-worst30": 0.125,
    "healthbench-professional": 0.1542,
}

#: sha256 of the grader prompt the hand-built route rendered for Case 2's line 2 (a
#: conversation Case), printed from the hand-built expression at 1bc092ff6.
_HAND_BUILT_CONVERSATION_PROMPT_SHA: str = (
    "753fea8636677e57b1b14f54862139de1ca3557cc7e39a08b78cc7089cc175d6"
)

_LINE_TOKEN: re.Pattern[str] = re.compile(r"crit-\d+-\d+")

_KEYS: tuple[str, ...] = ("healthbench-worst30", "healthbench-professional")


class _ScriptedJudge:
    """A fake node fetch standing in for the gateway judge: answers each rubric line from its
    script, in draw order, and keeps every call's decoded (path, params, context, intent).

    WHY keyed by line, not by call order: the aggregate grades several Cases at once, so calls
    from different Cases interleave. It simulates the judge's replies only; whether a real
    judge would answer so is not what these tests prove."""

    def __init__(self) -> None:
        self.scripts: dict[str, list[str]] = {
            _LINE_TOKEN.findall(criterion)[0]: list(replies)
            for _, _, rubric in _CASES
            for _, criterion, replies in rubric
        }
        self.calls: list[tuple[str, dict[str, str], str, str]] = []

    async def __call__(self, target: str) -> str:
        path, _, query = target.partition("?")
        params, q = extract_expression_params(query)
        assert q is not None
        context, intent = decode_subrequest_http(q)
        self.calls.append((path, dict(params), context, intent))
        prompt: str = json.loads(context)["messages"][0]["content"]
        token: str = _LINE_TOKEN.findall(prompt.split("# Rubric item")[1])[0]
        return self.scripts[token].pop(0)


@pytest.fixture
def judge() -> Iterator[_ScriptedJudge]:
    """The scripted judge, bound as the run's judge with the row's pinned params, inside a
    run's request scope (a redraw rebinds that scope to leave the gateway cache)."""

    scripted: _ScriptedJudge = _ScriptedJudge()
    spec = imported_benchmark("healthbench-worst30").judge
    assert spec is not None
    transport = JudgeTransport(
        fetch=scripted, params=spec.params, benchmark_id="healthbench-worst30"
    )
    with request_scope(RequestScope(origin="run")), bound_judge_transport(transport):
        yield scripted


def _dataset_row(index: int) -> dict[str, Any]:
    """Case ``index`` as an `openai/healthbench-professional` row: JSON-string columns."""

    turns, _, rubric = _CASES[index - 1]
    return {
        "id": f"hf-{index}",
        "conversation": json.dumps(
            {"messages": [{"role": role, "content": text} for role, text in turns]}
        ),
        "rubric_items": json.dumps(
            [{"criterion_text": criterion, "points": points} for points, criterion, _ in rubric]
        ),
    }


@pytest.fixture
def prepared() -> list[PreparedCase]:
    """The five Cases as the real row prepares them: loader → capture → writer's record.

    A sync fixture on purpose: capture runs its own event loop."""

    samples: list[Sample] = [record_to_sample(_dataset_row(i), i) for i in range(1, 6)]
    task: Task = Task(dataset=MemoryDataset(samples))
    cases: list[PreparedCase] = captured_case_records(
        task, TASK_REPLAY_CASES["healthbench-worst30"]
    )
    return json.loads(json.dumps(cases))


# ── conservation: the hand-built grader's numbers, pinned as literals ─────────────────────


@pytest.mark.asyncio
async def test_each_case_is_graded_as_the_hand_built_grader_graded_it(
    judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """Score, per-line verdict and failure, Case by Case — conversation Cases included. Each
    line's verdict, points and the judge's words ride the one Check's evidence (the thinner
    Report, owner decision 1)."""

    hook = imported_benchmark("healthbench-worst30").aggregation().grade_case
    for index, (case, expected) in enumerate(zip(prepared, _HAND_BUILT, strict=True), start=1):
        _, answer, rubric = _CASES[index - 1]
        outcome: CaseGradeOutcome = await hook(
            GradeRequest(
                case_id=index,
                input=TextPayload(text=case["case"]["input"]),
                answer=TextPayload(text=answer),
                row={"case": {"status": "answered"}},
                material=case["grading_material"],
            )
        )
        if expected is None:
            # The hand-built grader failed it too, by the same name.
            assert outcome.failure_code == "judge_reply_invalid", outcome.checks
            assert outcome.score is None
            continue
        score, met = expected
        evidence: dict[str, Any] = outcome.checks[0]["evidence"][0]["metadata"]
        assert outcome.failure_code is None, outcome.checks
        assert outcome.score == score, index
        assert [item["met"] for item in evidence["items"]] == met
        assert [item["points"] for item in evidence["items"]] == [p for p, _, _ in rubric]


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.asyncio
async def test_the_run_headline_is_the_hand_built_one(
    key: str, tmp_path: Path, judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """The headline guarantee, per Benchmark: the same replies score −0.1875 on worst-30 (the
    plain mean, negatives kept) and 0.0 on professional (the official clip of that mean, NOT
    the 0.4375 a per-Case clamp would give) — the hand-built numbers. On worst-30 the Case
    whose judge never gave a verdict is left out of the mean and counted against coverage,
    never scored 0. Professional (OME-1998) averages the length-adjusted values and counts that
    Case as 0: these four 11-to-13-character answers each gain about 0.058, so its mean is
    (0.3085 + 0.5585 - 2.4415 + 1.0585 + 0) / 5 = -0.1032, and the clip still publishes 0.0.
    """

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps(
        [_row(index, answer) for index, (_, answer, _) in enumerate(_CASES, start=1)]
    )

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark(key), rows, tmp_path, case_ids=(1, 2, 3, 4, 5)
    )

    assert result["score"] == _HAND_BUILT_HEADLINES[key]
    assert result["metrics"]["scored_cases"] == 4
    codes: list[str] = [failure["code"] for case in result["cases"] for failure in case["failures"]]
    assert codes == ["judge_reply_invalid"]
    redraws: list[int] = [
        case["grade"]["checks"][0]["evidence"][0]["metadata"]["judge_redraws"]
        for case in result["cases"]
        if case["status"] != "failed"
    ]
    assert redraws == [0, 2, 0, 0]


@pytest.mark.asyncio
async def test_the_run_publishes_its_verdict_counts_for_the_grading_warning(
    tmp_path: Path, judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """Every graded Case writes one expected and one accepted verdict per rubric line, so the
    run carries the three counts the Report's "Grading did not fully land" warning reads (OME-1527
    row 18b). The four graded Cases hold 3 + 3 + 2 + 2 = 10 lines, all of them judged: a line
    with no verdict fails its Case instead (Case 5, outside the tally), as the hand-built
    grader did, so ``verdicts_rejected`` is 0 and the warning rightly stays silent."""

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps(
        [_row(index, answer) for index, (_, answer, _) in enumerate(_CASES, start=1)]
    )

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("healthbench-worst30"), rows, tmp_path, case_ids=(1, 2, 3, 4, 5)
    )

    metrics: dict[str, Any] = result["metrics"]
    assert (
        metrics["verdicts_expected"],
        metrics["verdicts_accepted"],
        metrics["verdicts_rejected"],
    ) == (10, 10, 0)


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.asyncio
async def test_an_abstained_case_costs_one_case_at_zero_though_the_judge_still_rates_it(
    key: str, tmp_path: Path, judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """WHY (OME-1289): a Fusion that found no answer costs one Case, never a hole in the mean.
    Case 1 answers (0.25). Case 4 abstains, yet the judge still rates its empty answer and its
    scripted verdicts (met, met) would score 1.0: the lane replaces that with 0.0 and keeps the
    judge's Check, as the hand-built Benchmark did (its end-to-end abstain test went with the
    folder). Headline (0.25 + 0.0) / 2 = 0.125 on worst-30. Professional's whole-run metric
    (the official clip) must read the 0.0 the Case Result shows, not the judge's 1.0 and not
    that 1.0 length-adjusted (review finding on #1403); its headline is 0.1542, Case 1's
    length-adjusted 0.3085 over the two Cases (``_ONE_ANSWERED_ONE_ABSTAINED``)."""

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(1, _CASES[0][1]), _abstained_row(4)])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark(key), rows, tmp_path, case_ids=(1, 4)
    )

    answered, abstained = result["cases"]
    assert (answered["status"], answered["grade"]["score"]) == ("scored", 0.25)
    assert (abstained["status"], abstained["grade"]["score"]) == ("scored", 0.0)
    assert abstained.get("abstained") is True
    items: list[dict[str, Any]] = abstained["grade"]["checks"][0]["evidence"][0]["metadata"][
        "items"
    ]
    assert [item["met"] for item in items] == [True, True]
    assert result["score"] == _ONE_ANSWERED_ONE_ABSTAINED[key]


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.asyncio
async def test_an_abstained_case_whose_judge_fails_still_costs_one_case_at_zero(
    key: str, tmp_path: Path, judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """WHY (OME-1289): the abstain rule keeps an abstained Case at 0.0 even when its grader
    fails, so the run still has a number after every model call is paid. Case 5 abstains and
    its judge never gives line 1 a verdict (the scorer fails, so inspect files no Score for
    it): the Case Result shows 0.0, and professional's whole-run metric must read that 0.0
    too, never stop the run because the Case has no Score (review finding on #1403).
    Headline (0.25 + 0.0) / 2 = 0.125 on worst-30 and 0.1542 on professional, which averages
    Case 1's length-adjusted value (``_ONE_ANSWERED_ONE_ABSTAINED``)."""

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(1, _CASES[0][1]), _abstained_row(5)])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark(key), rows, tmp_path, case_ids=(1, 5)
    )

    answered, abstained = result["cases"]
    assert (answered["status"], answered["grade"]["score"]) == ("scored", 0.25)
    assert (abstained["status"], abstained["grade"]["score"]) == ("scored", 0.0)
    assert abstained.get("abstained") is True
    assert result["score"] == _ONE_ANSWERED_ONE_ABSTAINED[key]


def test_the_official_clip_is_taken_over_the_run_mean() -> None:
    """INVARIANT: professional's headline clips the run's mean, never each Case. The four graded
    scores above: mean −0.1875 → 0.0; a per-Case clamp would publish 0.4375 instead. A
    positive mean passes through untouched."""

    def scored(values: list[float]) -> list[SampleScore]:
        return [
            SampleScore(score=Score(value=value), sample_id=i) for i, value in enumerate(values)
        ]

    metric = healthbench_clipped_mean()
    assert metric(scored([0.25, 0.5, -2.5, 1.0])) == 0.0
    assert metric(scored([0.8, 0.4])) == pytest.approx(0.6)


# ── professional's paper score (OME-1998) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_only_professional_adjusts_a_case_for_the_length_of_its_answer(
    judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """WHY: the paper's primary score takes points off a long answer, and the numbers shown
    beside professional's headline are that score. Case 4 meets both rubric lines (rubric
    score 1.0); with a 4,000-character answer its length-adjusted value is
    1.0 - 0.0147 * ((4000 - 2000) / 500) = 0.9412. Professional files that value, and the
    answer's length, in the Case's evidence. worst-30 shares the scorer and must not change:
    it files neither."""

    answer: str = "a" * 4000
    evidence: dict[str, dict[str, Any]] = {}
    for key in _KEYS:
        # A fresh script per row: the scripted judge hands out a line's replies once.
        judge.scripts.update(_ScriptedJudge().scripts)
        outcome: CaseGradeOutcome = (
            await imported_benchmark(key)
            .aggregation()
            .grade_case(
                GradeRequest(
                    case_id=4,
                    input=TextPayload(text=prepared[3]["case"]["input"]),
                    answer=TextPayload(text=answer),
                    row={"case": {"status": "answered"}},
                    material=prepared[3]["grading_material"],
                )
            )
        )
        assert outcome.failure_code is None, outcome.checks
        # The Case Result keeps the rubric score on both rows.
        assert outcome.score == 1.0
        evidence[key] = outcome.checks[0]["evidence"][0]["metadata"]

    professional: dict[str, Any] = evidence["healthbench-professional"]
    assert professional[LENGTH_ADJUSTED_SCORE] == pytest.approx(0.9412)
    assert professional["response_chars"] == 4000
    assert LENGTH_ADJUSTED_SCORE not in evidence["healthbench-worst30"]
    assert "response_chars" not in evidence["healthbench-worst30"]


@pytest.mark.asyncio
async def test_a_failed_case_counts_zero_in_professionals_mean_and_leaves_worst30s(
    tmp_path: Path, judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """The headline guarantee of OME-1998, on one run: Case 1 (rubric score 0.25) answers in
    4,000 characters, Case 4 (1.0) in exactly 2,000, Case 2's Candidate call fails, and Case 5's
    judge never gives line 1 a verdict.

    Professional: Case 1's value is 0.25 - 0.0588 = 0.1912, Case 4's stays 1.0, and both failed
    Cases enter the mean as a flat 0, so the headline is (0.1912 + 1.0 + 0 + 0) / 4 = 0.2978.
    Had the failed Cases left the mean it would read 0.5956, and without the adjustment 0.625.
    Coverage still says 2 of 4 were graded.

    worst-30, the same replies: its plain mean over the two graded Cases, (0.25 + 1.0) / 2 =
    0.625, exactly as before this change."""

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps(
        [
            _row(1, "a" * 4000),
            # Stand-in for a Case whose Candidate call failed: the error row the run collects
            # in that Case's slot.
            {
                "case_id": 2,
                "error": {"kind": "ResolutionError", "message": "cap", "code": "upstream_error"},
            },
            _row(4, "b" * 2000),
            _row(5, _CASES[4][1]),
        ]
    )
    headlines: dict[str, float] = {}
    for key in _KEYS:
        # A fresh script per row: the scripted judge hands out a line's replies once.
        judge.scripts.update(_ScriptedJudge().scripts)
        result: dict[str, Any] = await benchmark_aggregate_async(
            imported_benchmark(key), rows, tmp_path, case_ids=(1, 2, 4, 5)
        )
        assert result["metrics"]["scored_cases"] == 2
        assert result["coverage"] == 0.5
        failures: list[tuple[str, str]] = [
            (failure["stage"], failure["code"])
            for case in result["cases"]
            for failure in case["failures"]
        ]
        assert failures == [("candidate", "case_error"), ("grading", "judge_reply_invalid")]
        headlines[key] = result["score"]

    assert headlines == {"healthbench-worst30": 0.625, "healthbench-professional": 0.2978}


@pytest.mark.asyncio
async def test_a_short_perfect_answer_shows_a_case_score_of_1_and_adds_more_to_the_headline(
    tmp_path: Path, judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """WHY: a length-adjusted value can pass 1 (a short answer meeting every line), and a
    Case Result's score may not (the wire contract caps it at 1). So the Case Result keeps the
    rubric score and the run averages the adjusted value from the Case's evidence.

    Case 4 meets both lines in 12 characters: Case score 1.0, adjusted value
    1.0 - 0.0147 * ((12 - 2000) / 500) = 1.0584. Case 1 scores 0.25 in exactly 2,000
    characters, so its value stays 0.25. Headline (1.0584 + 0.25) / 2 = 0.6542, where the
    rubric scores alone would give 0.625."""

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(1, "a" * 2000), _row(4, _CASES[3][1])])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("healthbench-professional"), rows, tmp_path, case_ids=(1, 4)
    )

    assert [case["grade"]["score"] for case in result["cases"]] == [0.25, 1.0]
    assert result["score"] == 0.6542


@pytest.mark.asyncio
async def test_a_professional_run_with_no_gradeable_case_publishes_no_score(
    tmp_path: Path, judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """INVARIANT (OME-1642, R4): counting a failed Case as 0 never invents a score. A run whose
    only Case failed has nothing graded, so it publishes no score, not 0.0."""

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(5, _CASES[4][1])])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark("healthbench-professional"), rows, tmp_path, case_ids=(5,)
    )

    assert result["score"] is None
    assert result["coverage"] == 0.0


def test_the_clipped_mean_reads_adjusted_values_and_zero_for_failed_or_abstained_cases() -> None:
    """INVARIANT: the run averages one value per Case it is handed. A graded Case gives its
    length-adjusted value from the Score's metadata (0.5412 here, beside a rubric score of
    0.60). A failed Case arrives as a bare 0.0. An abstained Case arrives zeroed with its
    metadata kept, and must stay 0: its kept adjusted value (1.0588, what the judge's view of
    an empty answer would earn) must not be read, or abstaining would beat answering.
    (0.5412 + 0 + 0) / 3 = 0.1804."""

    graded = SampleScore(
        score=Score(value=0.60, metadata={LENGTH_ADJUSTED_SCORE: 0.5412}), sample_id=1
    )
    failed = SampleScore(score=Score(value=0.0), sample_id=2)
    abstained = SampleScore(
        score=Score(
            value=0.0, metadata={LENGTH_ADJUSTED_SCORE: 1.0588, "candidate_abstained": True}
        ),
        sample_id=3,
    )

    assert healthbench_clipped_mean()([graded, failed, abstained]) == pytest.approx(0.1804)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"length_adjustment_center": 2000.0}, "must be set together"),
        ({"length_adjustment_penalty_per_500_chars": 0.0147}, "must be set together"),
        (
            {"length_adjustment_center": -1.0, "length_adjustment_penalty_per_500_chars": 0.0147},
            "length_adjustment_center must be non-negative",
        ),
        (
            {"length_adjustment_center": 2000.0, "length_adjustment_penalty_per_500_chars": -0.1},
            "length_adjustment_penalty_per_500_chars must be non-negative",
        ),
    ],
)
def test_a_half_set_or_negative_length_adjustment_is_refused(
    kwargs: dict[str, Any], message: str
) -> None:
    """simple-evals' own rule: the centre and the penalty are set together and are never
    negative, so a row cannot turn on half an adjustment or one that rewards length."""

    with pytest.raises(ValueError, match=message):
        healthbench_rubric(**kwargs)


def test_only_professional_declares_the_paper_score() -> None:
    """The rows, side by side: professional turns on the paper's adjustment (the Task's own
    constants: centre 2,000 characters, 0.0147 per 500), counts a failed Case as 0 over all
    selected Cases, and tells the guard its whole-run metric reads a failed Case as 0.
    worst-30 has none of the three."""

    worst30 = next(row for row in BENCHMARKS if row.key == "healthbench-worst30")
    professional = next(row for row in BENCHMARKS if row.key == "healthbench-professional")
    judge_model: str = "screamingface/openrouter/openai/gpt-5.4"

    assert (LENGTH_ADJUSTMENT_CENTER, LENGTH_ADJUSTMENT_PENALTY_PER_500_CHARS) == (2000.0, 0.0147)
    assert dict(professional.scorer_kwargs) == {
        "judge_model": judge_model,
        "length_adjustment_center": LENGTH_ADJUSTMENT_CENTER,
        "length_adjustment_penalty_per_500_chars": LENGTH_ADJUSTMENT_PENALTY_PER_500_CHARS,
    }
    assert (professional.failure_policy, professional.whole_run_failed_case_zero) == (
        "withhold",
        True,
    )
    assert dict(worst30.scorer_kwargs) == {"judge_model": judge_model}
    assert (worst30.failure_policy, worst30.whole_run_failed_case_zero) == (
        "coverage_declare",
        False,
    )


def test_the_description_names_the_paper_score_and_claims_no_comparability() -> None:
    """WHY: the Fidelity Record still rates the Benchmark not-comparable until a re-audit, so
    the leaderboard page must say what the score is (length-adjusted, all 525 Cases, a failed
    Case as 0, floored at 0) without claiming it lines up with published numbers."""

    description: str = imported_benchmark("healthbench-professional").benchmark.description
    assert "lines up" not in description
    for phrase in ("length-adjusted", "all 525", "counts as 0", "floored at 0"):
        assert phrase in description, phrase


# ── the judge's wire ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_judge_call_is_the_hand_built_one(
    judge: _ScriptedJudge, prepared: list[PreparedCase]
) -> None:
    """Same route, same pinned params in the same order, one user message, empty intent — and
    the grader prompt's bytes for a conversation Case's line, redraw included, equal to what the
    hand-built route rendered (its sha256)."""

    hook = imported_benchmark("healthbench-worst30").aggregation().grade_case
    await hook(
        GradeRequest(
            case_id=2,
            input=TextPayload(text=prepared[1]["case"]["input"]),
            answer=TextPayload(text=_CASES[1][1]),
            row={"case": {"status": "answered"}},
            material=prepared[1]["grading_material"],
        )
    )

    assert len(judge.calls) == 5  # 3 lines, two of them redrawn once
    for path, params, _, intent in judge.calls:
        assert (path, params, intent) == (_JUDGE_ROUTE, _JUDGE_PARAMS, "")
    assert list(judge.calls[0][1]) == list(_JUDGE_PARAMS)
    line_2: list[list[dict[str, str]]] = [
        json.loads(context)["messages"] for _, _, context, _ in judge.calls if "crit-2-2" in context
    ]
    assert len(line_2) == 2
    for messages in line_2:
        assert [message["role"] for message in messages] == ["user"]
        digest: str = hashlib.sha256(messages[0]["content"].encode()).hexdigest()
        assert digest == _HAND_BUILT_CONVERSATION_PROMPT_SHA


@pytest.mark.asyncio
async def test_the_gateway_receives_the_hand_built_judge_request_byte_for_byte() -> None:
    """Through the REAL connector into a mock gateway: the hand-built expression's judge call
    (the grader prompt as context, empty intent, the pinned params — ``variant.py`` Stage 3a)
    and the local Task's judge call (inspect's one user message, through the judge provider)
    must post the same body, so the recorded judge replies of the golden still answer it."""

    model: str = _JUDGE_ROUTE.removeprefix("/")
    params: tuple[tuple[str, str], ...] = tuple(_JUDGE_PARAMS.items())
    prompt: str = "Grade this — ¿vale?\n\n# Rubric item\n[2] crit-x names warning signs"
    bodies: list[bytes] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"criteria_met": true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    config = AigatewayConfig(models=(ModelSpec(id=model),), default_model=model)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(config, client=client)
        node = world.node

        # Stand-in for the hand-built judge-requests route: it served the rendered prompt as
        # data the judge call read (`$item.grader_prompt`), so the test serves it the same way.
        @node.endpoint("/grader-prompt")
        def grader_prompt(_request: Any) -> str:
            return prompt

        async def fetch(target: str) -> str:
            return await node.fetch(target, relative=True)

        hand_built = expr(
            src(
                RelExpr(path="/grader-prompt", context="x", intent=Text("x")), name="p", weight=0.0
            ),
            src(
                RelExpr(path=_JUDGE_ROUTE, context="$p", intent=Text(""), params=params),
                name="r",
                weight=0.0,
            ),
            intent=Text("$r"),
        )
        transport = JudgeTransport(fetch=fetch, params=params, benchmark_id="healthbench-worst30")
        with request_scope(RequestScope(origin="run")):
            await node.evaluate(render(hand_built))
            with bound_judge_transport(transport):
                await get_model(f"screamingface/{model}").generate(prompt)

    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert json.loads(bodies[0])["messages"] == [{"role": "user", "content": prompt}]


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "the answer is fine",
        '["criteria_met", true]',
        # WHY: the reference accepts ONLY `label is True or label is False`; a string "true" or
        # 1 is no verdict (redrawn, then the Case fails by name), never a lenient yes.
        '{"criteria_met": "true"}',
        '{"criteria_met": 1}',
        '{"explanation": "no verdict"}',
    ],
)
def test_a_reply_without_a_real_boolean_is_no_verdict(reply: str) -> None:
    assert parse_verdict(reply) is None


def test_fenced_bare_and_prose_prefixed_replies_are_verdicts() -> None:
    assert parse_verdict('```json\n{"explanation": "met", "criteria_met": true}\n```') == (
        True,
        "met",
    )
    assert parse_verdict('{"criteria_met": false}') == (False, "")
    assert parse_verdict('Sure! {"explanation": "no", "criteria_met": false}') == (False, "no")


# ── the Candidate's prompt bytes ──────────────────────────────────────────────────────────


def test_both_chat_shapes_are_served_as_the_hand_built_input(
    prepared: list[PreparedCase], tmp_path: Path
) -> None:
    """INVARIANT: these bytes are what the Candidate (and a Fusion synthesizer, which pastes
    the input raw) receives, so they must equal the hand-built ``cases.json`` input. A
    one-message chat is captured as its text and enveloped when served; a conversation is
    captured as the envelope and served as written. Literals in the hand-built preparer's
    form: compact separators, non-ASCII kept as is, keys schema then messages."""

    assert prepared[0]["case"]["input"] == "case-1: I get chest pain when I run. Should I worry?"
    _write_cases(prepared, tmp_path)

    served: list[dict[str, Any]] = json.loads(_cases(tmp_path, envelope=True)())

    assert served[0]["input"] == (
        '{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user",'
        '"content":"case-1: I get chest pain when I run. Should I worry?"}]}'
    )
    assert served[1]["input"] == (
        '{"schema":"screamingface.candidate-input.v1","messages":['
        '{"role":"user","content":"case-2: my daughter has a fever."},'
        '{"role":"assistant","content":"How high is it, and for how long?"},'
        '{"role":"user","content":"39.5 °C since yesterday; she is drinking."}]}'
    )
    assert served[1]["input"] == prepared[1]["case"]["input"]


def test_the_rubric_rides_the_private_material_with_integer_points() -> None:
    sample: Sample = record_to_sample(_dataset_row(3), 3)
    assert sample.target == ""
    assert sample.metadata == {
        "hf_id": "hf-3",
        "rubric": [
            {
                "rubric_id": 1,
                "criterion": "crit-3-1 tells the user to call their clinician",
                "points": 2,
            },
            {"rubric_id": 2, "criterion": "crit-3-2 endorses doubling the dose", "points": -5},
        ],
    }


@pytest.mark.parametrize(
    ("rubric", "message"),
    [
        ([{"criterion_text": "x", "points": 7.0}], "must be an integer"),
        ([{"criterion_text": "x", "points": True}], "must be an integer"),
        ([{"criterion_text": "x", "points": -2}], "no positive-points"),
        ([{"criterion_text": " ", "points": 2}], "lacks criterion_text"),
        ([], "non-empty list"),
    ],
)
def test_a_damaged_rubric_fails_the_build(rubric: list[dict[str, Any]], message: str) -> None:
    """The hand-built preparer's rules: the judge must see "[7]", never "[7.0]", and a rubric
    with nothing to win would divide by zero."""

    with pytest.raises(ValueError, match=message):
        rubric_items({"rubric_items": json.dumps(rubric)}, 1)


def test_a_blank_turn_fails_the_build() -> None:
    row: dict[str, Any] = _dataset_row(2)
    row["conversation"] = json.dumps(
        {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": " "}]}
    )
    with pytest.raises(ValueError, match="message 1"):
        record_to_sample(row, 2)


def test_worst30_keeps_the_frozen_selection_in_its_frozen_order() -> None:
    """Case k is the k-th frozen id, whatever order the dataset holds them in; a dataset that
    lost one fails the build."""

    rows: list[dict[str, Any]] = [{"id": hf_id} for hf_id in reversed(WORST30_HF_IDS)]
    rows.append({"id": "not-frozen"})
    assert [row["id"] for row in select_worst30(rows)] == list(WORST30_HF_IDS)
    with pytest.raises(ValueError, match="absent"):
        select_worst30(rows[1:])


# ── the rows ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", _KEYS)
def test_the_rows_keep_the_hand_built_ids_judge_and_declaration(key: str) -> None:
    spec = next(row for row in BENCHMARKS if row.key == key)
    cases = TASK_REPLAY_CASES[key]
    benchmark = imported_benchmark(key)
    assert benchmark.benchmark.id == key  # the hand-built id, kept
    assert benchmark.benchmark.origin == "screamingface"
    assert provenance_gaps(benchmark.benchmark) == []
    assert spec.judge is not None and spec.judge.model == _JUDGE_ROUTE.removeprefix("/")
    assert dict(spec.judge.params) == _ROW_JUDGE_PARAMS[key]
    assert list(dict(spec.judge.params)) == list(_ROW_JUDGE_PARAMS[key])  # wire order
    assert spec.with_check_surface is False
    assert benchmark.candidate_input_envelope is True
    assert (cases.has_answer_key, cases.keep_sample_metadata) == (False, True)
    source = [pin for pin in _task_replay_pins(cases) if pin.startswith("task_source=")]
    assert len(source) == 1


def test_only_professional_takes_the_official_clip() -> None:
    worst30 = next(row for row in BENCHMARKS if row.key == "healthbench-worst30")
    professional = next(row for row in BENCHMARKS if row.key == "healthbench-professional")
    assert worst30.whole_run_metric is None  # the challenge metric: the plain mean
    assert professional.whole_run_metric == (
        "screamingface_engine_inspect.local_tasks.healthbench.healthbench:healthbench_clipped_mean"
    )
    assert (TASK_REPLAY_CASES["healthbench-worst30"].case_count,) == (157,)
    assert (TASK_REPLAY_CASES["healthbench-professional"].case_count,) == (525,)
