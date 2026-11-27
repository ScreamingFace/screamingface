"""A hand-authored C4 Router block on a Gateway world, run by the real url4 executor (Unit 5.2).

WHY hand-authored: the public compiler is not part of this unit; the block follows the C4 sketch
(`docs/spec/2026-11-16-router-recipe-extension/contracts.md`) step by step.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from router_support import ROUTER, envelope
from routing_support import CALLER, CHAT_PATH, MODELS, Gateway, chat_answer, world_config

from screamingface_engine.benchmarks.picture_admission import run_expression_scope
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.factory import build_world
from url4 import Attachment
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.dag.attachments import bind_run_files

SCOPE = RequestScope(origin="run", identity_headers=CALLER)
QUESTION = "Which integral solves this math problem"
PNG = b"\x89PNG\r\n\x1a\n"


@asynccontextmanager
async def world(gateway: Gateway) -> AsyncIterator[Any]:
    """A Gateway world with no Benchmarks, as a direct or chat Engine composes one."""
    async with gateway.client() as client:
        node, aclose = await build_world(env={}, config=world_config(), client=client)
        try:
            yield node
        finally:
            if aclose is not None:
                await aclose()


def bound_call(binding: str, ref: dict[str, Any]) -> str:
    """One bound Model call over the admitted question, as a C4 body holds it."""
    params = "".join(f"&{name}={value}" for name, value in sorted(ref["params"].items()))
    return f"{binding}:0.0:/{ref['model']}?binding={binding}{params}&q=($router_1_admit.input)!''"


def selector_call(definition: dict[str, Any]) -> str:
    classifier = definition["classifier"]
    if classifier["source"] == "llm":
        return bound_call("selector_1", classifier["model"])
    # WHY sel_1: KEYWORDS keys its selectors by an E4c selector id (`decision.SELECTOR_ID`).
    keywords = {"sel_1": {"schema": "screamingface.keywords.v1", "multi": False}}
    keywords["sel_1"]["rules"] = classifier["rules"]
    intent = json.dumps(keywords, separators=(",", ":"))
    return f"selector_1:0.0:/ensemble/select/v1/keywords($router_1_admit.input)!'{intent}'"


def block(definition: dict[str, Any], question: str = QUESTION) -> str:
    """The C4 block of one ``select="one"`` Router occurrence over ``question``."""
    spec = json.dumps(envelope(definition), separators=(",", ":"))
    parts = [
        f"question:0.0:'{question}'",
        f"router_1_admit:0.0:/ensemble/router/v1/admit?binding={ROUTER}"
        f"&q=({{input: '$question'}})!'{spec}'",
    ]
    if definition["classifier"]["source"] == "scoring":
        parts.append("router_1_scores:0.0:/ensemble/router/v1/classify($router_1_admit)!''")
        evidence = "$router_1_scores"
    else:
        parts.append("router_1_open_s:0.0:/ensemble/router/v1/open($router_1_admit)!'classify'")
        parts.append(
            f"router_1_sel:0.0:$router_1_open_s*({selector_call(definition)})"
            "!'$selector_1';iteration.on_error=collect"
        )
        evidence = "$router_1_sel"
    parts.append(
        f"router_1_decide:0.0:/ensemble/router/v1/decide?binding={ROUTER}"
        f"&q=({{admit: '$router_1_admit', evidence: '{evidence}'}})!''"
    )
    bodies = [
        (f"c{k}", f"model_{k + 1}", row["model"]) for k, row in enumerate(definition["candidates"])
    ]
    if definition["default"] is not None:
        bodies.append(("d", f"model_{len(bodies) + 1}", definition["default"]))
    for slot, binding, ref in bodies:
        intent = "default" if slot == "d" else slot
        parts.append(
            f"router_1_open_{slot}:0.0:/ensemble/router/v1/open($router_1_decide)!'{intent}'"
        )
        parts.append(
            f"router_1_{slot}:0.0:$router_1_open_{slot}*({bound_call(binding, ref)})"
            f"!'${binding}';iteration.on_error=collect"
        )
    slots = "".join(f", {slot}: '$router_1_{slot}'" for slot, _, _ in bodies)
    parts.append(
        f"router_1:0.0:/ensemble/router/v1/join?binding={ROUTER}"
        f"&q=({{admit: '$router_1_admit', decision: '$router_1_decide'{slots}}})!''"
    )
    return "(" + ", ".join(parts) + ")!'$router_1'"


async def run_block(
    gateway: Gateway, block: str, files: tuple[Attachment, ...] = ()
) -> tuple[object, list[OperationCall]]:
    async with world(gateway) as node:
        with (
            request_scope(SCOPE),
            capture_operation_calls() as recorded,
            run_expression_scope(block),
            bind_run_files(files),
        ):
            try:
                value: object = await url4_run(block, io=node)
            except ResolutionError as exc:
                value = exc
    return value, list(recorded)


def selector_reply(label: str) -> Any:
    return lambda _request: {**chat_answer(MODELS["general"]), "choices": [choice(label)]}


def choice(content: str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}


def chats(gateway: Gateway) -> list[str]:
    return [body["model"] for body in gateway.posts(CHAT_PATH)]
