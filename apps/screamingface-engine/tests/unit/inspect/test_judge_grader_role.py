# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Role-based judges — the eval asks for "the grader", our pinned judge answers (OME-1370).

Most inspect judges never name a model: they call ``get_model(role="grader")`` and let
the eval runner decide who grades. Outside inspect's own eval loop nobody fills that
role, so a board row declares ``JudgeSpec(model=..., model_role="grader")`` and the judged
aggregate binds the role to our metered ``screamingface/<model>`` provider for the
grading pass — the same wall socket FrontierScience's named judge plugs into.

INVARIANT the suite defends: an unbound role never dials anyone. The binding is scoped
to one grading pass, a role-based scorer without a declared judge refuses at assembly,
and a judge that fills a model role is exam identity exactly like a named one.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import model_roles  # noqa: E402
from inspect_ai.scorer import model_graded_qa  # noqa: E402

from screamingface_engine.benchmarks.case_execution import case_execution_payload  # noqa: E402
from screamingface_engine.benchmarks.contract import (  # noqa: E402
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.spine.payloads import TextPayload  # noqa: E402
from screamingface_engine.benchmarks.spine.scored import GradeRequest  # noqa: E402
from screamingface_engine.grading_accounting import capture_grading_requests  # noqa: E402
from screamingface_engine.operation_accounting import (  # noqa: E402
    OperationAccounting,
    OperationCache,
    OperationUsage,
)
from screamingface_engine.operation_calls import (  # noqa: E402
    capture_request_accounting,
    operation_call_identity,
    record_operation_call,
)
from screamingface_engine_inspect import boards, single_shot  # noqa: E402
from screamingface_engine_inspect.boards import BoardSpec  # noqa: E402
from screamingface_engine_inspect.envelopes import (  # noqa: E402
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
    judge_filling_model_role,
)
from screamingface_engine_inspect.shim import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Request, Url4Node  # noqa: E402


class _RecordingFetch:
    """A fake node fetch: records every target, answers with a fixed judge reply."""

    def __init__(self, reply: str = "The answer names Paris.\n\nGRADE: C") -> None:
        self.targets: list[str] = []
        self.reply = reply

    async def __call__(self, target: str) -> str:
        self.targets.append(target)
        return self.reply


def _request() -> GradeRequest:
    return GradeRequest(
        case_id=3,
        input=TextPayload(text="What is the capital of France?"),
        answer=TextPayload(text="Paris is the capital of France."),
        row={"case": {"status": "answered"}},
        material={"target": "Paris"},
    )


def _role_spec(**overrides: Any) -> BoardSpec:
    """One minimal model-role row — model_graded_qa naming NO model, so inspect asks
    for its grader role, which the declaration binds to gateway judge-4."""

    values: dict[str, Any] = {
        "key": "gsm8k",  # reuses the real snapshot row; the board caches are patched
        "title": "Role Judged Test Board",
        "description": "test",
        "focus": "test",
        "dataset_url": "https://example.test/ds",
        "difficulty": "easy",
        "scorer": "inspect_ai.scorer:model_graded_qa",
        "scorer_kwargs": {},
        "judge": JudgeSpec(model="judge-4", params=(("temperature", "0"),), model_role="grader"),
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


# ── the provider face: the role resolves to our wall socket, and only in scope ─


@pytest.mark.asyncio
async def test_a_role_based_scorer_grades_through_the_provider_when_the_role_is_bound() -> None:
    """inspect's REAL judge scorer, naming no model, grades via our route once the
    grader role is bound — zero adapter code in the scorer's own path."""

    fetch = _RecordingFetch()
    scorer = model_graded_qa()
    with (
        bound_judge_transport(JudgeTransport(fetch=fetch)),
        judge_filling_model_role("grader", "judge-4"),
    ):
        outcome = await inspect_grade_case(scorer)(_request())
    assert (outcome.score, outcome.failure_code) == (1.0, None)
    assert [target.partition("?")[0] for target in fetch.targets] == ["/judge-4"]


@pytest.mark.asyncio
async def test_the_real_simpleqa_scorer_dials_the_bound_role() -> None:
    """The ticket's first board: SimpleQA's paper scorer asks for the grader role
    by name — its judge call must leave through the declared route."""

    from inspect_evals.simpleqa.scorer import simpleqa_scorer

    fetch = _RecordingFetch(reply="A")
    with (
        bound_judge_transport(JudgeTransport(fetch=fetch)),
        judge_filling_model_role("grader", "judge-4"),
    ):
        await inspect_grade_case(simpleqa_scorer())(_request())
    assert [target.partition("?")[0] for target in fetch.targets] == ["/judge-4"]


@pytest.mark.asyncio
async def test_the_role_binding_is_scoped_to_its_block() -> None:
    """INVARIANT: the next board's grade starts with no grader — a board that
    declares no model-role judge can never ride another board's binding."""

    before: dict[str, Any] = dict(model_roles())
    with judge_filling_model_role("grader", "judge-4"):
        assert str(model_roles()["grader"]) == "screamingface/judge-4"
    assert dict(model_roles()) == before
    assert "grader" not in model_roles()


@pytest.mark.asyncio
async def test_concurrent_role_bindings_stay_per_task() -> None:
    """INVARIANT: two boards grading at once each see their OWN judge. The
    save-and-restore in judge_filling_model_role is only safe because inspect keeps roles
    per task (a ContextVar); were they process-wide, board A would silently grade
    with board B's judge, and A's restore would wipe B's binding mid-grade
    (review finding, 2026-09-29)."""

    import asyncio

    from inspect_ai.model import get_model

    a_bound = asyncio.Event()
    b_bound = asyncio.Event()
    seen: dict[str, str] = {}

    async def board_a() -> None:
        with judge_filling_model_role("grader", "judge-4"):
            a_bound.set()
            await b_bound.wait()
            seen["a"] = str(get_model(role="grader"))

    async def board_b() -> None:
        await a_bound.wait()
        with judge_filling_model_role("grader", "judge-5"):
            b_bound.set()
            await asyncio.sleep(0)
            seen["b"] = str(get_model(role="grader"))

    await asyncio.gather(board_a(), board_b())
    assert seen == {"a": "screamingface/judge-4", "b": "screamingface/judge-5"}


@pytest.mark.asyncio
async def test_an_unbound_grader_role_never_dials_anyone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT (no unmetered judge call): with the role unbound, the scorer's
    judge lookup fails the Case by name — our socket stays silent and no vendor
    is dialed in its place."""

    monkeypatch.delenv("INSPECT_EVAL_MODEL", raising=False)
    fetch = _RecordingFetch()
    with bound_judge_transport(JudgeTransport(fetch=fetch)):
        outcome = await inspect_grade_case(model_graded_qa())(_request())
    assert outcome.score is None
    assert outcome.failure_code == "scorer_error"
    assert fetch.targets == []


# ── assembly: the model-role judge is declared, pinned, and cross-checked ────


def test_a_model_role_judge_assembles_and_rides_the_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _assembled(_role_spec(), monkeypatch)
    assert board.judge == JudgeSpec(
        model="judge-4", params=(("temperature", "0"),), model_role="grader"
    )


def test_a_model_role_boards_revision_moves_with_the_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: a judge that fills a model role is exam identity — swap it, the exam moves."""

    base = str(_assembled(_role_spec(), monkeypatch).benchmark.revision)
    other = str(
        _assembled(
            _role_spec(judge=JudgeSpec(model="judge-5", model_role="grader")), monkeypatch
        ).benchmark.revision
    )
    assert base != other


def test_an_unsupported_role_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the grader role is bound; any other role would resolve to nothing at
    grade time and fail every Case — refuse it at assembly instead."""

    with pytest.raises(ValueError, match="critic"):
        _assembled(_role_spec(judge=JudgeSpec(model="judge-4", model_role="critic")), monkeypatch)


def test_a_model_role_judge_plus_a_dialed_kwarg_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One judge, one path: a scorer that also dials a gateway judge by kwarg would
    grade with that one, leaving the role binding pinned but never called."""

    spec = _role_spec(scorer_kwargs={"model": "screamingface/judge-4"})
    with pytest.raises(ValueError, match="role"):
        _assembled(spec, monkeypatch)


def test_a_scorer_asking_for_a_different_role_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_graded_qa(model_role="judge") asks for a role the board never binds —
    the pinned judge and the called one would drift apart."""

    spec = _role_spec(scorer_kwargs={"model_role": "judge"})
    with pytest.raises(ValueError, match="judge"):
        _assembled(spec, monkeypatch)


def test_a_scorer_told_to_skip_the_role_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """model_role=None tells inspect to ignore roles and grade with its default
    model — a vendor call we never meter, while the revision still pins judge-4.
    The key being PRESENT is the signal, not its value (review finding, 2026-09-29)."""

    spec = _role_spec(scorer_kwargs={"model_role": None})
    with pytest.raises(ValueError, match="role"):
        _assembled(spec, monkeypatch)


def test_a_model_graded_scorer_without_a_judge_points_at_the_role_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal stays for undeclared role-based boards, and now names the fix."""

    with pytest.raises(ValueError, match='model_role="grader"'):
        _assembled(_role_spec(judge=None), monkeypatch)


# ── end to end: the aggregate binds the role, the judge's tokens are accounted ─


def _judge_accounting() -> OperationAccounting:
    return OperationAccounting(
        provider="openrouter",
        request_model="judge-4",
        response_model="judge-4-served",
        usage=OperationUsage(
            input_tokens=120,
            output_tokens=30,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=0,
            cost_usd="0.0042",
        ),
        provider_latency_ms=900,
        provider_attempts=1,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


class _ConnectorFaithfulJudge:
    """A fake judge route that publishes accounting exactly as the connector does:
    identity from the REQUEST's path/params/context/intent, then one terminal call."""

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def __call__(self, request: Request) -> str:
        self.requests.append(request)
        with operation_call_identity(
            request.path, request.params, context=request.context, intent=request.intent
        ):
            record_operation_call("GRADE: C", finish_reason="stop", accounting=_judge_accounting())
        return "The answer matches.\n\nGRADE: C"


def _prepare_by_hand(root: Path, benchmark_id: str) -> None:
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
async def test_a_model_role_boards_judge_is_routed_and_accounted_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ticket's acceptance under one roof: a role-based scorer's judge call
    leaves through the node's judge route with the pinned params, and its tokens
    and cost land in the Case's evidence accounting (the run's usage sink)."""

    board = _assembled(_role_spec(), monkeypatch)
    judge = _ConnectorFaithfulJudge()
    node = Url4Node("test")
    node.endpoint("/judge-4")(judge)
    _prepare_by_hand(tmp_path, board.benchmark.id)
    board.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "Paris is the capital of France.")])
    with capture_request_accounting(), capture_grading_requests():
        result = json.loads(await _call(node, board.aggregate_route, rows, "aggregate:1"))

    assert result["cases"][0]["grade"]["score"] == 1.0
    assert len(judge.requests) == 1
    assert judge.requests[0].params.get("temperature") == "0"
    accounting = result["cases"][0]["grade"]["checks"][0]["evidence"][0]["accounting"]
    assert accounting["usage"]["input_tokens"] == 120
    assert accounting["usage"]["cost_usd"] == "0.0042"
