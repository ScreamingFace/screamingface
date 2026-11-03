"""A fake classifier upstream and the shared helpers of the classification app tests.

# FEATURE: hosted BYOM Unit 3 — the harness's chat fake stays as it is; this fake answers the
# classifier path of every configured endpoint and hands every other path to the chat fake.
# WHY swapped in after `byom.start`: the harness installs its own chat-shaped transport and probe,
# and a classifier validation target needs a probe that answers a classification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.credential_blob.store import ORMStore
from aigateway.plugins.remote_endpoint.validation import RemoteEndpointReadiness

from .conftest import MALFORMED, REJECTED, Harness, Upstream, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    CLASSIFIER_ALIAS,
    CLASSIFIER_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
    chat_target,
    classifier_target,
    document,
    endpoint,
)

# Upstream order on purpose: not sorted, and the first and last labels tie.
SCORES = [
    {"label": "POSITIVE", "score": 0.25},
    {"label": "NEGATIVE", "score": 0.5},
    {"label": "NEUTRAL", "score": 0.25},
]


def classifier_id(provider: str, alias: str = CLASSIFIER_ALIAS) -> str:
    return f"{provider}/{alias}"


def mixed_endpoint(
    endpoint_id: str,
    *,
    origin: str,
    accounts: tuple[str, ...],
    enabled: bool = True,
    validation_target: str = ALIAS,
    envelope: str = "single-batch",
) -> dict[str, Any]:
    return endpoint(
        endpoint_id,
        origin=origin,
        accounts=accounts,
        enabled=enabled,
        targets=[chat_target(), classifier_target(response_envelope=envelope)],
        validation_target=validation_target,
    )


def mixed_document(
    *,
    a_accounts: tuple[str, ...] = (ACCOUNT_A, ACCOUNT_B),
    b_accounts: tuple[str, ...] = (ACCOUNT_A,),
    b_enabled: bool = True,
    validation_target: str = ALIAS,
    envelope: str = "single-batch",
) -> dict[str, Any]:
    """The Unit 0 grant matrix, with one chat and one classifier target on each endpoint."""
    return document(
        mixed_endpoint(
            ENDPOINT_A,
            origin=ORIGIN_A,
            accounts=a_accounts,
            validation_target=validation_target,
            envelope=envelope,
        ),
        mixed_endpoint(
            ENDPOINT_B,
            origin=ORIGIN_B,
            accounts=b_accounts,
            enabled=b_enabled,
            validation_target=validation_target,
            envelope=envelope,
        ),
    )


def classifier_only_document(*, accounts: tuple[str, ...] = (ACCOUNT_A,)) -> dict[str, Any]:
    return document(
        endpoint(
            ENDPOINT_A,
            origin=ORIGIN_A,
            accounts=accounts,
            targets=[classifier_target()],
            validation_target=CLASSIFIER_ALIAS,
        )
    )


@dataclass(frozen=True)
class ClassifierCall:
    url: str
    bearer: str
    body: bytes
    probe: bool


def scores_reply(request: httpx.Request) -> httpx.Response:
    """The default answer: a key with a marker gets what the chat fake gives it, else SCORES."""
    bearer = request.headers.get("authorization", "")
    if REJECTED in bearer:
        return httpx.Response(401, json={"error": "upstream says the key is invalid"})
    if MALFORMED in bearer:
        return httpx.Response(200, json={"choices": []})
    return httpx.Response(200, json=[SCORES])


@dataclass
class ClassifierUpstream:
    """The classifier behind every configured endpoint; any other path reaches the chat fake."""

    chat: Upstream
    calls: list[ClassifierCall] = field(default_factory=list)
    reply: Callable[[httpx.Request], httpx.Response] = scores_reply
    _parties: int = 0
    _barrier: asyncio.Barrier | None = None

    def expect_overlap(self, parties: int) -> None:
        """Hold every classification until `parties` are in flight at once (0 turns it off)."""
        self._parties, self._barrier = parties, None

    def transport(self, *, probe: bool = False) -> httpx.MockTransport:
        chat = self.chat.transport(probe=probe)

        async def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path != CLASSIFIER_PATH:
                return await chat.handle_async_request(request)
            bearer = request.headers.get("authorization", "")
            self.calls.append(ClassifierCall(str(request.url), bearer, request.content, probe))
            if self._parties:
                if self._barrier is None:
                    self._barrier = asyncio.Barrier(self._parties)
                # INVARIANT: a timeout here means the gateway serialized calls it must overlap.
                await asyncio.wait_for(self._barrier.wait(), timeout=10)
            return self.reply(request)

        return httpx.MockTransport(handle)

    def install(self, byom: Harness, client: TestClient) -> None:
        """Serve both endpoints' traffic and readiness probes from this fake from now on."""
        app = cast(FastAPI, client.app)
        for provider in (ENDPOINT_A, ENDPOINT_B):
            plugin = app.state.providers.get(provider)
            if plugin is not None:
                plugin._transport = self.transport()
                readiness = RemoteEndpointReadiness(
                    plugin._definition, transport=self.transport(probe=True)
                )
                byom.monkeypatch.setattr(plugin, "api_key_validator", lambda r=readiness: r)


@contextmanager
def started(byom: Harness, doc: dict[str, Any]) -> Iterator[tuple[TestClient, ClassifierUpstream]]:
    with byom.start(doc) as client:
        upstream = ClassifierUpstream(byom.upstream)
        upstream.install(byom, client)
        yield client, upstream


def classify(
    client: TestClient, account: str, body: Any, *, raw: bytes | None = None
) -> httpx.Response:
    headers = tenant_headers(account)
    if raw is not None:
        return client.post(
            "/v1/classifications",
            content=raw,
            headers={**headers, "content-type": "application/json"},
        )
    return client.post("/v1/classifications", json=body, headers=headers)


def classification_body(provider: str, text: str, alias: str = CLASSIFIER_ALIAS) -> dict[str, Any]:
    return {"model": classifier_id(provider, alias), "input": text}


def sent_input(call: ClassifierCall) -> Any:
    """The decoded upstream body; the test compares it with the caller's input."""
    return json.loads(call.body)


def key_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every read of either configured endpoint's stored keys from now on."""
    reads: list[str] = []
    original = ORMStore.read

    async def spy(self: ORMStore, service: str, account: str) -> str | None:
        if service.startswith((f"aigateway:{ENDPOINT_A}:", f"aigateway:{ENDPOINT_B}:")):
            reads.append(service)
        return await original(self, service, account)

    monkeypatch.setattr(ORMStore, "read", spy)
    return reads


class _Recording(logging.Handler):
    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def gateway_log() -> Iterator[list[logging.LogRecord]]:
    """Every record the `aigateway` loggers emit inside the block."""
    # WHY on the `aigateway` logger, not caplog: `logs.configure` turns propagation off, so
    # caplog sees these records only in some test orders. A copy of the Unit 1 helper in
    # `test_app_shared_cache.py`, which stays unchanged.
    records: list[logging.LogRecord] = []
    handler = _Recording(records)
    logger = logging.getLogger("aigateway")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def messages_of(records: list[logging.LogRecord]) -> list[str]:
    return [record.getMessage() for record in records]
