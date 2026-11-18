"""A chat run's world for tests: a stub gateway, the chat-input store in memory, the turn route.

Test-only, the `_gate_world` pattern. `chat_world` builds the gateway world with every route a
chat run needs (Candidate, combine, branch and chat turn). `ingest_chat_input` writes one
CHAT_INPUT record into an in-memory chat-input store and returns its ref and a run-scoped reader
factory. `run_turn` dispatches the turn route inside a chat run, the way the executor does, and
`run_candidate_route` runs the same recipe through the Candidate route of a benchmark Case.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from _gate_world import FAIL, REFUSE, Gateway, wrapped

from screamingface_engine.artifacts.blobs import (
    BLOB_REF_PREFIX,
    BlobScope,
    BlobStore,
    ScopedBlobReader,
)
from screamingface_engine.artifacts.chat_inputs import chat_input_store
from screamingface_engine.benchmarks.contract import (
    CandidateInvocation,
    decode_candidate_invocation_record,
)
from screamingface_engine.chat.input import (
    CHAT_INPUT_MEDIA_TYPE,
    CHAT_INPUT_SCHEMA,
    decode_chat_input,
    encode_chat_input,
)
from screamingface_engine.chat.result import ChatResult, decode_chat_result
from screamingface_engine.chat.wire import canonical_json
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.attachment_parts import BlobReader
from screamingface_engine.world.branch import install_branch_runtime
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.chat_turn import chat_run_scope, chat_turn_target, install_chat_turn
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.peer import dispatch_direct
from url4.peer.server import Url4Node

__all__ = [
    "FAIL",
    "REFUSE",
    "RUN",
    "Gateway",
    "MemoryObjects",
    "chat_store",
    "chat_world",
    "ingest_chat_input",
    "run_candidate_route",
    "run_turn",
]

RUN = "c" * 64


class MemoryObjects:
    """A put/get-only blob backend in a dict, with a delete."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        return 0

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def chat_store() -> tuple[BlobStore, MemoryObjects]:
    """A chat-input store over a fresh in-memory backend, and that backend."""
    objects = MemoryObjects()
    return chat_input_store(objects), objects


def ingest_chat_input(
    store: BlobStore,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    run: str = RUN,
) -> tuple[str, Callable[[], BlobReader]]:
    """Ingest one CHAT_INPUT record; its blob ref and a reader factory scoped to `run`."""
    value: dict[str, Any] = {"schema": CHAT_INPUT_SCHEMA, "messages": messages}
    if tools:
        value["tools"] = tools
    body = encode_chat_input(decode_chat_input(canonical_json(value)))
    sha = hashlib.sha256(body).hexdigest()
    scope = BlobScope.for_caller(None, run)
    store.ingest(scope, sha, CHAT_INPUT_MEDIA_TYPE, body)
    return BLOB_REF_PREFIX + sha, lambda: ScopedBlobReader(store, scope)


@asynccontextmanager
async def chat_world(gateway: Gateway, *, web_search: bool = False) -> AsyncIterator[Url4Node]:
    """The gateway world of a chat run, with every route it needs, over `gateway`."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=next(iter(gateway.replies)),
            models=tuple(ModelSpec(id=model, web_search=web_search) for model in gateway.replies),
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        install_branch_runtime(world.node)
        install_chat_turn(world.node)
        yield world.node
    finally:
        await world.aclose()
        await client.aclose()


async def run_turn(
    node: Url4Node, recipe: str, ref: str, reader: Callable[[], BlobReader]
) -> ChatResult:
    """Dispatch the turn route inside a chat run and decode its CHAT_RESULT."""
    with request_scope(RequestScope(origin="run")), chat_run_scope(reader):
        result = await dispatch_direct(node, chat_turn_target(ref, recipe))
    return decode_chat_result(result.body.encode("utf-8"))


async def run_candidate_route(node: Url4Node, recipe: str, input_text: str) -> CandidateInvocation:
    """Run `recipe` through the Candidate route on `input_text`, as a benchmark Case does."""
    with request_scope(RequestScope(origin="run")):
        text = await url4_run(wrapped(recipe, input_text), io=node)
    return decode_candidate_invocation_record(text)
