# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Judged-board assembly — the judge is exam identity, and its only exit is the node.

A judged board's exam is not just its dataset: swap the judge model, its prompt, or
its pinned params and a candidate sits a DIFFERENT exam. This suite pins that the
judge declaration (``JudgeSpec``) rides the revision hash, that every misdeclaration
refuses at assembly (CI), never at grade time, and that the aggregate binds the
judge transport so the scorer's judge call leaves through the node's model route.

INVARIANT: the 10 published string-match boards' revisions must NOT move — judge
pins exist only when a judge is declared, and scorer kwargs stay outside the hash
for undeclared boards exactly as they were before OME-1240.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.case_execution import case_execution_payload  # noqa: E402
from screamingface_engine.benchmarks.contract import (  # noqa: E402
    encode_candidate_invocation,
)
from screamingface_engine_inspect import boards, single_shot  # noqa: E402
from screamingface_engine_inspect.boards import BoardSpec  # noqa: E402
from screamingface_engine_inspect.envelopes import (  # noqa: E402
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Request, Url4Node  # noqa: E402


def _judged_spec(**overrides: Any) -> BoardSpec:
    """One minimal judged row — a model_graded_qa board pinned to gateway judge-4."""

    values: dict[str, Any] = {
        "key": "gsm8k",  # reuses the real snapshot row; the board caches are patched
        "title": "Judged Test Board",
        "description": "test",
        "focus": "test",
        "dataset_url": "https://example.test/ds",
        "difficulty": "easy",
        "scorer": "inspect_ai.scorer:model_graded_qa",
        "scorer_kwargs": {"model": "screamingface/judge-4"},
        "judge": JudgeSpec(model="judge-4", params=(("temperature", "0"),)),
        "with_check_surface": False,
    }
    values.update(overrides)
    return BoardSpec(**values)


def _assembled(spec: BoardSpec, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Assemble one row through the REAL catalogue path, on fresh board caches."""

    monkeypatch.setattr(boards, "BOARDS", (spec,))
    monkeypatch.setattr(boards, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BOARDS_BY_ID", {})
    return boards.imported_board(spec.key)


def _revision(spec: BoardSpec, monkeypatch: pytest.MonkeyPatch) -> str:
    return str(_assembled(spec, monkeypatch).benchmark.revision)


# ── the judge is exam identity ───────────────────────────────────────────────


def test_a_judged_boards_revision_moves_with_the_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: swapping the judge is a different exam — the revision must move."""

    base = _revision(_judged_spec(), monkeypatch)
    other = _revision(
        _judged_spec(
            judge=JudgeSpec(model="judge-5", params=(("temperature", "0"),)),
            scorer_kwargs={"model": "screamingface/judge-5"},
        ),
        monkeypatch,
    )
    assert base != other


def test_a_judged_boards_revision_moves_with_the_judge_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judge's grading prompt (template/instructions kwargs) is exam identity."""

    base = _revision(_judged_spec(), monkeypatch)
    other = _revision(
        _judged_spec(
            scorer_kwargs={
                "model": "screamingface/judge-4",
                "template": "Grade strictly: {question} {answer} {criterion} {instructions}",
            }
        ),
        monkeypatch,
    )
    assert base != other


def test_a_judged_boards_revision_moves_with_the_judge_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _revision(_judged_spec(), monkeypatch)
    other = _revision(
        _judged_spec(judge=JudgeSpec(model="judge-4", params=(("temperature", "1"),))),
        monkeypatch,
    )
    assert base != other


def test_the_same_judged_spec_assembles_to_the_same_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _revision(_judged_spec(), monkeypatch) == _revision(_judged_spec(), monkeypatch)


def test_a_string_match_boards_kwargs_stay_outside_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT (frozen published revisions): for an UNDECLARED board, scorer kwargs
    were never exam identity before OME-1240 and must not become it now — the 10
    published boards keep their revisions byte-identical."""

    plain = _judged_spec(
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={"numeric": True},
        judge=None,
    )
    reworded = _judged_spec(
        scorer="inspect_ai.scorer:match",
        scorer_kwargs={},
        judge=None,
    )
    assert _revision(plain, monkeypatch) == _revision(reworded, monkeypatch)


# ── misdeclarations refuse at assembly, never at grade time ──────────────────


def test_an_undeclared_gateway_judge_kwarg_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row whose scorer dials the gateway without a JudgeSpec would grade with an
    unpinned judge — silently outside exam identity. Refuse at assembly (CI)."""

    spec = _judged_spec(judge=None)
    with pytest.raises(ValueError, match="judge"):
        _assembled(spec, monkeypatch)


def test_a_model_graded_scorer_without_a_judge_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_graded_* with no explicit model rides inspect's grader ROLE — a path
    this plugin does not support yet; it must refuse by name, not fail every Case."""

    spec = _judged_spec(judge=None, scorer_kwargs={})
    with pytest.raises(ValueError, match="judge"):
        _assembled(spec, monkeypatch)


def test_a_judge_model_missing_from_the_scorer_kwargs_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declaration and the scorer must dial the SAME judge — a typo between the
    two would pin one model and call another."""

    spec = _judged_spec(scorer_kwargs={"model": "screamingface/judge-5"})
    with pytest.raises(ValueError, match="judge-4"):
        _assembled(spec, monkeypatch)


def test_an_unresolved_todo_judge_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The importer emits judge model TODO — an unreviewed row must fail CI by name."""

    spec = _judged_spec(
        judge=JudgeSpec(model="TODO"),
        scorer_kwargs={"model": "screamingface/TODO"},
    )
    with pytest.raises(ValueError, match="TODO"):
        _assembled(spec, monkeypatch)


def test_a_judged_board_with_a_check_surface_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judged mid-run check spends judge tokens per attempt; until the check-cost
    knob exists (OME-1116) a judged board must not advertise a check surface."""

    spec = _judged_spec(with_check_surface=True)
    with pytest.raises(ValueError, match="check"):
        _assembled(spec, monkeypatch)


# ── the aggregate binds the transport: the judge call exits via the node ─────


class _JudgeEndpoint:
    """A fake gateway model route: records requests, replies with a fixed grade."""

    def __init__(self, reply: str = "The answer matches.\n\nGRADE: C") -> None:
        self.requests: list[Request] = []
        self.reply = reply

    async def __call__(self, request: Request) -> str:
        self.requests.append(request)
        return self.reply


def _bake_by_hand(root: Path, benchmark_id: str) -> None:
    board_root = root / benchmark_id
    (board_root / "targets").mkdir(parents=True)
    (board_root / "cases.json").write_text(
        json.dumps([{"id": 1, "input": "What is the capital of France?"}]),
        encoding="utf-8",
    )
    (board_root / "targets" / "1.json").write_text(
        json.dumps({"target": "Paris"}), encoding="utf-8"
    )


def _row(case_id: int, answer: str) -> dict[str, object]:
    record = {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": answer,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
    }
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [bind_case_evaluation(case_id, [record])],
    )


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    result = await node.evaluate(
        render(
            expr(
                src(text(payload), name="payload", weight=0.0),
                RelExpr(path=route, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


@pytest.mark.asyncio
async def test_the_aggregate_binds_the_judge_transport_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole seam under one roof: a judged board's aggregate grades a Case by
    dialing the node's own judge route — pinned params on the wire, score in the
    result, and the judge's words in the evidence."""

    board = _assembled(_judged_spec(), monkeypatch)
    judge = _JudgeEndpoint()
    node = Url4Node("test")
    node.endpoint("/judge-4")(judge)
    _bake_by_hand(tmp_path, board.benchmark.id)
    board.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "Paris is the capital of France.")])
    result = json.loads(await _call(node, board.aggregate_route, rows, "aggregate:1"))

    assert result["score"] == 1.0
    assert result["cases"][0]["grade"]["score"] == 1.0
    # The judge's own words survive into the evidence (audit trail).
    assert "The answer matches." in json.dumps(result["cases"][0]["grade"]["checks"])
    # Exactly one judge call left the engine, through the declared route,
    # carrying the pinned params.
    assert len(judge.requests) == 1
    assert judge.requests[0].params.get("temperature") == "0"
    envelope = json.loads(judge.requests[0].context)
    assert envelope["schema"].startswith("screamingface.candidate-input.")


@pytest.mark.asyncio
async def test_a_judge_route_failure_fails_the_case_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A gateway refusal is ONE Case's named failure, never an aborted aggregate."""

    board = _assembled(_judged_spec(), monkeypatch)

    async def refusing(request: Request) -> str:
        raise RuntimeError("the gateway refused: judge overloaded")

    node = Url4Node("test")
    node.endpoint("/judge-4")(refusing)
    _bake_by_hand(tmp_path, board.benchmark.id)
    board.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "Paris.")])
    result = json.loads(await _call(node, board.aggregate_route, rows, "aggregate:1"))

    case = result["cases"][0]
    assert case["grade"]["score"] is None
    assert case["failures"][0]["code"] == "scorer_error"


