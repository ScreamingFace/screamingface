"""`POST /v1/classifications` when the classifier fails: sanitized answers and one record each.

# FEATURE: hosted BYOM Unit 3 — every bad upstream result ends as the existing sanitized failure,
# a 429 or 503 passes only its bounded Retry-After on after the shared overload retry, and a
# client that leaves mid-call is answered 499, as chat does.
# INVARIANT: each failure finds its expected record on the `aigateway` logger first; then neither
# the key nor the input appears in any captured record or in the answer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException, Request

from aigateway.config import Settings
from aigateway.routes import classifications
from aigateway.routes.classifications import dispatch_classification

from .classifier_upstream import (
    classification_body,
    classify,
    gateway_log,
    messages_of,
    mixed_document,
    started,
)
from .conftest import Harness, put_key
from .fixtures import ACCOUNT_A, ENDPOINT_A

KEY = "sk-alice-on-a-failures-0001"
MARKER = "zz-input-marker"
TEXT = f"{MARKER}: please classify this"
FAILED = f"classification failed provider={ENDPOINT_A} code=provider_error status="

BAD_RESULTS: dict[str, httpx.Response] = {
    "empty-list": httpx.Response(200, json=[[]]),
    "two-item-batch": httpx.Response(200, json=[[{"label": "a", "score": 0.5}]] * 2),
    "boolean-score": httpx.Response(200, json=[[{"label": "a", "score": True}]]),
    "score-above-one": httpx.Response(200, json=[[{"label": "a", "score": 1.5}]]),
    "nan-score": httpx.Response(
        200,
        content=b'[[{"label": "a", "score": NaN}]]',
        headers={"content-type": "application/json"},
    ),
    "html": httpx.Response(200, content=b"<html></html>", headers={"content-type": "text/html"}),
    "unauthorized": httpx.Response(401, json={"error": f"bad key {KEY}"}),
    "forbidden": httpx.Response(403, json={"error": "denied"}),
    "server-error": httpx.Response(500, json={"error": f"echo {TEXT}"}),
    "oversized": httpx.Response(
        200, content=b"[" + b" " * 1_100_000 + b"]", headers={"content-type": "application/json"}
    ),
}


def _private(response: httpx.Response, records: list[Any]) -> None:
    texts = [response.text, *messages_of(records), *(str(r.args) for r in records)]
    assert not [text for text in texts if KEY in text or MARKER in text]


@pytest.fixture
def quick_retry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # WHY: one immediate retry, so the overload warning is logged without a real wait.
    monkeypatch.setenv("AIGW_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("AIGW_RETRY_BACKOFF_BASE", "0")
    monkeypatch.setenv("AIGW_RETRY_JITTER", "0")
    yield


@pytest.mark.parametrize("answer", BAD_RESULTS.values(), ids=BAD_RESULTS.keys())
def test_a_bad_result_is_a_sanitized_502_with_one_record(
    byom: Harness, answer: httpx.Response
) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.reply = lambda _request: answer
        with gateway_log() as records:
            response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, TEXT))

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "provider_error"
    # INVARIANT (G7): an upstream 401 or 403 is not retried with another key.
    assert len(upstream.calls) == 1
    assert [m for m in messages_of(records) if m.startswith(FAILED)] == [
        f"{FAILED}502 type=HTTPException"
    ]
    _private(response, records)


@pytest.mark.parametrize("status", [429, 503])
def test_an_overloaded_classifier_is_retried_once_and_passes_its_bounded_hint(
    byom: Harness, quick_retry: None, status: int
) -> None:
    answers = iter(
        [
            httpx.Response(status, json={"error": TEXT}),
            httpx.Response(status, headers={"retry-after": "7"}, json={"error": KEY}),
        ]
    )
    with started(byom, mixed_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.reply = lambda _request: next(answers)
        with gateway_log() as records:
            response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, TEXT))

    assert response.status_code == status, response.text
    assert response.headers.get("retry-after") == "7"
    assert len(upstream.calls) == 2
    messages = messages_of(records)
    assert f"aigw upstream overload (status={status}); retry 1/1 after 0.00s" in messages
    assert [m for m in messages if m.startswith(FAILED)] == [f"{FAILED}{status} type=HTTPException"]
    _private(response, records)


def test_an_unexpected_error_is_a_sanitized_502_logged_by_type_only(byom: Harness) -> None:
    def explode(_request: httpx.Request) -> httpx.Response:
        raise LookupError(f"{KEY} {TEXT}")

    with started(byom, mixed_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        upstream.reply = explode
        with gateway_log() as records:
            response = classify(client, ACCOUNT_A, classification_body(ENDPOINT_A, TEXT))

    assert (response.status_code, response.json()["detail"]["code"]) == (502, "provider_error")
    assert [m for m in messages_of(records) if m.startswith(FAILED)] == [
        f"{FAILED}502 type=LookupError"
    ]
    _private(response, records)


# --- a client that leaves mid-call ---------------------------------------------------------------


def _request() -> tuple[Request, asyncio.Event]:
    disconnect = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    app = SimpleNamespace(state=SimpleNamespace(settings=Settings(provider_max_concurrency=1)))
    return Request({"type": "http", "app": app, "headers": []}, receive), disconnect


@pytest.mark.asyncio
async def test_a_client_disconnect_is_answered_499_and_cancels_the_call() -> None:
    request, disconnect = _request()
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def classify_forever(body: dict[str, Any]) -> dict[str, Any]:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return body

    plugin = SimpleNamespace(classify=classify_forever)
    task = asyncio.create_task(dispatch_classification(request, plugin, ENDPOINT_A, {}))
    await asyncio.wait_for(entered.wait(), 1)
    disconnect.set()

    with pytest.raises(HTTPException) as caught:
        await task

    assert caught.value.status_code == 499
    assert caught.value.detail == {
        "code": "client_disconnected",
        "message": "The client disconnected.",
    }
    assert cancelled.is_set()
    assert task.cancelling() == 0


@pytest.mark.asyncio
async def test_a_shutdown_cancellation_still_propagates() -> None:
    request, _disconnect = _request()
    entered = asyncio.Event()

    async def classify_forever(body: dict[str, Any]) -> dict[str, Any]:
        entered.set()
        await asyncio.Event().wait()
        return body

    plugin = SimpleNamespace(classify=classify_forever)
    task = asyncio.create_task(dispatch_classification(request, plugin, ENDPOINT_A, {}))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel("shutdown")

    with pytest.raises(asyncio.CancelledError):
        await task


# --- the record's level --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "level"),
    [("provider_queue_timeout", logging.WARNING), ("provider_error", logging.ERROR)],
)
async def test_only_the_gateway_s_own_queue_timeout_503_is_a_warning(
    monkeypatch: pytest.MonkeyPatch, code: str, level: int
) -> None:
    """WHY (OME-1461 log-level policy, as chat): a call the Gateway shed for capacity is expected
    overload volume, so WARNING; a classifier still answering 503 after retries is an outage and
    stays alertable at ERROR."""

    async def refuse(*_args: Any) -> dict[str, Any]:
        raise HTTPException(503, detail={"code": code, "message": "fixed"})

    monkeypatch.setattr(classifications, "dispatch_with_budgets", refuse)
    request, _disconnect = _request()
    with gateway_log() as records, pytest.raises(HTTPException):
        await dispatch_classification(request, SimpleNamespace(), ENDPOINT_A, {})

    expected = f"classification failed provider={ENDPOINT_A} code={code} status=503"
    failed = [r for r in records if r.getMessage().startswith("classification failed")]
    assert [(r.levelno, r.getMessage()) for r in failed] == [
        (level, f"{expected} type=HTTPException")
    ]
