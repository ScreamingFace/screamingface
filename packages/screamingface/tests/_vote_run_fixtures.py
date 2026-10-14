"""Shared helpers for the sf.Vote / sf.Median evaluation tests (not a test module; OME-1289 gap).

STORY: a researcher evaluates a deterministic reducer through a real ``sf.Client``; these helpers
script the Engine (benchmark resources, operator catalog) and the run transport.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from _answer_fixtures import evidence_wires
from _combine_contract import ENGINE_OPERATOR_NAMES, operators_wire
from test_client_run import BENCHMARK, _engine
from test_operation_accounting_decode import _accounting_wire
from url4 import Expression, build

from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.combine_spec import decode_combine_spec
from screamingface._evaluation.model import Candidate
from screamingface.url4 import _calls, _candidate_expression


def benchmark_resource(
    benchmark_id: str, *, answer_rule: dict[str, Any] | None = None, case_count: int = 1
) -> dict[str, Any]:
    """``GET /v1/benchmarks/<id>``: the draco fixture under another id, with the rule when given."""

    resource = copy.deepcopy(BENCHMARK)
    resource["id"] = benchmark_id
    resource["case_count"] = case_count
    if answer_rule is not None:
        resource["answer_rule"] = copy.deepcopy(answer_rule)
    return resource


def engine_handler(
    events: list[str],
    *,
    resources: Mapping[str, Mapping[str, Any]],
    operators: Mapping[str, Sequence[str]] = ENGINE_OPERATOR_NAMES,
) -> Callable[[httpx.Request], httpx.Response]:
    """A scripted Engine: models, model parameters, ``/v1/operators`` and the given benchmarks.

    Every request path is appended to ``events`` so a test can read the order and the count.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        events.append(path)
        if path == "/v1/operators":
            return httpx.Response(
                200,
                json=operators_wire(operators),
                headers={"ETag": '"v1"', "Cache-Control": "public, max-age=300, must-revalidate"},
            )
        benchmark_id = path.removeprefix("/v1/benchmarks/")
        if path.startswith("/v1/benchmarks/") and benchmark_id in resources:
            return httpx.Response(200, json=resources[benchmark_id])
        return _engine(request)

    return handle


class ScriptedTransport:
    """A run transport that returns scripted cases for the Candidate it is asked to run."""

    def __init__(
        self,
        benchmark_id: str,
        revision: str,
        cases_for: Callable[[Candidate], list[dict[str, Any]]],
        events: list[str] | None = None,
    ) -> None:
        self.candidate: Candidate | None = None
        self._benchmark_id = benchmark_id
        self._revision = revision
        self._cases_for = cases_for
        self._events = events

    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        del on_event
        self.candidate = candidate
        if self._events is not None:
            self._events.append("RUN")
        cases = self._cases_for(candidate)
        when = datetime(2026, 10, 2, tzinfo=UTC)
        return _RunOutcome(
            run_id="vote-run",
            started_at=when,
            completed_at=when,
            result_body=json.dumps(
                {
                    "schema": "screamingface.candidate-result.v1",
                    "benchmark_id": self._benchmark_id,
                    "benchmark_revision": self._revision,
                    "case_count": len(cases),
                    "score": 1.0,
                    "coverage": 1.0,
                    "metrics": {},
                    "cases": cases,
                    "failures": [],
                }
            ),
            media_type="application/json",
            root_usage=None,
        )

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


def case_wire(output: str, operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "status": "scored",
        "case_id": 1,
        "input": "Fixture question",
        "output": output,
        "finish_reason": "stop",
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": {"method": "fixture", "score": 1.0, "metrics": {}, "checks": []},
        "failures": [],
        "metadata": {},
    }
    if operations is not None:
        wire["operations"] = operations
    return wire


def spec_of(url4: str) -> dict[str, object]:
    """The combine spec a (possibly benchmark-linked) Candidate url4 carries."""

    candidate, _ = _candidate_expression(build(url4))
    assert isinstance(candidate, Expression)
    return decode_combine_spec(_calls(candidate)["synthesis_1"].raw_intent)


def operation_wire(
    op_id: str,
    output: str,
    *,
    accounting: dict[str, Any] | None = None,
    combine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "operation_id": op_id,
        "output": output,
        "finish_reason": "stop",
        "accounting": accounting,
    }
    if combine is not None:
        wire["combine"] = combine
    return wire


def vote_case(
    texts: Sequence[str],
    evidence_name: str,
    *,
    model_ops: Sequence[str],
    output: str,
    models: Sequence[str] = (),
    synthesis_id: str = "op_synthesis_1",
) -> dict[str, Any]:
    """A scored Case of a Fusion: one operation per model call, then the combine step.

    ``texts`` aligns with ``model_ops``. ``output`` is the combine step's output, given by the
    test (which member it names depends on the evidence). With ``models`` (one request model per
    model call) each model operation carries accounting; without it none does.
    """

    assert not models or len(models) == len(model_ops), "one request model per model call"
    evidence = copy.deepcopy(evidence_wires()[evidence_name])
    operations = [
        operation_wire(
            op_id,
            text,
            accounting=_accounting_wire(request_model=models[index]) if models else None,
        )
        for index, (op_id, text) in enumerate(zip(model_ops, texts, strict=True))
    ]
    operations.append(operation_wire(synthesis_id, output, combine=evidence))
    return case_wire(output, operations)
