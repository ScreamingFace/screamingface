"""C8 attempt facts of the direct `/route-answer` entry and of bound calls (Unit 5.2).

FEATURE: Router Recipe extension. The direct named-profile entry opens one private attempt scope
per invocation with a `classifier` and a `branch` slot; a model call carrying `binding=` publishes
its fact to the active recorder scopes beside the operation-call records.

INVARIANT: a fact exists only for a role that made an Engine attempt; preflight reads are not
attempts; a scope takes no write once closed and is never seen by a concurrent invocation; the
public body, the operation-call records and the retry rules are unchanged.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from routing_support import (
    CALLER,
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    DETAILS_PATH,
    LABELS,
    MODELS,
    PUBLIC,
    Gateway,
    chat_answer,
    run_direct,
    scores,
    world_config,
)

from screamingface_engine.operation_calls import (
    AttemptFact,
    capture_operation_calls,
    current_attempt_facts,
    latest_attempt_fact,
)
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world import attempt_facts
from screamingface_engine.world.factory import build_world
from url4.core.errors import ResolutionError
from url4.wire.subrequest import encode_subrequest

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_HEADER = "X-AIGW-Upstream-Attempts"


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, AttemptFact]]]:
    closed: list[dict[str, AttemptFact]] = []
    monkeypatch.setattr(attempt_facts, "_direct_sink", lambda facts: closed.append(dict(facts)))
    yield closed


def _classified(count: str | None = "1", top: str = "code") -> httpx.Response:
    body = {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": scores(top),
    }
    return httpx.Response(200, json=body, headers={} if count is None else {_HEADER: count})


def _chatted(model: str, count: str | None = "1") -> httpx.Response:
    headers = {} if count is None else {_HEADER: count}
    return httpx.Response(200, json=chat_answer(model), headers=headers)


def _gateway(classifier: str | None = "1", branch: str | None = "1") -> Gateway:
    gateway = Gateway(top="code")
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = _classified(classifier)
    gateway.script[(CHAT_PATH, MODELS["code"])] = _chatted(MODELS["code"], branch)
    return gateway


def _fact(
    role: str, status: str, code: str | None, engine: int, upstream: int | None, billed: bool
) -> AttemptFact:
    return AttemptFact(role, status, code, engine, upstream, billed)  # type: ignore[arg-type]


# --- the direct entry's private scope -------------------------------------------------------------


async def test_a_routed_answer_leaves_one_fact_per_role(sink: list[dict[str, AttemptFact]]) -> None:
    outcome = await run_direct(_gateway("1", "2"))

    assert outcome.error is None
    assert sink == [
        {
            "classifier": _fact("classifier", "answered", None, 1, 1, True),
            "branch": _fact("branch", "answered", None, 1, 2, True),
        }
    ]


async def test_the_public_body_carries_no_fact(sink: list[dict[str, AttemptFact]]) -> None:
    document = (await run_direct(_gateway())).document()

    assert set(document) == {
        "object",
        "contract",
        "profile",
        "revision",
        "policy",
        "classification",
        "selected",
        "answer",
    }
    assert "attempts" not in json.dumps(document)


async def test_a_preflight_refusal_leaves_both_slots_empty(
    sink: list[dict[str, AttemptFact]],
) -> None:
    gateway = _gateway()
    gateway.script[(DETAILS_PATH, CLASSIFIER)] = httpx.Response(404, json={"detail": "no"})

    outcome = await run_direct(gateway)

    assert outcome.code() == "routing_profile_not_found"
    assert sink == [{}]


async def test_a_classifier_refusal_is_a_failed_classifier_fact_and_no_branch_fact(
    sink: list[dict[str, AttemptFact]],
) -> None:
    gateway = _gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(
        422, json={"detail": {"code": "x", "message": "m"}}, headers={_HEADER: "0"}
    )

    outcome = await run_direct(gateway)

    assert outcome.code() == "aigateway_http_422"
    assert sink == [
        {"classifier": _fact("classifier", "failed", "aigateway_http_422", 1, 0, False)}
    ]


async def test_a_branch_failure_keeps_the_classifier_fact(
    sink: list[dict[str, AttemptFact]],
) -> None:
    gateway = _gateway()
    gateway.script[(CHAT_PATH, MODELS["code"])] = httpx.Response(
        400, json={"detail": {"code": "x", "message": "m"}}, headers={_HEADER: "1"}
    )

    await run_direct(gateway)

    (facts,) = sink
    assert facts["classifier"].status == "answered"
    assert facts["branch"] == _fact("branch", "failed", "aigateway_http_400", 1, 1, True)


async def test_a_missing_header_is_unknown(sink: list[dict[str, AttemptFact]]) -> None:
    await run_direct(_gateway(classifier=None, branch=None))

    (facts,) = sink
    assert facts["classifier"].upstream_attempts is None
    assert facts["branch"].upstream_attempts is None
    assert facts["branch"].possibly_billed is True


async def test_a_policy_refusal_leaves_no_branch_fact(sink: list[dict[str, AttemptFact]]) -> None:
    gateway = _gateway()
    tie = [{"label": label, "score": 0.5 if label != "math" else 0.0} for label in LABELS]
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = lambda _: {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": tie,
    }

    outcome = await run_direct(gateway)

    assert outcome.code() == "routing_ambiguous"
    assert list(sink[0]) == ["classifier"]


async def test_concurrent_invocations_never_share_a_scope(
    sink: list[dict[str, AttemptFact]],
) -> None:
    await asyncio.gather(run_direct(_gateway("1", "1")), run_direct(_gateway("3", "3")))

    counts = sorted(
        (facts["classifier"].upstream_attempts, facts["branch"].upstream_attempts) for facts in sink
    )
    assert counts == [(1, 1), (3, 3)]


async def test_a_cancelled_branch_leaves_no_branch_fact_and_no_late_write(
    sink: list[dict[str, AttemptFact]],
) -> None:
    gateway = _gateway()
    gateway.hold = CHAT_PATH
    task = asyncio.create_task(run_direct(gateway))
    await asyncio.wait_for(gateway.held.wait(), 5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    assert sink == [{"classifier": _fact("classifier", "answered", None, 1, 1, True)}]


# --- the recorder channel of a bound call ---------------------------------------------------------


async def _bound_chat(gateway: Gateway, params: tuple[tuple[str, str], ...]) -> list[Any]:
    """One direct chat run of the public route inside an operation-call capture scope."""
    target = encode_subrequest(f"/{PUBLIC}", "hello", None, params)
    async with gateway.client() as client:
        node, aclose = await build_world(env={}, config=world_config(), client=client)
        try:
            with (
                request_scope(RequestScope(origin="sync", identity_headers=CALLER)),
                capture_operation_calls() as calls,
            ):
                try:
                    async for _ in Url4Executor(node, run_shape="direct").execute(target):
                        pass
                except ResolutionError:
                    pass
                facts = current_attempt_facts()
                latest = latest_attempt_fact("model_1")
        finally:
            if aclose is not None:
                await aclose()
    return [calls, facts, latest]


async def test_a_bound_call_publishes_its_fact_beside_the_operation_call() -> None:
    gateway = Gateway()
    gateway.script[(CHAT_PATH, PUBLIC)] = _chatted(PUBLIC, "2")

    calls, facts, latest = await _bound_chat(gateway, (("binding", "model_1"),))

    assert len(calls) == 1
    assert facts == (AttemptFact("model_1", "answered", None, 1, 2, True),)
    assert latest == facts[0]
    assert latest.document() == {
        "binding": "model_1",
        "status": "answered",
        "code": None,
        "engine_attempts": 1,
        "upstream_attempts": 2,
        "possibly_billed": True,
    }


async def test_a_failed_bound_call_publishes_a_failed_fact() -> None:
    gateway = Gateway()
    gateway.script[(CHAT_PATH, PUBLIC)] = httpx.Response(
        502, json={"detail": {"code": "x", "message": "m"}}, headers={_HEADER: "1"}
    )

    _, facts, _ = await _bound_chat(gateway, (("binding", "model_1"),))

    assert facts == (AttemptFact("model_1", "failed", "aigateway_http_502", 1, 1, True),)


async def test_an_unbound_call_publishes_no_fact() -> None:
    gateway = Gateway()

    calls, facts, latest = await _bound_chat(gateway, ())

    assert len(calls) == 1
    assert (facts, latest) == ((), None)


async def test_a_gateway_refusal_fact_keeps_the_status_code_not_the_body_code(
    sink: list[dict[str, AttemptFact]],
) -> None:
    gateway = _gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(
        422, json={"detail": {"code": "provider_error", "message": "m"}}, headers={_HEADER: "1"}
    )

    outcome = await run_direct(gateway)

    assert sink[0]["classifier"].code == outcome.code() == "aigateway_http_422"
