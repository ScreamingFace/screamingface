# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Judge observability — what a reader of the report can see about the judge (OME-1240).

The paid live run is read through the report: per-case evidence must say what the
judge cost (tokens, USD, latency, attempts — via the run's existing payload-free
grading join), and the engine log must say which Case a judge round trip belonged
to. This suite pins both, plus the join's absence on string-match boards.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.benchmarks.case_execution import case_execution_payload  # noqa: E402
from screamingface_engine.benchmarks.contract import (  # noqa: E402
    encode_candidate_invocation,
)
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
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Request, Url4Node  # noqa: E402


def _judged_spec(**overrides: Any) -> BoardSpec:
    values: dict[str, Any] = {
        "key": "gsm8k",  # reuses the real snapshot row; the board caches are patched
        "title": "Judged Observability Board",
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
    monkeypatch.setattr(boards, "BOARDS", (spec,))
    monkeypatch.setattr(boards, "_ASSEMBLED", {})
    monkeypatch.setattr(single_shot, "_BOARDS_BY_ID", {})
    return boards.imported_board(spec.key)


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
async def test_judge_cost_lands_in_the_cases_evidence_accounting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole join under one roof: the judge call registers itself against its
    Case's evidence, the run's payload-free ledger records the call, and the
    shared finalizer writes tokens/USD/latency into that evidence's accounting."""

    board = _assembled(_judged_spec(), monkeypatch)
    judge = _ConnectorFaithfulJudge()
    node = Url4Node("test")
    node.endpoint("/judge-4")(judge)
    _bake_by_hand(tmp_path, board.benchmark.id)
    board.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "Paris is the capital of France.")])
    with capture_request_accounting(), capture_grading_requests():
        result = json.loads(await _call(node, board.aggregate_route, rows, "aggregate:1"))

    evidence = result["cases"][0]["grade"]["checks"][0]["evidence"][0]
    accounting = evidence["accounting"]
    assert accounting is not None
    assert accounting["usage"]["input_tokens"] == 120
    assert accounting["usage"]["output_tokens"] == 30
    assert accounting["usage"]["cost_usd"] == "0.0042"
    assert accounting["provider_latency_ms"] == 900


@pytest.mark.asyncio
async def test_a_string_match_boards_evidence_accounting_stays_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No judge call, no accounting — the join must not invent one."""

    board = _assembled(
        _judged_spec(judge=None, scorer="inspect_ai.scorer:match", scorer_kwargs={}),
        monkeypatch,
    )
    node = Url4Node("test")
    _bake_by_hand(tmp_path, board.benchmark.id)
    board.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "ANSWER: Paris")])
    with capture_request_accounting(), capture_grading_requests():
        result = json.loads(await _call(node, board.aggregate_route, rows, "aggregate:1"))

    evidence = result["cases"][0]["grade"]["checks"][0]["evidence"][0]
    assert evidence["accounting"] is None
