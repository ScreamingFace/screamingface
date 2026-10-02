"""An SDK-written judge-weighted vote runs in the engine world (OME-1289 E4a, unit 8S, SR#11).

FEATURE: ``sf.Vote(weights=sf.signal("score:judge"), judge=sf.Judge(..., returns="scores"))``
compiles to a judge model call plus a weighted-vote combine step that reads the judge's scores.
STORY: as a researcher, the vote follows the judge's scores, not the head count: two members agree
on 12, but the judge trusts the one member that says 7, and 7 wins.
INVARIANT defended: the judge call is paid once, its ``binding`` param never reaches the gateway,
and the Report reads the scores in ``members[].signals`` and ``weight`` (the vote has no
``evidence.judge``).

The data file under ``data/combine_contract/`` is what the SDK compiles (the SDK drift guard keeps
it byte-equal), so this runs the real compiler output. This is a CHAR test: it passes on its first
run by design (unit 8E delivers the behavior).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_samples_seed_contract import _wrapped_candidate

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run

_CANDIDATE = (
    (Path(__file__).parent / "data" / "combine_contract" / "judge_vote_candidate.url4")
    .read_text(encoding="utf-8")
    .removesuffix("\n")
)
_ANSWERS = {
    "prov/alpha": "alpha says 12",
    "prov/beta": "beta says 7",
    "prov/gamma": "gamma says 12",
    "prov/judge": json.dumps({"member_1": 1, "member_2": 5, "member_3": 3}),
}
_JUDGE_PREFIX = "judge-template@1 returns=scores"


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


async def _run() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bodies: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return _chat(_ANSWERS[body["model"]])

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="prov/alpha", models=tuple(ModelSpec(id=model) for model in _ANSWERS)
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        with request_scope(RequestScope(origin="run")):
            result = await url4_run(_wrapped_candidate(_CANDIDATE), io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    record: dict[str, Any] = json.loads(result)
    return bodies, record


def _operation(record: dict[str, Any], operation_id: str) -> dict[str, Any]:
    return next(op for op in record["operations"] if op["operation_id"] == operation_id)


@pytest.mark.asyncio
async def test_sdk_judge_weighted_vote_runs_in_the_engine_world() -> None:
    bodies, record = await _run()

    synthesis = _operation(record, "op_synthesis_1")
    assert synthesis["output"] == "beta says 7"
    combine = synthesis["combine"]
    tally = [(row["value"], row["score"], row["holders"]) for row in combine["tally"]]
    assert tally == [("7", 5.0, ["member_2"]), ("12", 4.0, ["member_1", "member_3"])]
    assert [member["signals"] for member in combine["members"]] == [
        {"score:judge": 1.0},
        {"score:judge": 5.0},
        {"score:judge": 3.0},
    ]
    assert [member["weight"] for member in combine["members"]] == [1.0, 5.0, 3.0]
    assert combine["signal"] == {"key": "score:judge", "order": None}
    assert combine["judge"] is None
    assert combine["presentation_order"] == "author"
    assert combine["chosen"] == ["member_2"]
    assert _operation(record, "op_judge_1")["output"] == _ANSWERS["prov/judge"]
    # one judge call, and the attribution param never reaches the gateway
    judge_calls = [body for body in bodies if body["model"] == "prov/judge"]
    assert len(judge_calls) == 1
    assert all("binding" not in body for body in bodies)
    system = judge_calls[0]["messages"][0]
    assert system["role"] == "system"
    # WHY U+2028: url4 carries a newline of the intent text as a line separator
    assert system["content"].startswith(f"{_JUDGE_PREFIX}\u2028You are a judge.")
