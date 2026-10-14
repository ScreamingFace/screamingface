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
- the rows: ids, origin, the judge pinned, the envelope kept, the clip only on professional.

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
    healthbench_clipped_mean,
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
    the 0.4375 a per-Case clamp would give) — the hand-built numbers. The Case whose judge
    never gave a verdict is left out of the mean and counted against coverage, never scored 0.
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
    folder). Headline (0.25 + 0.0) / 2 = 0.125 on BOTH Benchmarks: professional's whole-run
    metric (the official clip) must read the 0.0 the Case Result shows, not the judge's 1.0,
    or it would publish (0.25 + 1.0) / 2 = 0.625 (review finding on #1403)."""

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
    assert result["score"] == 0.125


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
    Headline (0.25 + 0.0) / 2 = 0.125 on both Benchmarks."""

    _write_cases(prepared, tmp_path)
    rows: str = json.dumps([_row(1, _CASES[0][1]), _abstained_row(5)])

    result: dict[str, Any] = await benchmark_aggregate_async(
        imported_benchmark(key), rows, tmp_path, case_ids=(1, 5)
    )

    answered, abstained = result["cases"]
    assert (answered["status"], answered["grade"]["score"]) == ("scored", 0.25)
    assert (abstained["status"], abstained["grade"]["score"]) == ("scored", 0.0)
    assert abstained.get("abstained") is True
    assert result["score"] == 0.125


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
    assert dict(spec.judge.params) == _JUDGE_PARAMS
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
