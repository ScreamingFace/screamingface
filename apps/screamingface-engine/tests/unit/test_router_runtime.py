"""The Router runtime on a Gateway world (contracts C4, C8, C11; Unit 5.2).

FEATURE: Router Recipe extension. Every Gateway world serves the five Router steps after its
direct-mount snapshot, with or without Benchmarks. A hand-authored C4 block runs on the real url4
executor over a fake Gateway: the selected candidate makes one call, every unselected body makes
none, and JOIN publishes one record.

STORY: as an Engine operator, a Router runs in a world with no Benchmarks, and a run whose files a
Router Model cannot take is refused before any classifier or Model is paid.

WHY a hand-authored block: the public compiler is not part of this unit; the block follows the C4
sketch (`docs/spec/2026-11-16-router-recipe-extension/contracts.md`) step by step.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx
import pytest
from router_block_support import PNG as _PNG
from router_block_support import QUESTION as _QUESTION
from router_block_support import SCOPE as _SCOPE
from router_block_support import block as _block
from router_block_support import chats as _chats
from router_block_support import choice as _choice
from router_block_support import run_block as _run
from router_block_support import selector_reply as _selector_reply
from router_block_support import world as _world
from router_support import (
    ROUTER,
    accepted,
    choice_definition,
    fixed_definition,
    llm_definition,
    model,
    regex_definition,
    router_gateway,
    step,
    text,
)
from routing_support import (
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    LABELS,
    MODELS,
    PUBLIC,
    Gateway,
    chat_answer,
)

from screamingface_engine.operation_calls import (
    AttemptFact,
    OperationCall,
    capture_operation_calls,
    current_attempt_facts,
)
from screamingface_engine.request_scope import request_scope
from screamingface_engine.world.factory import direct_mount_paths
from screamingface_engine.world.router_steps import (
    ROUTER_ADMIT_ROUTE,
    ROUTER_CLASSIFY_ROUTE,
    ROUTER_DECIDE_ROUTE,
    ROUTER_JOIN_ROUTE,
    ROUTER_OPEN_ROUTE,
)
from url4 import Attachment
from url4.core.errors import ResolutionError
from url4.wire.subrequest import encode_subrequest

_STEPS = (
    ROUTER_ADMIT_ROUTE,
    ROUTER_CLASSIFY_ROUTE,
    ROUTER_DECIDE_ROUTE,
    ROUTER_OPEN_ROUTE,
    ROUTER_JOIN_ROUTE,
)
# --- installation ---------------------------------------------------------------------------------


def test_a_world_without_benchmarks_serves_the_router_steps_outside_its_direct_mounts() -> None:
    async def scenario() -> tuple[frozenset[str], frozenset[str]]:
        async with _world(Gateway()) as node:
            return frozenset(node.processor_routes()), direct_mount_paths(node)

    served, direct = asyncio.run(scenario())

    assert set(_STEPS) <= served
    assert not set(_STEPS) & direct


# --- the classification port (C8) ---------------------------------------------------------------


async def _classify(gateway: Gateway) -> tuple[object, list[OperationCall], list[AttemptFact]]:
    """CLASSIFY on the world, over the ADMIT result its occurrence recorded."""
    admit = accepted(fixed_definition())
    target = encode_subrequest(ROUTER_CLASSIFY_ROUTE, admit, None, ())
    async with _world(gateway) as node:
        with request_scope(_SCOPE), capture_operation_calls() as recorded:
            step("admit", admit)
            try:
                value: object = await node.fetch(target, relative=True)
            except ResolutionError as exc:
                value = exc
            facts = list(current_attempt_facts() or ())
    return value, list(recorded), facts


def test_the_scoring_classify_step_records_its_answer_and_its_attempts() -> None:
    value, recorded, facts = asyncio.run(_classify(Gateway()))

    assert isinstance(value, str) and json.loads(value)["model"] == CLASSIFIER
    assert [(call.path, call.params) for call in recorded] == [
        (ROUTER_CLASSIFY_ROUTE, (("binding", ROUTER),))
    ]
    assert [(item.binding, item.status) for item in facts] == [(ROUTER, "answered")]


def test_a_gateway_refusal_of_the_classifier_is_its_status_code_and_an_unpriced_call() -> None:
    gateway = Gateway()
    detail = {"detail": {"code": "provider_key_refused", "message": "a key text"}}
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(403, json=detail)

    value, recorded, facts = asyncio.run(_classify(gateway))

    assert value == text({"failed": {"code": "aigateway_http_403", "permanent": True}})
    # INVARIANT: the failed classification is still the occurrence's classify operation, with
    # no accounting, so a budget counts the call that may have been paid.
    assert [(call.path, call.params, call.accounting) for call in recorded] == [
        (ROUTER_CLASSIFY_ROUTE, (("binding", ROUTER),), None)
    ]
    assert [(item.binding, item.status, item.code) for item in facts] == [
        (ROUTER, "failed", "aigateway_http_403")
    ]


def test_a_control_plane_ending_propagates_through_the_classify_step() -> None:
    gateway = Gateway()
    ended = ResolutionError("the run ended", code="deadline_exceeded", permanent=True)
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = ended

    value, recorded, _ = asyncio.run(_classify(gateway))

    assert isinstance(value, ResolutionError) and value.code == "deadline_exceeded"
    assert recorded == []


# --- one C4 block on the url4 executor ------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "classifications", "selected"),
    [
        (fixed_definition(), 1, "code"),
        (choice_definition(), 1, "code"),
        (llm_definition(), 0, "code"),
        (regex_definition(), 0, "math"),
    ],
    ids=["fixed", "choice", "llm", "regex"],
)
def test_a_router_block_runs_only_the_selected_candidate(
    definition: dict[str, Any], classifications: int, selected: str
) -> None:
    gateway = router_gateway()
    gateway.script[(CHAT_PATH, MODELS["general"])] = _selector_reply("code")

    value, recorded = asyncio.run(_run(gateway, _block(definition)))

    assert value == f"answer from {MODELS[selected]}"
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == classifications
    selector = [MODELS["general"]] if definition["classifier"]["source"] == "llm" else []
    assert _chats(gateway) == [*selector, MODELS[selected]]
    records = [call.router for call in recorded if call.router is not None]
    assert len(records) == 1 and records[0] is not None
    record = records[0].document()
    assert (record["status"], record["selected"][0]["label"]) == ("answered", selected)
    assert _QUESTION not in json.dumps(record)


def test_a_failed_classifier_never_runs_the_default() -> None:
    gateway = router_gateway()
    gateway.script[(CLASSIFICATIONS_PATH, CLASSIFIER)] = httpx.Response(403, json={"detail": "no"})
    block = _block(fixed_definition(default=model(PUBLIC)))

    value, recorded = asyncio.run(_run(gateway, block))

    assert isinstance(value, ResolutionError)
    assert (value.code, value.permanent) == ("aigateway_http_403", True)
    assert _chats(gateway) == []
    records = [call.router for call in recorded if call.router is not None]
    assert len(records) == 1 and records[0] is not None
    assert records[0].document()["failure"] == {"phase": "classify", "code": "aigateway_http_403"}


def test_a_json_shaped_answer_reaches_the_caller_byte_for_byte() -> None:
    # WHY (url4 spec 5.3.8): the real executor re-encodes a structured row; JOIN proves the row
    # against the call's recorded reply and returns the reply itself.
    gateway = router_gateway()
    reply = '{"answer":"\u00e9","n":[1,2]}'
    gateway.script[(CHAT_PATH, MODELS["code"])] = lambda _request: {
        **chat_answer(MODELS["code"]),
        "choices": [_choice(reply)],
    }

    value, _ = asyncio.run(_run(gateway, _block(fixed_definition())))

    assert value == reply


def test_a_refused_candidate_fails_at_generate_with_its_gateway_code() -> None:
    gateway = router_gateway()
    gateway.script[(CHAT_PATH, MODELS["code"])] = httpx.Response(403, json={"detail": "no"})

    value, recorded = asyncio.run(_run(gateway, _block(fixed_definition())))

    assert isinstance(value, ResolutionError)
    assert (value.code, value.permanent) == ("aigateway_http_403", True)
    assert _chats(gateway) == [MODELS["code"]]
    records = [call.router for call in recorded if call.router is not None]
    assert len(records) == 1 and records[0] is not None
    record = records[0].document()
    assert record["failure"] == {"phase": "generate", "code": "aigateway_http_403"}
    assert [(row["label"], row["status"], row["code"]) for row in record["branches"]] == [
        ("code", "failed", "aigateway_http_403")
    ]


def test_a_refused_definition_runs_nothing_and_still_publishes_its_record() -> None:
    gateway = router_gateway()
    block = _block(fixed_definition(candidates=[]))

    value, recorded = asyncio.run(_run(gateway, block))

    assert isinstance(value, ResolutionError) and value.code == "router_definition_invalid"
    assert [request.method for request in gateway.requests] == []
    records = [call.router for call in recorded if call.router is not None]
    assert len(records) == 1 and records[0] is not None
    assert records[0].document()["failure"] == {
        "phase": "admit",
        "code": "router_definition_invalid",
    }


def test_a_run_file_a_router_model_cannot_take_refuses_the_run_before_any_call() -> None:
    gateway = router_gateway()
    listed = [{"id": name, "input_modalities": ["text"]} for name in (*MODELS.values(), PUBLIC)]
    gateway.script[("/v1/models", "")] = lambda _request: {"object": "list", "data": listed}
    picture = Attachment(
        digest="sha256:" + hashlib.sha256(_PNG).hexdigest(), media_type="image/png", body=_PNG
    )

    value, recorded = asyncio.run(_run(gateway, _block(fixed_definition()), (picture,)))

    assert isinstance(value, ResolutionError) and value.code == "intent_error"
    assert [request.method for request in gateway.requests if request.method == "POST"] == []
    assert [call for call in recorded if call.router is not None or call.is_provider] == []
    assert len(LABELS) == 3
