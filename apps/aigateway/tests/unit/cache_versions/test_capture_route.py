"""CV-3, CV-4, CV-6, CV-26: what the chat route captures, and that capture never changes a reply.

FEATURE: OME-1307 (E14) - a traced chat call leaves one `cache_capture_entry` row with its outcome.
INVARIANT (CV-D5): only a call that carries a valid inbound ``traceparent`` is captured.
INVARIANT (CV-3): a capture failure never changes the chat response.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.models import CacheCaptureEntry, RequestCachePrompt
from aigateway.core.cache_versions.ports import CaptureRecord
from tests.unit.cache_versions.conftest import login_admin, traceparent
from tests.unit.test_chat_global_cache_route import (
    _CHAT_PATH,
    _PATCH_TARGET,
    _arrange_account,
    _chat_body,
    _DispatchCounter,
)

_TRACE = "a1" * 16


def _state(client: TestClient) -> Any:
    app: Any = client.app
    return app.state


def _rows(client: Any, trace_id: str) -> list[CacheCaptureEntry]:
    async def _load() -> list[CacheCaptureEntry]:
        return await CacheCaptureEntry.filter(trace_id=trace_id).order_by("ordinal")

    return client.portal.call(_load)


def _count(client: Any, model: Any) -> int:
    async def _n() -> int:
        return await model.all().count()

    return client.portal.call(_n)


def _prompts(client: Any) -> list[RequestCachePrompt]:
    async def _load() -> list[RequestCachePrompt]:
        return await RequestCachePrompt.all()

    return client.portal.call(_load)


class _RaisingSink:
    async def record(self, record: CaptureRecord) -> None:
        raise RuntimeError("the capture store is down")


def test_capture_failure_does_not_change_chat_response(
    capture_client: TestClient, credential_blobs: Any
) -> None:
    _arrange_account(capture_client, credential_blobs)
    state = _state(capture_client)
    state.capture_sink = _RaisingSink()
    counter = _DispatchCounter()

    with patch(_PATCH_TARGET, counter):
        resp = capture_client.post(
            _CHAT_PATH, json=_chat_body(), headers={"traceparent": traceparent(_TRACE)}
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "PLAINTEXT-ANSWER-42"
    assert resp.headers["X-AIGW-Cache"] == "miss"
    assert resp.headers["X-AIGW-Cache-Write"] == "stored"
    assert state.capture_stats.failures == 1
    assert _rows(capture_client, _TRACE) == []


_UNTRACED_HEADERS = [
    pytest.param(None, id="absent"),
    pytest.param("garbage", id="garbage"),
    pytest.param(f"00-{'0' * 32}-{'a' * 16}-01", id="all-zero-trace-id"),
    pytest.param(f"00-{'AB' * 16}-{'a' * 16}-01", id="uppercase-hex"),
    pytest.param(f"01-{'b2' * 16}-{'a' * 16}-01", id="version-01"),
]


@pytest.mark.parametrize("header", _UNTRACED_HEADERS)
def test_untraced_call_writes_no_capture_row(
    header: str | None, capture_client: TestClient, credential_blobs: Any
) -> None:
    _arrange_account(capture_client, credential_blobs)
    counter = _DispatchCounter()
    positive_trace = "c3" * 16

    with patch(_PATCH_TARGET, counter):
        # Positive control: the same request with a VALID traceparent is captured, so a zero
        # below cannot come from capture being broken or switched off.
        controlled = capture_client.post(
            _CHAT_PATH,
            json=_chat_body(),
            headers={"traceparent": traceparent(positive_trace)},
        )
        assert controlled.status_code == 200, controlled.text
        assert len(_rows(capture_client, positive_trace)) == 1

        headers = {} if header is None else {"traceparent": header}
        before = _count(capture_client, CacheCaptureEntry)
        resp = capture_client.post(_CHAT_PATH, json=_chat_body(), headers=headers)

    assert resp.status_code == 200, resp.text
    assert _count(capture_client, CacheCaptureEntry) == before


def test_capture_writes_one_row_per_traced_call_with_outcome(
    capture_client: TestClient, credential_blobs: Any
) -> None:
    _arrange_account(capture_client, credential_blobs)
    counter = _DispatchCounter()
    hit_body = _chat_body(messages=[{"role": "user", "content": "H: primes below 100?"}])
    stored_body = _chat_body(messages=[{"role": "user", "content": "S: primes below 200?"}])
    bypass_body = _chat_body(
        messages=[{"role": "user", "content": "B: primes below 300?"}],
        cache={"use-cache": False},
    )
    headers = {"traceparent": traceparent(_TRACE)}

    with patch(_PATCH_TARGET, counter):
        # An UNTRACED call fills body H in the live cache and leaves no capture row.
        filled = capture_client.post(_CHAT_PATH, json=hit_body)
        assert filled.headers["X-AIGW-Cache-Write"] == "stored"
        assert _count(capture_client, CacheCaptureEntry) == 0

        hit = capture_client.post(_CHAT_PATH, json=hit_body, headers=headers)
        stored = capture_client.post(_CHAT_PATH, json=stored_body, headers=headers)
        bypass = capture_client.post(_CHAT_PATH, json=bypass_body, headers=headers)

    assert hit.headers["X-AIGW-Cache"] == "hit"
    assert stored.headers["X-AIGW-Cache-Write"] == "stored"
    assert bypass.headers["X-AIGW-Cache"] == "bypass"
    rows = _rows(capture_client, _TRACE)
    assert [row.outcome for row in rows] == ["hit", "stored", "bypass"]
    assert [row.response_json is not None for row in rows] == [False, False, True]
    dispatched = json.loads(rows[2].response_json or "")
    assert dispatched["choices"][0]["message"]["content"] == "PLAINTEXT-ANSWER-42"
    assert "_aigw" not in dispatched, "the body is the provider-compatible form, before metadata"
    prompts = {prompt.key_hash: prompt for prompt in _prompts(capture_client)}
    assert len(prompts) == 3
    assert {row.key_hash for row in rows} == set(prompts)
    for key_hash, prompt in prompts.items():
        assert hashlib.sha256(prompt.request_json.encode("utf-8")).hexdigest() == key_hash
    assert rows[0].key_hash is not None and rows[1].key_hash is not None
    assert rows[0].key_hash[:12] == hit.headers["X-AIGW-Cache-Key"]
    assert rows[1].key_hash[:12] == stored.headers["X-AIGW-Cache-Key"]


def test_streaming_call_captured_as_bypass_without_body(
    capture_client: TestClient, credential_blobs: Any
) -> None:
    _arrange_account(capture_client, credential_blobs)

    async def _one_chunk(plugin: Any, body: dict[str, Any], *, provider: str) -> AsyncIterator[str]:
        yield 'data: {"choices": []}\n\n'

    with patch("aigateway.routes.chat._stream", _one_chunk):
        resp = capture_client.post(
            _CHAT_PATH,
            json=_chat_body(stream=True),
            headers={"traceparent": traceparent(_TRACE)},
        )
        _ = resp.content

    assert resp.status_code == 200, resp.text
    rows = _rows(capture_client, _TRACE)
    assert len(rows) == 1
    assert rows[0].outcome == "bypass"
    assert rows[0].key_hash is None
    assert rows[0].response_json is None
    assert _prompts(capture_client) == []


# --- the paths a capture row must not get wrong: unstored, error, bypass, kill switch ---------


@pytest.fixture
def _cache_only_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: the default of AIGW_CACHE_VERSIONS_ENABLED is off. No `_versions_env` here.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def cache_only_client(_cache_only_env: None, client: TestClient) -> TestClient:
    return login_admin(client)


@pytest.fixture
def _capture_without_cache_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_CACHE_VERSIONS_ENABLED", "true")
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "false")


@pytest.fixture
def capture_without_cache_client(
    _capture_without_cache_env: None, client: TestClient
) -> TestClient:
    return login_admin(client)


def _arranged_traced_post(
    client: TestClient, *, body: dict[str, Any] | None = None, counter: _DispatchCounter
) -> Any:
    with patch(_PATCH_TARGET, counter):
        return client.post(
            _CHAT_PATH,
            json=body or _chat_body(),
            headers={"traceparent": traceparent(_TRACE)},
        )


@pytest.mark.parametrize("write_status", ["race_lost", "not_stored"])
def test_unstored_write_is_captured_as_unstored_with_this_calls_own_answer(
    write_status: str, capture_client: TestClient, credential_blobs: Any
) -> None:
    # INVARIANT (OD-5): after a lost race the live row holds the OTHER caller's answer, so the
    # capture row must carry THIS call's own dispatched answer, never a pointer to the live row.
    _arrange_account(capture_client, credential_blobs)

    async def _refuse_to_store(*args: Any, **kwargs: Any) -> str:
        return write_status

    with patch("aigateway.routes.chat.store_global_response", _refuse_to_store):
        resp = _arranged_traced_post(capture_client, counter=_DispatchCounter())

    assert resp.status_code == 200, resp.text
    rows = _rows(capture_client, _TRACE)
    assert [row.outcome for row in rows] == ["unstored"]
    assert rows[0].key_hash is not None
    dispatched = json.loads(rows[0].response_json or "")
    assert dispatched["id"] == "resp-1"
    assert dispatched["choices"][0]["message"]["content"] == "PLAINTEXT-ANSWER-42"
    assert _state(capture_client).capture_stats.rows["unstored"] == 1


def test_failed_traced_call_writes_one_error_row(capture_client: TestClient) -> None:
    # FEATURE: no Anthropic connection is arranged, so credential resolution refuses the call in
    # Stage 2, AFTER `begin_capture`. The freeze counts `error` rows to fill `missing_count`.
    untraced = capture_client.post(_CHAT_PATH, json=_chat_body())
    assert untraced.status_code in (404, 409), untraced.text

    resp = capture_client.post(
        _CHAT_PATH, json=_chat_body(), headers={"traceparent": traceparent(_TRACE)}
    )

    assert resp.status_code == untraced.status_code
    assert resp.json()["detail"] == untraced.json()["detail"]
    rows = _rows(capture_client, _TRACE)
    assert [row.outcome for row in rows] == ["error"]
    assert rows[0].key_hash is not None
    assert rows[0].response_json is None
    assert _state(capture_client).capture_stats.rows["error"] == 1


def test_call_failing_at_dispatch_writes_one_error_row_and_keeps_the_status(
    capture_client: TestClient, credential_blobs: Any
) -> None:
    _arrange_account(capture_client, credential_blobs)

    async def _refuse(body: dict[str, Any]) -> None:
        raise HTTPException(status_code=418, detail="the provider refused")

    with patch(_PATCH_TARGET, _refuse):
        resp = capture_client.post(
            _CHAT_PATH, json=_chat_body(), headers={"traceparent": traceparent(_TRACE)}
        )

    # The dispatch layer maps a provider failure to its own 502; capture leaves that untouched.
    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"]["code"] == "provider_error"
    rows = _rows(capture_client, _TRACE)
    assert [row.outcome for row in rows] == ["error"]
    assert rows[0].key_hash is not None
    assert rows[0].response_json is None
    assert _state(capture_client).capture_stats.rows["error"] == 1


def test_traced_call_is_not_captured_when_the_kill_switch_is_off(
    cache_only_client: TestClient, credential_blobs: Any
) -> None:
    # INVARIANT (OD-1): capture stores prompt text in plaintext, so it stays off unless the
    # operator turns it on. A valid traceparent alone must not persist a prompt.
    _arrange_account(cache_only_client, credential_blobs)
    assert _state(cache_only_client).settings.cache_versions_enabled is False

    resp = _arranged_traced_post(cache_only_client, counter=_DispatchCounter())

    assert resp.status_code == 200, resp.text
    assert resp.headers["X-AIGW-Cache-Write"] == "stored", "the live cache itself is on"
    assert _count(cache_only_client, CacheCaptureEntry) == 0
    assert _count(cache_only_client, RequestCachePrompt) == 0


def test_traced_call_with_the_live_cache_off_is_captured_as_bypass_with_the_body(
    capture_without_cache_client: TestClient, credential_blobs: Any
) -> None:
    _arrange_account(capture_without_cache_client, credential_blobs)

    resp = _arranged_traced_post(capture_without_cache_client, counter=_DispatchCounter())

    assert resp.status_code == 200, resp.text
    assert resp.headers["X-AIGW-Cache"] == "bypass"
    rows = _rows(capture_without_cache_client, _TRACE)
    assert [row.outcome for row in rows] == ["bypass"]
    assert rows[0].key_hash is not None
    dispatched = json.loads(rows[0].response_json or "")
    assert dispatched["choices"][0]["message"]["content"] == "PLAINTEXT-ANSWER-42"