def test_the_judge_declaration_rides_the_assembled_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The binding seam: install-time wiring reads the judge off the ImportedBoard."""

    board = _assembled(_judged_spec(), monkeypatch)
    assert board.judge == JudgeSpec(model="judge-4", params=(("temperature", "0"),))
    unjudged = _assembled(
        replace(_judged_spec(), judge=None, scorer="inspect_ai.scorer:match", scorer_kwargs={}),
        monkeypatch,
    )
    assert unjudged.judge is None


def test_a_judge_model_kwarg_without_a_declaration_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection must key on the KWARG, not the scorer's name: a custom eval-module
    scorer (frontierscience's shape) carries its judge under a model kwarg while
    matching no model_graded_* name — importing it undeclared shipped a judge
    outside exam identity (review finding, 2026-09-24)."""

    for kwargs in ({"model": None}, {"model": "openai/gpt-4o"}, {"grader_model": "openai/gpt-4o"}):
        spec = _judged_spec(
            scorer="inspect_evals.frontierscience.frontierscience:frontierscience_scorer",
            scorer_kwargs=kwargs,
            judge=None,
        )
        with pytest.raises(ValueError, match="judge"):
            _assembled(spec, monkeypatch)


def test_a_non_gateway_judge_model_value_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judge-model kwarg naming another provider would dial OpenAI directly —
    unmetered, outside the gateway, outside exam identity. Refused by name."""

    spec = _judged_spec(
        scorer_kwargs={"model": "screamingface/judge-4", "grader_model": "openai/gpt-4o"},
    )
    with pytest.raises(ValueError, match="openai/gpt-4o"):
        _assembled(spec, monkeypatch)


@pytest.mark.asyncio
async def test_the_judged_aggregate_runs_its_judge_fetch_on_the_runs_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """INVARIANT (OME-1240): no second loop for judged grading — the run's shared
    HTTP client's pooled connections are bound to the run's own loop, and httpx
    raises "bound to a different event loop" anywhere else (reproduced 2026-09-24)."""

    import asyncio

    seen_loops: list[Any] = []

    class _LoopRecordingJudge(_JudgeEndpoint):
        async def __call__(self, request: Request) -> str:
            seen_loops.append(asyncio.get_running_loop())
            return await super().__call__(request)

    board = _assembled(_judged_spec(), monkeypatch)
    judge = _LoopRecordingJudge()
    node = Url4Node("test")
    node.endpoint("/judge-4")(judge)
    _bake_by_hand(tmp_path, board.benchmark.id)
    board.benchmark.install(node, tmp_path)

    outer = asyncio.get_running_loop()
    rows = json.dumps([_row(1, "Paris.")])
    result = json.loads(await _call(node, board.aggregate_route, rows, "aggregate:1"))
    assert result["cases"][0]["grade"]["score"] == 1.0
    assert seen_loops == [outer]


def test_the_run_sync_twins_stay_verbatim_identical() -> None:
    """The spine's `_run_sync` and single_shot's copy must not diverge — the copy
    exists only because the spine's is private, and a one-sided fix (the context
    copy, the loop discipline) would silently split behavior between the aggregate
    and the check surface."""

    import ast
    import inspect as pyinspect

    from screamingface_engine.benchmarks.spine import scored as spine_scored

    def body_dump(fn: Any) -> str:
        tree = ast.parse(pyinspect.getsource(fn).strip())
        function = tree.body[0]
        assert isinstance(function, ast.FunctionDef)
        # Drop the docstring — wording differs; the CODE must not.
        if isinstance(function.body[0], ast.Expr):
            function.body = function.body[1:]
        return ast.dump(function, include_attributes=False)

    assert body_dump(single_shot._run_sync) == body_dump(spine_scored._run_sync)
