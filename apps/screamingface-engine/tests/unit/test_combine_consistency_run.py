"""The SDK-compiled consistency Pick runs offline in the Engine world (E4b part 7 unit 4, CA#7).

FEATURE: ``combine_contract/consistency_pick_candidate.url4`` (F1, written by the SDK drift guard
ST/test_consistency_contract_fixtures.py) runs through url4 and a mocked gateway. Each member makes
three sample calls with its own seed; the combine step counts the samples that match the member's
answer and picks the most consistent member.
STORY: as a benchmark author, a sample call that fails costs one sample, not the Case.
INVARIANT defended: a failed sample drops its optional slot from the member's sample panel
(quorum 0), so the Case does not fail (ans:Q4); each sample request carries its own seed and the
stated temperature and never the binding param (ans:Q3, SC-I2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from _signal_world import operation
from test_samples_seed_contract import _wrapped_candidate

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run

_FIXTURE = Path(__file__).parent / "data" / "combine_contract" / "consistency_pick_candidate.url4"
_MEMBERS = ("prov/alpha", "prov/beta", "prov/gamma")
_MEMBER_TEXTS = {"prov/alpha": "B", "prov/beta": "C", "prov/gamma": "A"}
# sample seed s(k, j) of erd §2 -> (model, reply): the fixture W texts of consistency-value §3.
_SAMPLE_TEXTS: dict[int, tuple[str, str]] = {
    2063835758: ("prov/alpha", "A"),
    10968804: ("prov/alpha", "B"),
    1079774124: ("prov/alpha", "b"),
    966517312: ("prov/beta", "A"),
    107840383: ("prov/beta", "A"),
    1732381022: ("prov/beta", "c d"),
    1073252422: ("prov/gamma", "a"),
    137802004: ("prov/gamma", "A."),
    992611152: ("prov/gamma", "A"),
}
_FAILED_SEED = 137802004  # gamma sample 2: binding model_11
_DECLARED = {
    "cons": {
        "match": {
            "extract": {"args": {}, "op": "last_line@1"},
            "normalize": {"args": {}, "op": "text@1"},
        },
        "n": 3,
        "source": "consistency",
        "temperature": 1.0,
    }
}
_ALPHA_COUNT = {"member_id": "member_1", "matched": 2, "succeeded": 3, "failed": 0}
_BETA_COUNT = {"member_id": "member_2", "matched": 0, "succeeded": 3, "failed": 0}


def _candidate() -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    assert _FIXTURE.exists(), f"combine_contract/{_FIXTURE.name} is missing - write it with the SDK"
    return _FIXTURE.read_text(encoding="utf-8").removesuffix("\n")


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


class _Gateway:
    """Answers a member call by its model and a sample call by its own seed (order-free)."""

    def __init__(self, failing_seed: int | None) -> None:
        self.bodies: list[dict[str, Any]] = []
        self._failing_seed = failing_seed

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        seed = body.get("seed")
        if seed is None:
            return _chat(_MEMBER_TEXTS[body["model"]])
        if seed == self._failing_seed:
            return httpx.Response(400, json={"error": {"message": "bad"}})
        return _chat(_SAMPLE_TEXTS[seed][1])


async def _run(failing_seed: int | None) -> tuple[_Gateway, dict[str, Any]]:
    gateway = _Gateway(failing_seed)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=_MEMBERS[0], models=tuple(ModelSpec(id=model) for model in _MEMBERS)
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        with request_scope(RequestScope(origin="run")):
            result = await url4_run(_wrapped_candidate(_candidate()), io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    record: dict[str, Any] = json.loads(result)
    return gateway, record


def _assert_answered(record: dict[str, Any]) -> None:
    assert record["status"] == "completed"
    assert record["output"] == "A"
    assert record.get("abstained", False) is False


def _assert_bodies(gateway: _Gateway) -> None:
    """3 member calls with no seed and no temperature; 9 sample calls (ans:Q3)."""
    assert len(gateway.bodies) == 12
    members = [body for body in gateway.bodies if "seed" not in body]
    samples = [body for body in gateway.bodies if "seed" in body]
    assert sorted(body["model"] for body in members) == list(_MEMBERS)
    assert all("temperature" not in body for body in members)
    assert sorted(body["seed"] for body in samples) == sorted(_SAMPLE_TEXTS)
    assert all(body["temperature"] == 1.0 for body in samples)
    assert all(body["model"] == _SAMPLE_TEXTS[body["seed"]][0] for body in samples)
    assert all("binding" not in body for body in gateway.bodies)


def _assert_pick(combine: dict[str, Any]) -> None:
    """The fixture W evidence of consistency-value §3 (CV-2)."""
    assert combine["chosen"] == ["member_3"]
    assert combine["signal"] == {"key": "cons", "order": "max"}
    assert [member["signals"] for member in combine["members"]] == [
        {"cons": 0.6666666666666666},
        {"cons": 0.0},
        {"cons": 1.0},
    ]
    assert combine["declared"] == _DECLARED
    assert (combine["result"]["member_id"], combine["result"]["status"]) == (
        "member_3",
        "answered",
    )


# No `-> None`: with it, the PRD test name does not fit in the 100-character line (ruff E501).
@pytest.mark.asyncio
async def test_the_engine_runs_the_consistency_pick_and_a_failed_sample_does_not_fail_the_case():
    gateway, record = await _run(failing_seed=None)
    _assert_answered(record)
    _assert_bodies(gateway)
    combine = operation(record, "op_synthesis_1")["combine"]
    _assert_pick(combine)
    gamma = {"member_id": "member_3", "matched": 3, "succeeded": 3, "failed": 0}
    assert combine["consistency"] == {"cons": [_ALPHA_COUNT, _BETA_COUNT, gamma]}
    assert operation(record, "op_model_4")["output"] == "A"

    # ans:Q4: the gamma sample of seed 137802004 fails; the value is over the 2 successes.
    gateway, record = await _run(failing_seed=_FAILED_SEED)
    _assert_answered(record)
    _assert_bodies(gateway)
    assert operation(record, "op_model_11")["output"] is None
    combine = operation(record, "op_synthesis_1")["combine"]
    _assert_pick(combine)
    gamma = {"member_id": "member_3", "matched": 2, "succeeded": 2, "failed": 1}
    assert combine["consistency"] == {"cons": [_ALPHA_COUNT, _BETA_COUNT, gamma]}
