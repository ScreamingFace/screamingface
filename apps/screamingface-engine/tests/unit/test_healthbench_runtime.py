"""HealthBench runtime routes — preflight, task building, and the grading chain.

INVARIANT under test: the judge prompt is rendered Engine-side with the reference's
exact assembly, identities are bound by the Engine (never model-supplied), and unusable
assets fail LOUDLY before any paid call (S-DR3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.case_execution import (
    case_execution_payload,
    install_case_execution,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE, encode_candidate_invocation
from screamingface_engine.benchmarks.healthbench.case_evaluation import (
    CASE_EVALUATION_SCHEMA,
    RUBRIC_EVALUATION_SCHEMA,
)
from screamingface_engine.benchmarks.healthbench.definition import (
    HEALTHBENCH_PROFESSIONAL,
    HEALTHBENCH_WORST30,
    PROFESSIONAL_EXAM,
    WORST30_EXAM,
)
from screamingface_engine.benchmarks.healthbench.exam import ASSET_BUNDLE_ID
from screamingface_engine.benchmarks.healthbench.pins import JUDGE_MODEL
from screamingface_engine.benchmarks.healthbench.prepare import envelope
from screamingface_engine.benchmarks.healthbench.prompts import GRADER_TEMPLATE
from screamingface_engine.benchmarks.healthbench.runtime import install, preflight
from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS
from screamingface_engine.benchmarks.healthbench.verdict import call as verdict_call
from screamingface_engine.benchmarks.run_logs import BenchmarkRunLogAdapter
from screamingface_engine.run_log_contract import LogScalar
from url4 import RelExpr, Text, expr, render, src
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_MESSAGES = [
    {"role": "user", "content": "STOP-DAPt trial"},
]
_ANSWER = "STOPDAPT-2 studied 1-month DAPT after PCI; which variant do you mean?"
# The Case a limit=1 run selects: cases.json order decides, and the fixture writes the
# subset in WORST30_CASE_IDS order, so the first id is the exercised one.
_CASE_ID = WORST30_CASE_IDS[0]


def _write_assets(root: Path) -> None:
    # Bake the full worst30 subset — the exam preflights ALL 157 Cases, so a partial
    # fixture cannot serve any route. The exercised first Case carries the real rubric
    # the assertions read; the rest carry an interchangeable one-item rubric.
    root.mkdir(parents=True, exist_ok=True)
    (root / "cases.json").write_text(
        json.dumps([{"id": case_id, "input": envelope(_MESSAGES)} for case_id in WORST30_CASE_IDS]),
        encoding="utf-8",
    )
    rubric_dir = root / "rubrics"
    rubric_dir.mkdir(exist_ok=True)
    for case_id in WORST30_CASE_IDS:
        (rubric_dir / f"{case_id}.json").write_text(
            json.dumps(
                {
                    "hf_id": f"hf-{case_id}",
                    "items": [
                        {"rubric_id": 1, "criterion": "seeks context for the study", "points": 8}
                    ],
                }
            ),
            encoding="utf-8",
        )


async def _call(node: Url4Node, path: str, context: object, intent: str) -> object:
    payload = context if isinstance(context, str) else json.dumps(context)
    expression = expr(
        src(Text(payload), name="payload", weight=0.0),
        src(
            RelExpr(path=path, context="$payload", intent=Text(intent)),
            name="result",
            weight=0.0,
        ),
        intent=Text("$result"),
    )
    return json.loads((await node.evaluate(render(expression))).text)


def test_preflight_fails_loudly_on_missing_assets(tmp_path: Path) -> None:
    with pytest.raises(ResolutionError, match="failed preflight"):
        preflight(tmp_path, WORST30_CASE_IDS)


def test_preflight_names_a_missing_rubric(tmp_path: Path) -> None:
    _write_assets(tmp_path)
    (tmp_path / "rubrics" / f"{_CASE_ID}.json").unlink()
    with pytest.raises(ResolutionError, match="rubric asset"):
        preflight(tmp_path, WORST30_CASE_IDS)


@pytest.mark.asyncio
async def test_the_worst30_cases_route_preflights_all_157(tmp_path: Path) -> None:
    # Partial assets cannot serve the exam — the data route must refuse BEFORE any
    # Candidate call instead of iterating over an incomplete subset.
    _write_assets(tmp_path)
    (tmp_path / "rubrics" / f"{_CASE_ID}.json").unlink()
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    with pytest.raises(ResolutionError, match="failed preflight"):
        await node.fetch(WORST30_EXAM.routes.cases, relative=True)


@pytest.mark.asyncio
async def test_the_cases_route_serves_the_frozen_subset(tmp_path: Path) -> None:
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    cases = json.loads(await node.fetch(WORST30_EXAM.routes.cases, relative=True))
    assert [case["id"] for case in cases] == list(WORST30_CASE_IDS)
    # Privacy: the public rows carry the chat envelope and NOTHING of the rubric.
    assert "rubric" not in json.dumps(cases)
    assert "seeks context" not in json.dumps(cases)


@pytest.mark.asyncio
async def test_rubric_tasks_render_the_reference_prompt_bytes(tmp_path: Path) -> None:
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    rows = await _call(
        node,
        WORST30_EXAM.routes.tasks,
        encode_candidate_invocation(_ANSWER, "stop", None),
        str(_CASE_ID),
    )
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row["case_id"] == str(_CASE_ID)
    assert row["rubric_id"] == "1"
    # The reference `grade_sample` assembly, byte for byte: flattened "role: content"
    # transcript, the answer appended as the final assistant turn, `[points] criterion`.
    transcript = "user: STOP-DAPt trial"
    expected = GRADER_TEMPLATE.replace(
        "<<conversation>>", f"{transcript}\n\nassistant: {_ANSWER}"
    ).replace("<<rubric_item>>", "[8] seeks context for the study")
    assert row["grader_prompt"] == expected
    # The Case record (with the full output) rides the first row only.
    case_record = json.loads(row["case_record"])
    assert case_record["case_id"] == _CASE_ID
    assert case_record["output"] == _ANSWER
    assert case_record["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_rubric_tasks_grade_exact_refusal_text_through_the_normal_judge(
    tmp_path: Path,
) -> None:
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    exact = "I cannot provide a medical recommendation."

    rows = await _call(
        node,
        WORST30_EXAM.routes.tasks,
        encode_candidate_invocation("", "content_filter", exact),
        str(_CASE_ID),
    )

    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert f"assistant: {exact}" in row["grader_prompt"]
    case_record = json.loads(row["case_record"])
    assert case_record["answer"] == case_record["refusal"] == exact
    assert case_record["output"] is None
    assert case_record["finish_reason"] == "content_filter"


@pytest.mark.asyncio
async def test_the_grading_chain_binds_engine_identities(tmp_path: Path) -> None:
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    tasks = await _call(
        node,
        WORST30_EXAM.routes.tasks,
        encode_candidate_invocation(_ANSWER, None, None),
        str(_CASE_ID),
    )
    assert isinstance(tasks, list)
    task = tasks[0]
    verdict = await _call(
        node,
        WORST30_EXAM.routes.verdict,
        '{"explanation": "asks which study", "criteria_met": true}',
        f"{_CASE_ID}:1",
    )
    assert isinstance(verdict, dict)
    assert verdict["valid"] is True
    assert verdict["case_id"] == _CASE_ID
    rubric_evaluation = await _call(
        node,
        WORST30_EXAM.routes.rubric_evaluation,
        {
            "case": task["case_record"],
            "rubric": task["rubric_record"],
            "evidence": json.dumps(verdict),
        },
        str(_CASE_ID),
    )
    assert isinstance(rubric_evaluation, dict)
    assert rubric_evaluation["schema"] == RUBRIC_EVALUATION_SCHEMA
    case_evaluation = await _call(
        node,
        WORST30_EXAM.routes.case_evaluation,
        [json.dumps(rubric_evaluation)],
        str(_CASE_ID),
    )
    assert isinstance(case_evaluation, dict)
    assert case_evaluation["schema"] == CASE_EVALUATION_SCHEMA
    result = await _call(
        node,
        WORST30_EXAM.routes.aggregate,
        json.dumps(
            [
                case_execution_payload(
                    _CASE_ID,
                    encode_candidate_invocation(_ANSWER, None, None),
                    [case_evaluation],
                )
            ]
        ),
        # v2 intent: "aggregate:<selected>" — the count of Cases this run selected
        # (how a limit=N run tells the reducer to score only the first N).
        "aggregate:1",
    )
    assert isinstance(result, dict)
    # The single +8 item was met — the Case scores 1.0 and the mean follows.
    assert result["score"] == 1.0
    assert result["metrics"]["verdict_coverage"] == 1.0


@pytest.mark.asyncio
async def test_a_malformed_judge_reply_retries_with_a_fresh_sample(tmp_path: Path) -> None:
    # INVARIANT (the reference's retry condition, healthbench_eval.py:415-423): a
    # malformed reply is a SUCCESSFUL model call, so the retry must live on the
    # verdict route and re-resolve the NESTED judge call — each re-ask is a fresh
    # sample. Sibling wiring would deterministically re-deliver the same bad reply.
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    calls = {"judge": 0}

    @node.endpoint(f"/{JUDGE_MODEL}")
    def judge(request: Request) -> str:
        calls["judge"] += 1
        if calls["judge"] < 3:
            return "I think the answer is fine"  # prose — no verdict
        return '{"explanation": "ok", "criteria_met": true}'

    judge_call = RelExpr(path=f"/{JUDGE_MODEL}", context="prompt", intent=Text(""))
    expression = expr(
        verdict_call(
            judge_call,
            case_id=str(_CASE_ID),
            rubric_id="1",
            route=WORST30_EXAM.routes.verdict,
            retry=2,
        ),
        intent=Text("$verdict"),
    )
    record = json.loads((await node.evaluate(render(expression))).text)
    assert calls["judge"] == 3  # two fresh re-asks, third sample parsed
    assert record["valid"] is True
    assert record["criteria_met"] is True


@pytest.mark.asyncio
async def test_exhausted_judge_retries_fail_loudly(tmp_path: Path) -> None:
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    calls = {"judge": 0}

    @node.endpoint(f"/{JUDGE_MODEL}")
    def judge(request: Request) -> str:
        calls["judge"] += 1
        return "never json"

    judge_call = RelExpr(path=f"/{JUDGE_MODEL}", context="prompt", intent=Text(""))
    expression = expr(
        verdict_call(
            judge_call,
            case_id=str(_CASE_ID),
            rubric_id="1",
            route=WORST30_EXAM.routes.verdict,
            retry=2,
        ),
        intent=Text("$verdict"),
    )
    with pytest.raises(ResolutionError, match="invalid judge reply"):
        await node.evaluate(render(expression))
    assert calls["judge"] == 3  # 1 initial + 2 bounded re-asks, then loud failure


@pytest.mark.asyncio
async def test_the_aggregate_route_rejects_other_operations(tmp_path: Path) -> None:
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    with pytest.raises(ResolutionError, match="unsupported HealthBench operation"):
        await _call(node, WORST30_EXAM.routes.aggregate, "[]", "score")


@pytest.mark.asyncio
async def test_a_limit_one_expression_resolves_end_to_end(tmp_path: Path) -> None:
    # WHY this test exists: every route handler passed its direct-call unit tests
    # while the LIVE run still died between routes — the url4 resolver's rendering
    # of iterate collections is part of the protocol, and only resolving the real
    # built expression exercises it. Guards the expression↔runtime seam, on the
    # same sliced (limit=1) expression the SDK compiles for a cheap rehearsal.
    _write_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    install_case_execution(node)

    @node.endpoint(CANDIDATE_ROUTE)
    def candidate(request: Request) -> str:
        return encode_candidate_invocation(_ANSWER, "stop", None)

    @node.endpoint(f"/{JUDGE_MODEL}")
    def judge(request: Request) -> str:
        assert GRADER_TEMPLATE.splitlines()[0] in request.context
        return '{"explanation": "asks which study", "criteria_met": true}'

    expression = expr(
        src(Text("unused-candidate-recipe"), name="candidate", weight=0.0),
        src(HEALTHBENCH_WORST30.protocol(1), name="exam", weight=0.0),
        intent=Text("$exam"),
    )
    result = json.loads((await node.evaluate(render(expression))).text)
    assert result["score"] == 1.0, result["cases"]
    assert result["case_count"] == 1
    assert result["metrics"]["verdict_coverage"] == 1.0
    assert result["cases"][0]["failures"] == []


@pytest.mark.asyncio
async def test_real_limit_one_expression_emits_one_exact_provisional_snapshot(
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / ASSET_BUNDLE_ID
    _write_assets(bundle_root)
    node = Url4Node("test")
    install(node, bundle_root, WORST30_EXAM)
    install_case_execution(node)

    @node.endpoint(CANDIDATE_ROUTE)
    def candidate(_request: Request) -> str:
        return encode_candidate_invocation(_ANSWER, "stop", None)

    @node.endpoint(f"/{JUDGE_MODEL}")
    def judge(_request: Request) -> str:
        return '{"explanation": "asks which study", "criteria_met": true}'

    expression = expr(
        src(Text("unused-candidate-recipe"), name="candidate", weight=0.0),
        src(HEALTHBENCH_WORST30.protocol(1), name="exam", weight=0.0),
        intent=Text("$exam"),
    )
    rendered = render(expression)
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scope = BenchmarkRunLogAdapter(BUILTIN_BENCHMARKS, assets_root=tmp_path).open_run_scope(
        rendered,
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        final = json.loads((await node.evaluate(rendered)).text)

    assert final["score"] == 1.0
    assert records == [
        (
            "evaluation progress",
            {
                "screamingface.event.schema": "screamingface.evaluation-progress.v1",
                "cases.total": 1,
                "cases.completed": 1,
                "cases.graded": 1,
                "cases.failed": 0,
                "cases.refused": 0,
                "score.provisional": final["score"],
                "score.coverage": final["coverage"],
            },
        )
    ]


def _write_full_assets(root: Path, points: tuple[int, ...] = (8,)) -> None:
    """The whole baked answer key — all 525 Cases, the superset both boards select from.

    ``points`` is the rubric every Case carries. A positive item is a win a good answer
    earns; a negative one is a penalty. INVARIANT (prepare.py): at least one item must be
    positive, or the score has no denominator — so driving a Case below zero means a small
    win plus a bigger penalty, e.g. ``(2, -8)``.
    """

    root.mkdir(parents=True, exist_ok=True)
    case_ids = tuple(PROFESSIONAL_EXAM.case_ids)
    (root / "cases.json").write_text(
        json.dumps([{"id": case_id, "input": envelope(_MESSAGES)} for case_id in case_ids]),
        encoding="utf-8",
    )
    rubric_dir = root / "rubrics"
    rubric_dir.mkdir(exist_ok=True)
    for case_id in case_ids:
        (rubric_dir / f"{case_id}.json").write_text(
            json.dumps(
                {
                    "hf_id": f"hf-{case_id}",
                    "items": [
                        {"rubric_id": index, "criterion": f"criterion {index}", "points": value}
                        for index, value in enumerate(points, start=1)
                    ],
                }
            ),
            encoding="utf-8",
        )


@pytest.mark.asyncio
async def test_both_boards_serve_one_answer_key_from_separate_addresses(tmp_path: Path) -> None:
    """INVARIANT (OME-903): two exams, ONE baked asset root, zero route collisions.

    The professional board is a second SELECTION over the same `cases.json` — never a
    second bake and never a renumbering. Installing both into one Runner world must
    therefore work, and each board must serve exactly its own case list.
    """

    _write_full_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_EXAM)
    install(node, tmp_path, PROFESSIONAL_EXAM)

    professional_routes = PROFESSIONAL_EXAM.routes
    assert professional_routes.cases != WORST30_EXAM.routes.cases

    worst30_cases = json.loads(await node.fetch(WORST30_EXAM.routes.cases, relative=True))
    professional_cases = json.loads(await node.fetch(professional_routes.cases, relative=True))
    assert [case["id"] for case in worst30_cases] == list(WORST30_CASE_IDS)
    assert [case["id"] for case in professional_cases] == list(range(1, 526))
    # The hard subset is a strict subset of the full exam — same ids, same answer key.
    assert set(WORST30_CASE_IDS) <= {case["id"] for case in professional_cases}
    # INVARIANT: the answer key stays private on BOTH boards — a Candidate sees chat
    # envelopes and nothing of the rubric, whichever exam it is sitting.
    served = json.dumps(professional_cases)
    assert "rubric" not in served
    assert "criterion" not in served


@pytest.mark.asyncio
async def test_the_official_clip_reaches_the_score_through_the_real_expression(
    tmp_path: Path,
) -> None:
    """The professional board's whole point, end to end: a negative run reports 0.0.

    Unit-testing ``clipped_mean`` proves the arithmetic; only resolving the BUILT
    expression proves the board actually wired that arithmetic into its aggregate route.
    The rubric here is a +2 win and a -8 penalty, both judged MET, so the one graded Case
    scores (2 - 8) / 2 = -3.0 — the challenge metric would publish -3.0, the official
    metric publishes 0.0.
    """

    _write_full_assets(tmp_path, points=(2, -8))
    node = Url4Node("test")
    install(node, tmp_path, PROFESSIONAL_EXAM)
    install_case_execution(node)

    @node.endpoint(CANDIDATE_ROUTE)
    def candidate(request: Request) -> str:
        return encode_candidate_invocation(_ANSWER, "stop", None)

    @node.endpoint(f"/{JUDGE_MODEL}")
    def judge(request: Request) -> str:
        # The judge says the PENALTY criterion was triggered — the worst possible answer.
        return '{"explanation": "invents a dosage", "criteria_met": true}'

    expression = expr(
        src(Text("unused-candidate-recipe"), name="candidate", weight=0.0),
        src(HEALTHBENCH_PROFESSIONAL.protocol(1), name="exam", weight=0.0),
        intent=Text("$exam"),
    )
    result = json.loads((await node.evaluate(render(expression))).text)

    assert result["score"] == 0.0, result["cases"]
    # The Case's own grade keeps the unclamped truth — only the exam total is floored.
    assert result["cases"][0]["grade"]["score"] == -3.0
    assert result["benchmark_id"] == "healthbench-professional"
