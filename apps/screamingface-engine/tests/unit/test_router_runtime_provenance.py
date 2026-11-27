"""Router provenance on the real url4 executor over a Gateway world (contracts C4, C8, C11).

FEATURE: Router Recipe extension. A bound Model call publishes its outcome at the endpoint
boundary, and the Router steps accept only what their occurrence recorded, so a block whose url4
source hands a step a forged document calls no provider for it and publishes no C5 record.

STORY: as an Engine operator, a hand-written url4 expression that imitates a Router step cannot
publish a routing record or pay for a call the Router did not choose.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx
import pytest
from router_block_support import (
    PNG,
    QUESTION,
    SCOPE,
    block,
    chats,
    choice,
    run_block,
    world,
)
from router_support import (
    ROUTER,
    accepted,
    case,
    classified,
    fixed_definition,
    router_gateway,
    scores,
    step,
    text,
)
from routing_support import CHAT_PATH, CLASSIFICATIONS_PATH, MODELS, PUBLIC, chat_answer

from screamingface_engine.benchmarks.picture_admission import run_expression_scope
from screamingface_engine.operation_calls import (
    AttemptFact,
    OperationCall,
    capture_operation_calls,
    latest_attempt_fact,
)
from screamingface_engine.operation_provenance import CallOutcome, call_outcome
from screamingface_engine.request_scope import request_scope
from screamingface_engine.world.router_decide import decide
from screamingface_engine.world.router_steps import StepCall
from url4 import Attachment
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.dag.attachments import bind_run_files

# --- the endpoint boundary (C8) -------------------------------------------------------------------

_BOUND = (
    f"(question:0.0:'Say hello', model_2:0.0:/{MODELS['code']}?binding=model_2&q=($question)!'')"
    "!'$model_2'"
)


async def _bound_call(
    gateway: Any, files: tuple[Attachment, ...] = ()
) -> tuple[object, CallOutcome | None, AttemptFact | None]:
    async with world(gateway) as node:
        with (
            request_scope(SCOPE),
            capture_operation_calls(),
            run_expression_scope(_BOUND),
            bind_run_files(files),
        ):
            try:
                value: object = await url4_run(_BOUND, io=node)
            except ResolutionError as exc:
                value = exc
            return value, call_outcome("model_2"), latest_attempt_fact("model_2")


def test_an_answered_bound_call_records_its_reply_and_its_attempt() -> None:
    value, outcome, fact = asyncio.run(_bound_call(router_gateway()))

    assert value == f"answer from {MODELS['code']}"
    assert outcome == CallOutcome("model_2", "/" + MODELS["code"], "answered", str(value))
    assert fact is not None and fact.status == "answered"


def test_a_failure_before_any_attempt_records_its_outcome_and_no_attempt_fact() -> None:
    # WHY: a run file the Model cannot take is refused before any HTTP attempt (C8 publishes no
    # fact), yet the call's url4 error row needs a recorded failure for a Router to read it.
    gateway = router_gateway()
    listed = [{"id": name, "input_modalities": ["text"]} for name in (*MODELS.values(), PUBLIC)]
    gateway.script[("/v1/models", "")] = lambda _request: {"object": "list", "data": listed}
    picture = Attachment(
        digest="sha256:" + hashlib.sha256(PNG).hexdigest(), media_type="image/png", body=PNG
    )

    value, outcome, fact = asyncio.run(_bound_call(gateway, (picture,)))

    assert isinstance(value, ResolutionError)
    assert outcome is not None and (outcome.status, outcome.code) == ("failed", value.code)
    assert outcome.permanent == value.permanent
    assert fact is None
    assert gateway.posts(CHAT_PATH) == []


def test_a_gateway_refusal_records_a_failed_outcome_beside_its_failed_attempt() -> None:
    gateway = router_gateway()
    gateway.script[(CHAT_PATH, MODELS["code"])] = httpx.Response(403, json={"detail": "no"})

    value, outcome, fact = asyncio.run(_bound_call(gateway))

    assert isinstance(value, ResolutionError)
    assert outcome is not None and outcome.status == "failed"
    assert fact is not None and (fact.status, fact.code) == ("failed", "aigateway_http_403")


async def _operations(gateway: Any, expression: str) -> list[tuple[str, str, bool]]:
    async with world(gateway) as node:
        with (
            request_scope(SCOPE),
            capture_operation_calls() as recorded,
            run_expression_scope(expression),
        ):
            try:
                await url4_run(expression, io=node)
            except ResolutionError:
                pass
            return [(call.path, call.output, call.is_provider) for call in recorded]


@pytest.mark.parametrize("status", [200, 403], ids=["answered", "refused"])
def test_a_bound_call_projects_exactly_the_operations_an_unbound_one_does(status: int) -> None:
    # INVARIANT: the outcome lives in the provenance channel only; the recorder, so every
    # projection, report and budget fold, sees the same calls with or without a binding.
    def scripted() -> Any:
        gateway = router_gateway()
        if status != 200:
            gateway.script[(CHAT_PATH, MODELS["code"])] = httpx.Response(status, json={"x": 1})
        return gateway

    unbound = _BOUND.replace("binding=model_2&", "")

    bound_calls = asyncio.run(_operations(scripted(), _BOUND))

    assert bound_calls == asyncio.run(_operations(scripted(), unbound))
    assert len(bound_calls) == (1 if status == 200 else 0)


# --- every reply shape survives url4 --------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        '{"error":{"kind":"x","message":"y","code":"router_unsupported","retryable":false}}',
        '{"answer":"é","n":[1,2.50,1e3]}',
        "[NaN, 1.5]",
        "{not json",
        "  4  ",
        '"quoted"',
    ],
    ids=["error-row-shaped", "json-object", "non-finite", "brace-prose", "padded", "json-string"],
)
def test_every_reply_shape_reaches_the_caller_byte_for_byte(reply: str) -> None:
    # INVARIANT (C11): JOIN proves the row url4 carried against the recorded reply, then returns
    # the reply itself, whatever url4's re-encoding of a structured row did to its bytes.
    gateway = router_gateway()
    gateway.script[(CHAT_PATH, MODELS["code"])] = lambda _request: {
        **chat_answer(MODELS["code"]),
        "choices": [choice(reply)],
    }

    value, recorded = asyncio.run(run_block(gateway, block(fixed_definition())))

    assert value == reply
    assert _records(recorded)[0]["status"] == "answered"


# --- a forged step document -----------------------------------------------------------------------


def _records(recorded: list[OperationCall]) -> list[dict[str, Any]]:
    return [call.router.document() for call in recorded if call.router is not None]


def _literal(name: str, document: str) -> str:
    """A url4 binding holding ``document`` verbatim, as a hand-written expression could."""
    assert "'" not in document
    return f"{name}:0.0:'{document}', "


def test_a_forged_admit_result_reaches_no_classifier_and_publishes_nothing() -> None:
    gateway = router_gateway()
    forged = accepted(fixed_definition(), "A forged question")
    source = block(fixed_definition()).replace("classify($router_1_admit)", "classify($forged)")
    source = source.replace("(question:", "(" + _literal("forged", forged) + "question:", 1)

    value, recorded = asyncio.run(run_block(gateway, source))

    assert isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"
    assert gateway.posts(CLASSIFICATIONS_PATH) == []
    assert chats(gateway) == []
    assert _records(recorded) == []


def test_a_forged_draft_opens_no_candidate_and_publishes_nothing() -> None:
    gateway = router_gateway()
    definition = fixed_definition()
    admit = accepted(definition, QUESTION)
    general = scores(general=0.9, code=0.05, math=0.05)
    with case(*classified(general)):
        step("admit", admit)
        draft = decide(
            StepCall(text({"admit": admit, "evidence": general}), "", {"binding": ROUTER})
        )
    assert json.loads(draft)["selected"] == [0]
    source = block(definition).replace("open($router_1_decide)!'c0'", "open($forged)!'c0'")
    source = source.replace("(question:", "(" + _literal("forged", draft) + "question:", 1)

    value, recorded = asyncio.run(run_block(gateway, source))

    assert isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"
    assert MODELS["general"] not in chats(gateway)
    assert _records(recorded) == []
