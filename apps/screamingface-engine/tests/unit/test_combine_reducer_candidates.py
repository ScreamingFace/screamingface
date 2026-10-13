"""SDK-compiled Vote candidates run end to end on the Engine (OME-1289 E4a, unit 5).

FEATURE: a Candidate compiled by ``sf.Fusion(..., synthesizer=sf.Vote(...))`` runs VERBATIM
(``combine_contract/*.url4`` are written by the SDK; its drift guard keeps them current).
STORY: as a researcher, a vote with no usable answer abstains the case (scored 0.0, flagged), a
member failure fails the candidate exactly like a model synthesizer, the grader reads the chosen
member's text byte for byte, two reducers and two turns keep their own evidence.

PRD ids: VT-5 (now the abstain outcome, GE-1), VT-12, VT-13 (IFEval twin), EV-6, EV-13. These are
contract pins: the Engine already delivers the behavior, so they pass on their first run by design.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_corrective_loop_e2e import _assets, _chat
from test_medxpert_protocol_turns import _TRIGGER_MARK, _message_text
from test_medxpert_protocol_turns import _assets as _medxpert_assets

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    CaseResult,
    OperationOutput,
    decode_candidate_invocation_record,
)
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
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


async def _ifeval_case(
    tmp_path: Path, candidate_file: str, replies: _Replies
) -> tuple[dict[str, Any], dict[str, Any]]:
    _assets(tmp_path / "ifeval")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_by_model(replies)), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="prov/member-a",
            models=tuple(ModelSpec(id=m) for m in (*_MEMBERS, "prov/synth")),
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        BenchmarkRegistry((IFEVAL,)).install(world.node, assets_root=tmp_path)
        protocol = IFEVAL.resource(1)["url4"]
        assert isinstance(protocol, str)
        result = await world.node.evaluate(link_candidate(_contract(candidate_file), protocol))
    finally:
        await world.aclose()
        await client.aclose()
    payload = json.loads(result.text)
    return payload, payload["cases"][0]


async def test_no_votes_abstains_the_case(tmp_path: Path) -> None:
    replies: _Replies = dict.fromkeys(_MEMBERS, "tea has no digits")
    result, case = await _ifeval_case(tmp_path, "vote_candidate.url4", replies)
    # An abstain is an answer of "no answer": the case is scored 0.0, not failed (GE-1).
    assert case["status"] == "scored"
    assert case["abstained"] is True
    assert case["output"] == ""
    assert case["grade"]["score"] == 0.0
    assert case["failures"] == []
    assert result["score"] == 0.0
    synthesis = {op["operation_id"]: op for op in case["operations"]}["op_synthesis_1"]
    evidence = synthesis["combine"]
    assert evidence["result"] == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "no_votes",
    }
    assert evidence["dropped"] == 3


async def test_member_failure_fails_candidate_like_model_synthesizer(tmp_path: Path) -> None:
    replies: dict[str, str | httpx.Response] = {
        "prov/member-a": "tea 1",
        "prov/member-b": httpx.Response(400),
        "prov/member-c": "tea 1",
        "prov/synth": "tea 1",
    }
    shapes = []
    for name in ("vote_candidate.url4", "model_synthesizer_candidate.url4"):
        _, case = await _ifeval_case(tmp_path / name, name, replies)
        assert case["status"] == "failed"
        shapes.append(
            [(f["stage"], f["code"], f["retryable"], f["message"]) for f in case["failures"]]
        )
    expected = [
        ("candidate", "aigateway_http_400", False, "aigateway request failed with status 400")
    ]
    assert shapes == [expected, expected]


async def test_ifeval_grades_the_chosen_member_text_verbatim(tmp_path: Path) -> None:
    replies: _Replies = {
        "prov/member-a": "tea is warm 2",
        "prov/member-b": "Tea, maybe 3",
        "prov/member-c": "tea calms 2",
    }
    result, case = await _ifeval_case(tmp_path, "vote_candidate.url4", replies)
    assert case["output"] == "tea is warm 2"
    assert case["status"] == "scored"
    assert result["score"] == 1.0
    operations = {operation["operation_id"]: operation for operation in case["operations"]}
    synthesis = operations["op_synthesis_1"]
    assert synthesis["combine"]["chosen"] == ["member_1"]
    assert synthesis["output"] == replies["prov/member-a"]


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
