"""SDK-compiled Vote candidates run end to end on the Engine (OME-1289 E4a, unit 5).

FEATURE: a Candidate compiled by ``sf.Fusion(..., synthesizer=sf.Vote(...))`` runs VERBATIM
(``combine_contract/*.url4`` are written by the SDK; its drift guard keeps them current).
STORY: as a researcher, two reducers and two turns keep their own evidence.

PRD ids: EV-6, EV-13. These are contract pins: the Engine already delivers the behavior, so they
pass on their first run by design. VT-5, VT-12 and VT-13 graded a vote through IFEval, a local
inspect Task since OME-1527, so they live in ``inspect/test_combine_candidates_on_ifeval.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_medxpert_protocol_turns import _TRIGGER_MARK, _message_text
from test_medxpert_protocol_turns import _assets as _medxpert_assets

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    CaseResult,
    OperationOutput,
    decode_candidate_invocation_record,
)
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world

pytestmark = pytest.mark.asyncio

_CONTRACT = Path(__file__).parent / "data" / "combine_contract"
_MEMBERS = ("prov/member-a", "prov/member-b", "prov/member-c")

type _Replies = Mapping[str, str | httpx.Response]


def _chat(content: str) -> httpx.Response:
    """One chat completion carrying ``content``, as the gateway sends it."""

    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _contract(name: str) -> str:
    # rstrip: the repo's end-of-file hook appends a newline the rendered expression never carries.
    return (_CONTRACT / name).read_text(encoding="utf-8").rstrip("\n")


def _by_model(
    replies: _Replies, seen: list[dict[str, Any]] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        reply = replies[body["model"]]
        return _chat(reply) if isinstance(reply, str) else reply

    return respond


_TWO_REDUCERS = {
    "provider/alpha": "alpha reasons, so 12",
    "provider/beta": "beta says 7",
    "provider/gamma": "gamma agrees: 12.",
    "provider/delta": "Delta thinks.\nParis.",
    "provider/epsilon": "paris",
}


def _tally(operation: OperationOutput) -> list[tuple[str, float, list[str]]]:
    assert operation.combine is not None and operation.combine.tally is not None
    return [(row.value, row.score, row.holders) for row in operation.combine.tally]


async def test_two_reducers_keep_separate_evidence() -> None:
    seen: list[dict[str, Any]] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_by_model(_TWO_REDUCERS, seen)),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha",
            models=tuple(ModelSpec(id=m) for m in _TWO_REDUCERS),
        ),
        client=client,
    )
    try:
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        encoded = await evaluate_candidate_recipe(
            world.node, _contract("two_reducers_candidate.url4"), "What is 6 + 6?"
        )
    finally:
        await world.aclose()
        await client.aclose()

    decoded = decode_candidate_invocation_record(encoded)
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    first, second = by_id["op_synthesis_1"], by_id["op_synthesis_2"]
    assert first.combine is not None and second.combine is not None
    assert first.combine.operators == ["last_number@1", "numeric@1", "mode@1", "first_holder@1"]
    assert _tally(first) == [("12", 2.0, ["member_1", "member_3"]), ("7", 1.0, ["member_2"])]
    assert first.output == _TWO_REDUCERS["provider/alpha"]
    assert second.combine.operators == ["last_line@1", "text@1", "mode@1", "first_holder@1"]
    assert _tally(second) == [("paris", 2.0, ["member_1", "member_2"])]
    assert second.combine.chosen == ["member_1"]
    assert decoded.output == _TWO_REDUCERS["provider/delta"]
    for model in ("provider/delta", "provider/epsilon"):
        [body] = [b for b in seen if b["model"] == model]
        assert _TWO_REDUCERS["provider/alpha"] in json.dumps(body["messages"])
    assert first.combine != second.combine


_COMMIT_REPLIES = {"prov/member-a": "E is 1", "prov/member-b": "E is 2", "prov/member-c": "E is 2"}
_REASONING_REPLIES = {
    "prov/member-a": "reason 3",
    "prov/member-b": "reason 3",
    "prov/member-c": "reason 8",
}


def _assert_second_turn_evidence(case: CaseResult) -> None:
    assert case.operations is not None
    by_id = {operation.operation_id: operation for operation in case.operations}
    evidence = by_id["op_synthesis_1"].combine
    assert evidence is not None and evidence.tally is not None
    values = [row.value for row in evidence.tally]
    assert values == ["2", "1"]
    assert "3" not in values
    assert evidence.chosen == ["member_2"]
    assert by_id["op_model_1"].output == "E is 1"


async def test_multi_turn_case_keeps_second_turn_evidence(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        commit = _TRIGGER_MARK in _message_text(body)
        return _chat((_COMMIT_REPLIES if commit else _REASONING_REPLIES)[body["model"]])

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="prov/member-a", models=tuple(ModelSpec(id=m) for m in _MEMBERS)
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        BenchmarkRegistry((MEDXPERT,)).install(
            world.node, assets_root=_medxpert_assets(tmp_path, 1)
        )
        result = await world.node.evaluate(
            link_candidate(_contract("vote_candidate.url4"), MEDXPERT.build(1))
        )
    finally:
        await world.aclose()
        await client.aclose()

    # 3 members x 2 turns: the reasoning turn ran too, so "second turn wins" is not vacuous.
    assert len(seen) == 6
    _assert_second_turn_evidence(CandidateResult.model_validate(json.loads(result.text)).cases[0])
