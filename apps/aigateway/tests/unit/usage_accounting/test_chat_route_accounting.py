"""OME-303 — the accounting response contract on POST /v1/chat/completions.

These tests hold the current wire decisions in place: default-on non-streaming accounting, the
``_aigw`` namespace, the cache boundary, and the rule that none of it may reach
``request_cache_entries.response_json``.
"""

from __future__ import annotations

import json
import time
from functools import partial
from typing import Any, Literal, cast
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from litellm.exceptions import RateLimitError
from litellm.types.utils import ModelResponse, Usage

from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.request_cache import RequestCacheWrite
from aigateway.core.usage_accounting import active_collector
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.openrouter_provider.dispatch_errors import (
    _embedded_error_exception,
)
from aigateway.plugins.taxonomy.types import UsageAccountingStrategy

_CHAT_PATH = "/v1/chat/completions"
_ANTHROPIC_DISPATCH = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)
_ANTHROPIC_STREAM_DISPATCH = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion_stream"
)
# The plugin METHOD (accounting controls not yet applied) vs the inner LiteLLM-facing
# handler the plugin delegates to (controls applied). Assert at the seam that matches
# the claim — see TestTheBodyLiteLLMActuallyReceives.
_ANTHROPIC_INNER_DISPATCH = "aigateway.plugins.anthropic_provider.plugin.chat_completion"
_ANTHROPIC_STRATEGY = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.usage_accounting_strategy"
)
_ACCOUNTING_HEADERS = {"X-AIGW-Accounting": "enabled"}


# --- arrangement (mirrors tests/unit/test_chat_global_cache_route.py) ----------


async def _create_active_connection(account_id: str, *, label: str = "default"):
    store = OAuthConnectionStore()
    connection = await store.create_pending(
        account_id=account_id, provider="anthropic", label=label, connection_id=uuid4()
    )
    return await store.complete(connection, label=label, identity=None)


def _arrange_account(client: TestClient, credential_blobs) -> str:
    account_id = client.get("/v1/auth/me").json()["id"]
    portal = client.portal
    assert portal is not None, "the TestClient was used outside its context manager"
    connection = portal.call(partial(_create_active_connection, account_id))
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection.id)),
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )
    return account_id


def _chat_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


def _provider_payload(**extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "msg_1",
        "model": "claude-haiku-4-5",
        "choices": [{"message": {"content": "ANSWER"}, "finish_reason": "stop"}],
        "usage": {"input_tokens": 100, "output_tokens": 25},
    }
    payload.update(extra)
    return payload


class _Dispatch:
    """A stand-in provider dispatch that records the bodies it was handed."""

    def __init__(self, payload: dict[str, Any] | None = None, raises: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self._payload = payload if payload is not None else _provider_payload()
        self._raises = raises

    async def __call__(self, body: dict[str, Any]) -> Any:
        self.calls.append(dict(body))
        if self._raises is not None:
            raise self._raises
        return dict(self._payload)


class _StreamingDispatch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.collectors: list[Any] = []

    async def __call__(self, body: dict[str, Any]):
        self.calls.append(dict(body))
        self.collectors.append(active_collector())
        yield {"choices": [{"delta": {"content": "streamed"}}]}


class _Store:
    """Minimal in-memory request-cache store honouring the OME-305 contract."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.set_calls: list[RequestCacheWrite] = []
        self.get_calls: list[str] = []

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
        self.get_calls.append(key_hash)
        return self.rows.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> Literal["stored", "race_lost"]:
        self.set_calls.append(entry)
        if entry.key_hash in self.rows:
            return "race_lost"
        self.rows[entry.key_hash] = entry.response
        return "stored"


@pytest.fixture
def chat_client(monkeypatch, client: TestClient) -> TestClient:
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


def _install(client: TestClient, store: _Store) -> _Store:
    cast(Any, client.app).state.request_cache_store = store
    return store


def _aigw(response: Any) -> dict[str, Any]:
    body = response.json()
    assert "_aigw" in body, f"accounted response carried no _aigw: {body}"
    return body["_aigw"]


# --- activation ---------------------------------------------------------------


class TestActivation:
    def test_accounting_is_default_on(self, credential_blobs, chat_client) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body())
        assert response.status_code == 200, response.text
        assert "_aigw" in response.json()
        assert "_aigw_accounting" not in response.json()

    def test_the_legacy_header_does_not_change_accounting(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 200, response.text
        metadata = _aigw(response)
        assert set(metadata) == {"usage_accounting", "request_economics"}
        assert metadata["usage_accounting"]["schema"] == "aigw.chat_usage_accounting"
        assert metadata["request_economics"]["schema"] == "aigw.request_economics"

    def test_cached_provider_metadata_cannot_impersonate_taxonomy(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        store = _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            first = chat_client.post(_CHAT_PATH, json=_chat_body())
        assert first.status_code == 200, first.text
        stored = next(iter(store.rows.values()))
        stored["_aigw"] = {"forged": True}

        second = chat_client.post(_CHAT_PATH, json=_chat_body())

        assert second.status_code == 200, second.text
        assert second.json()["_aigw"] != {"forged": True}
        assert second.json()["_aigw"]["usage_accounting"]["cache"]["status"] == "hit"

    def test_an_unknown_legacy_header_value_is_ignored(self, credential_blobs, chat_client) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(
                _CHAT_PATH, json=_chat_body(), headers={"X-AIGW-Accounting": "unknown"}
            )
        assert response.status_code == 200, response.text
        assert len(dispatch.calls) == 1
        assert "_aigw" in response.json()

    def test_the_header_does_not_change_the_cache_key(self, credential_blobs, chat_client) -> None:
        """§9.2 — THE cache-partition test.

        A legacy header must not enter the effective request and partition the shared
        cache, even though accounting itself is now always active for non-streaming calls.
        """
        _arrange_account(chat_client, credential_blobs)
        store = _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            plain = chat_client.post(_CHAT_PATH, json=_chat_body())
            assert plain.status_code == 200, plain.text
            negotiated = chat_client.post(
                _CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS
            )
        assert negotiated.status_code == 200, negotiated.text
        assert len(store.get_calls) == 2
        assert store.get_calls[0] == store.get_calls[1], "the opt-in changed the key_hash"
        # The second request therefore HIT the row the first one wrote.
        assert negotiated.headers["X-AIGW-Cache"] == "hit"

    def test_the_legacy_header_does_not_change_provider_parameter_validation(
        self, credential_blobs, chat_client
    ) -> None:
        # §9.2 second half: an unknown parameter must fail closed identically either way.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        body = _chat_body(definitely_not_a_real_parameter=1)
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            plain = chat_client.post(_CHAT_PATH, json=body)
            negotiated = chat_client.post(_CHAT_PATH, json=body, headers=_ACCOUNTING_HEADERS)
        assert plain.status_code == negotiated.status_code == 400
        assert plain.json()["detail"] == negotiated.json()["detail"]


class TestDefaultOnAccounting:
    def test_non_streaming_accounting_needs_no_header(self, credential_blobs, chat_client) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body())

        assert response.status_code == 200, response.text
        metadata = _aigw(response)
        assert metadata["usage_accounting"]["schema"] == "aigw.chat_usage_accounting"

    def test_legacy_accounting_header_is_ignored(self, credential_blobs, chat_client) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(
                _CHAT_PATH,
                json=_chat_body(),
                headers={"X-AIGW-Accounting": "unknown"},
            )

        assert response.status_code == 200, response.text
        assert len(dispatch.calls) == 1
        assert "_aigw" in response.json()

    def test_streaming_bypasses_accounting_even_with_a_legacy_header(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            response = chat_client.post(
                _CHAT_PATH,
                json=_chat_body(stream=True),
                headers=_ACCOUNTING_HEADERS,
            )

        assert response.status_code != 400 or (
            response.json().get("detail", {}).get("code")
            != "accounting_not_supported_for_streaming"
        )


class TestEarlySafeErrors:
    @pytest.mark.parametrize(
        ("model", "detail"),
        [
            ("claude-haiku-4-5", "model must be provider-prefixed"),
            ("future-provider/model", "unknown provider: future-provider"),
        ],
    )
    def test_model_resolution_error_carries_accounting_metadata(
        self, chat_client: TestClient, model: str, detail: str
    ) -> None:
        store = _install(chat_client, _Store())

        response = chat_client.post(
            _CHAT_PATH,
            json=_chat_body(model=model),
            headers=_ACCOUNTING_HEADERS,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"] == detail
        metadata = body["_aigw"]
        assert metadata["usage_accounting"]["capture_status"] == "accounting_not_supported"
        assert metadata["usage_accounting"]["attempts"] == []
        assert metadata["request_economics"]["observed_new_attempts"] == 0
        assert metadata["request_economics"]["direct_cost_status"] == "not_applicable"
        assert store.get_calls == []

    @pytest.mark.parametrize("model", ["claude-haiku-4-5", "future-provider/model"])
    def test_default_on_model_resolution_error_carries_accounting(
        self, chat_client: TestClient, model: str
    ) -> None:
        response = chat_client.post(_CHAT_PATH, json=_chat_body(model=model))

        assert response.status_code == 400
        assert set(response.json()) == {"detail", "_aigw"}

    @pytest.mark.parametrize(
        ("content", "expected_detail"),
        [
            (b"{", "request body must be valid JSON"),
            (b"[]", "model and messages are required"),
        ],
    )
    def test_body_errors_carry_accounting_metadata(
        self, chat_client: TestClient, content: bytes, expected_detail: str
    ) -> None:
        response = chat_client.post(
            _CHAT_PATH,
            content=content,
            headers={**_ACCOUNTING_HEADERS, "Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == expected_detail
        metadata = _aigw(response)
        assert metadata["usage_accounting"]["capture_status"] == "accounting_not_supported"
        assert metadata["usage_accounting"]["attempts"] == []
        assert metadata["request_economics"]["direct_cost_status"] == "not_applicable"

    def test_legacy_accounting_header_does_not_precede_malformed_body_parsing(
        self, chat_client: TestClient
    ) -> None:
        response = chat_client.post(
            _CHAT_PATH,
            content=b"{",
            headers={"X-AIGW-Accounting": "unknown", "Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "request body must be valid JSON"
        assert "_aigw" in response.json()


class TestStreaming:
    @pytest.mark.parametrize(
        "body",
        [
            {"stream": True},
            _chat_body(model="future-provider/model", stream=True),
            _chat_body(model="claude-haiku-4-5", stream=True),
        ],
    )
    def test_streaming_early_errors_have_no_accounting_metadata(
        self, chat_client: TestClient, body: dict[str, Any]
    ) -> None:
        response = chat_client.post(_CHAT_PATH, json=body)

        assert response.status_code == 400
        assert set(response.json()) == {"detail"}

    def test_streaming_with_a_legacy_header_bypasses_accounting(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _StreamingDispatch()
        with patch(_ANTHROPIC_STREAM_DISPATCH, dispatch):
            response = chat_client.post(
                _CHAT_PATH, json=_chat_body(stream=True), headers=_ACCOUNTING_HEADERS
            )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"_aigw"' not in response.text
        assert len(dispatch.calls) == 1
        assert "client" not in dispatch.calls[0]
        assert dispatch.collectors == [None]

    def test_streaming_without_a_legacy_header_bypasses_accounting(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _StreamingDispatch()
        with patch(_ANTHROPIC_STREAM_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(stream=True))
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"_aigw"' not in response.text
        assert len(dispatch.calls) == 1
        assert "client" not in dispatch.calls[0]
        assert dispatch.collectors == [None]


# --- the cache boundary -------------------------------------------------------


class TestCacheBoundary:
    def test_a_miss_stores_provider_json_and_returns_a_copy_with_metadata(
        self, credential_blobs, chat_client
    ) -> None:
        """§9.7 and the §6 persistence boundary, in one assertion pair.

        The stored row must remain provider-compatible forever — it is replayed to every
        later caller of this body — and the metadata must reach only the copy returned
        to THIS caller.
        """
        _arrange_account(chat_client, credential_blobs)
        store = _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 200, response.text
        assert response.headers["X-AIGW-Cache"] == "miss"
        assert "_aigw" in response.json()
        (write,) = store.set_calls
        assert "_aigw" not in write.response
        assert set(write.response) == {"id", "model", "choices", "usage"}
        assert _aigw(response)["usage_accounting"]["cache"]["reference"] is None

    @pytest.mark.parametrize(
        "key",
        ["_aigw", "usage_accounting", "request_economics", "direct_cost", "estimated_cost"],
    )
    def test_no_accounting_key_can_reach_the_persisted_row(
        self, credential_blobs, chat_client, key: str
    ) -> None:
        # §12 stop condition: metadata must never be persisted to a cache row.
        _arrange_account(chat_client, credential_blobs)
        store = _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        (write,) = store.set_calls
        assert key not in json.dumps(write.response)

    def test_a_hit_dispatches_nothing_and_reports_zero_new_attempts(
        self, credential_blobs, chat_client
    ) -> None:
        # §9.4 — the whole economic point of the cache: a hit costs no new provider work,
        # and `observed_new_attempts=0` is the current-request proof of it.
        _arrange_account(chat_client, credential_blobs)
        store = _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_DISPATCH, dispatch):
            first = chat_client.post(_CHAT_PATH, json=_chat_body())
            assert first.status_code == 200, first.text
            hit = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert hit.status_code == 200, hit.text
        assert hit.headers["X-AIGW-Cache"] == "hit"
        assert len(dispatch.calls) == 1, "the hit dispatched the provider again"
        metadata = _aigw(hit)
        assert metadata["usage_accounting"]["attempts"] == []
        assert metadata["usage_accounting"]["cache"]["status"] == "hit"
        assert metadata["usage_accounting"]["capture_status"] == "not_applicable"
        economics = metadata["request_economics"]
        assert economics["observed_new_attempts"] == 0
        assert economics["known_direct_cost_subtotals"] == []
        assert economics["direct_cost_status"] == "not_applicable"
        # A hit must not add a second row, and the stored row still carries no metadata.
        assert len(store.set_calls) == 1
        assert "_aigw" not in store.set_calls[0].response

    def test_an_anthropic_hit_reports_historical_usage_but_no_money(
        self, credential_blobs, chat_client
    ) -> None:
        # The reference describes only the cached final response. Anthropic has no
        # provider-authored direct-cost response field, so its cost status is absent.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            chat_client.post(_CHAT_PATH, json=_chat_body())
            hit = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert hit.headers["X-AIGW-Cache"] == "hit"
        reference = _aigw(hit)["usage_accounting"]["cache"]["reference"]
        assert reference["coverage"] == "final_successful_response_only"
        assert reference["incurred_in_current_request"] is False
        assert reference["direct_cost"]["status"] == "absent"


# --- dispatch grouping and status --------------------------------------------


class TestDispatchGrouping:
    def test_a_supported_provider_with_zero_observed_sends_is_partial(
        self, credential_blobs, chat_client
    ) -> None:
        """§9.22 — capture is partial while attempt-level cost is not applicable.

        This is the shape of a patched dispatch: the plugin returned an answer but no
        HTTP send passed the observer. Claiming `complete` would assert the provider was
        called zero times for a request that really was served. Request economics still
        has no observed attempt to summarize; capture status carries that uncertainty.
        """
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        metadata = _aigw(response)
        assert metadata["usage_accounting"]["capture_status"] == "partial"
        assert metadata["usage_accounting"]["attempts"] == []
        assert metadata["request_economics"]["direct_cost_status"] == "not_applicable"

    def test_gateway_overload_retries_bump_the_dispatch_index(
        self, credential_blobs, chat_client
    ) -> None:
        """§9.9 — a gateway overload retry is a NEW dispatch.

        ``test_collector`` already pins ``[1, 2]`` for two dispatches and ``test_handler``
        pins ``[1, 1]`` for litellm's hidden in-``post()`` resend. What only the route can
        prove is the WIRING: that the backpressure retry really opens a second dispatch
        instead of appending to the first. So this dispatch reports its sends through the
        same public collector API the httpx hooks use, which makes ``dispatch_index``
        observable on the wire rather than as an internal counter.
        """
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        class _OverloadedTwice:
            def __init__(self) -> None:
                self.attempts = 0
                # The collector keys pending sends by id(); holding the markers keeps
                # CPython from recycling an address and aliasing two distinct sends.
                self.markers: list[object] = []

            async def __call__(self, body: dict[str, Any]) -> Any:
                self.attempts += 1
                collector = active_collector()
                assert collector is not None, "the dispatch ran outside the bound collector"
                marker = object()
                self.markers.append(marker)
                collector.on_send_admitted(marker)
                if self.attempts == 1:
                    collector.on_response_completed(marker, status=529, raw_evidence=None)
                    raise RateLimitError(
                        message="overloaded", llm_provider="anthropic", model="claude-haiku-4-5"
                    )
                collector.on_response_completed(
                    marker, status=200, raw_evidence=_provider_payload()
                )
                return _provider_payload()

        dispatch = _OverloadedTwice()
        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 200, response.text
        assert dispatch.attempts == 2, "the overload retry never happened"
        attempts = _aigw(response)["usage_accounting"]["attempts"]
        assert [attempt["dispatch_index"] for attempt in attempts] == [1, 2], (
            "the retry must open a new dispatch, not extend the first"
        )
        assert [attempt["attempt_index"] for attempt in attempts] == [1, 1], (
            "a gateway retry is not a hidden litellm resend"
        )
        assert [attempt["outcome"] for attempt in attempts] == [
            "provider_error",
            "succeeded",
        ]
        # Both local transport admissions were observed; billing is not inferred.
        assert _aigw(response)["request_economics"]["observed_new_attempts"] == 2


class TestAnthropicRouteMapping:
    """§9.16-9.18 — the Anthropic evidence a real caller sees on the wire."""

    def _succeed(self) -> Any:
        class _Reporting:
            def __init__(self) -> None:
                self.bodies: list[dict[str, Any]] = []
                self.markers: list[object] = []

            async def __call__(self, body: dict[str, Any]) -> Any:
                self.bodies.append(dict(body))
                collector = active_collector()
                assert collector is not None
                marker = object()
                self.markers.append(marker)
                collector.on_send_admitted(marker)
                collector.on_response_completed(
                    marker,
                    status=200,
                    raw_evidence={
                        "id": "msg_route",
                        "model": "claude-haiku-4-5",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 25,
                            "cache_read_input_tokens": 20,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                )
                return _provider_payload()

        return _Reporting()

    def test_the_raw_anthropic_usage_reaches_the_response(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = self._succeed()
        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 200, response.text
        metadata = _aigw(response)
        (attempt,) = metadata["usage_accounting"]["attempts"]
        assert attempt["provider"] == "anthropic"
        assert attempt["outcome"] == "succeeded"
        assert attempt["provider_response_id"] == "msg_route"
        assert attempt["usage"]["input"]["total"] == 120
        assert attempt["usage"]["input"]["uncached"] == 100
        assert attempt["usage"]["input"]["cache_read"] == 20
        assert attempt["usage"]["output"]["total"] == 25
        assert attempt["usage"]["source"] == "provider_raw_response"
        assert attempt["latency_ms"] is not None
        assert metadata["usage_accounting"]["capture_status"] == "complete"

    def test_a_valid_accounted_request_allocates_one_gateway_call_id(
        self, credential_blobs, chat_client
    ) -> None:
        # OME-938 retargeted the patch, NOT the claim. The id is now minted once per request by
        # `middleware.call_id` and consumed by the session and the collector, so patching the
        # two former mint sites observes zero calls while the behaviour is perfectly correct.
        # There is exactly one minter left; the assertion is unchanged — one allocation per
        # request, and the response carries that same id.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with (
            patch(_ANTHROPIC_DISPATCH, self._succeed()),
            patch(
                "aigateway.middleware.call_id.new_gateway_call_id",
                return_value="call_" + "a" * 32,
            ) as allocate_call_id,
        ):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)

        assert response.status_code == 200, response.text
        assert allocate_call_id.call_count == 1
        assert _aigw(response)["usage_accounting"]["gateway_call_id"] == "call_" + "a" * 32

    def test_anthropic_reports_no_money_on_the_wire(self, credential_blobs, chat_client) -> None:
        # §9.18 / §12 stop condition: no USD may appear for Anthropic in the MVP.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, self._succeed()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        metadata = _aigw(response)
        (attempt,) = metadata["usage_accounting"]["attempts"]
        assert attempt["direct_cost"]["status"] == "absent"
        economics = metadata["request_economics"]
        assert economics["observed_new_attempts"] == 1
        assert economics["known_direct_cost_subtotals"] == []
        assert economics["direct_cost_status"] == "unavailable"
        assert "usd" not in json.dumps(metadata).lower()

    def test_installed_litellm_converted_usage_reaches_the_rendered_wire(
        self, credential_blobs, chat_client
    ) -> None:
        class _ConvertedReporting:
            async def __call__(self, _body: dict[str, Any]) -> ModelResponse:
                collector = active_collector()
                assert collector is not None
                marker = object()
                collector.on_send_admitted(marker)
                collector.on_response_completed(marker, status=200, raw_evidence=None)
                return ModelResponse(
                    id="msg_converted",
                    model="claude-haiku-4-5",
                    choices=[],
                    usage=Usage(
                        prompt_tokens=130,
                        completion_tokens=25,
                        total_tokens=155,
                        prompt_tokens_details={
                            "text_tokens": 100,
                            "cached_tokens": 20,
                            "cache_creation_tokens": 10,
                            "cache_creation_token_details": {
                                "ephemeral_5m_input_tokens": 7,
                                "ephemeral_1h_input_tokens": 3,
                            },
                        },
                    ),
                )

        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _ConvertedReporting()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)

        assert response.status_code == 200, response.text
        (attempt,) = _aigw(response)["usage_accounting"]["attempts"]
        assert attempt["provider_response_id"] == "msg_converted"
        assert attempt["usage"]["source"] == "provider_converted_response"
        assert attempt["usage"]["input"] == {
            "total": 130,
            "uncached": 100,
            "cache_read": 20,
            "cache_write": 10,
            "cache_write_by_ttl": [
                {"ttl_seconds": 300, "tokens": 7},
                {"ttl_seconds": 3600, "tokens": 3},
            ],
        }


class TestTheBodyLiteLLMActuallyReceives:
    """§9.17 — asserted at the LiteLLM-facing seam, not at the plugin method.

    ``apply_anthropic_dispatch_controls`` runs INSIDE ``AnthropicProviderPlugin.
    chat_completion``, so a test that patches that method would assert on a body the
    controls had not been applied to yet and pass while proving nothing. Patching the
    inner handler instead captures the dict that reaches ``litellm.acompletion``.
    """

    def test_hidden_litellm_retries_are_disabled_and_the_handler_is_injected(
        self, credential_blobs, chat_client
    ) -> None:
        # WHY it matters: litellm's OUTER retry loop would spend money this accounting
        # cannot see, making dispatch_index a lower bound instead of a complete account.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_INNER_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 200, response.text
        (body,) = dispatch.calls
        assert body["num_retries"] == 0
        assert body["max_retries"] == 0
        # Without the injected client no send is ever observed and the whole contract
        # degrades silently to `partial`.
        assert body["client"] is cast(Any, chat_client.app).state.usage_accounting_handler

    def test_a_default_on_request_disables_retries_and_is_instrumented(
        self, credential_blobs, chat_client
    ) -> None:
        # The retry controls are a provider-level correctness property, not an
        # accounting-only one: they must not appear or vanish with the header. The
        # client injection is now default-on for supported non-streaming providers.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_INNER_DISPATCH, dispatch):
            chat_client.post(_CHAT_PATH, json=_chat_body())
        (body,) = dispatch.calls
        assert body["num_retries"] == 0
        assert body["max_retries"] == 0
        assert "client" in body, "a default-on request was not instrumented"

    def test_the_negotiation_header_is_never_forwarded_to_the_provider(
        self, credential_blobs, chat_client
    ) -> None:
        # The opt-in is a gateway concern. Forwarding it could trip a provider's own
        # unknown-parameter validation, which the frozen decisions forbid it affecting.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_INNER_DISPATCH, dispatch):
            chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        (body,) = dispatch.calls
        rendered = json.dumps({k: str(v) for k, v in body.items()}).lower()
        assert "x-aigw-accounting" not in rendered


class TestConversionFailure:
    """§9.19-9.20 — the provider answered, but the gateway could not render its answer.

    The provider very likely BILLED this call, so it must not be reported as a provider
    error: that would tell Engine the provider rejected work it actually performed and
    the operator would under-count real spend.
    """

    class _Unrenderable:
        """A provider response object whose ``model_dump`` raises, like a real one can."""

        def model_dump(self) -> dict[str, Any]:
            raise ValueError("SECRET-INTERNAL-STATE cannot be serialized")

    def _dispatch(self) -> Any:
        unrenderable = self._Unrenderable()

        class _Reporting:
            def __init__(self) -> None:
                self.markers: list[object] = []

            async def __call__(self, body: dict[str, Any]) -> Any:
                collector = active_collector()
                assert collector is not None
                marker = object()
                self.markers.append(marker)
                collector.on_send_admitted(marker)
                collector.on_response_completed(
                    marker, status=200, raw_evidence={"usage": {"input_tokens": 7}}
                )
                return unrenderable

        return _Reporting()

    def test_the_admitted_send_is_still_reported_as_an_attempt(
        self, credential_blobs, chat_client
    ) -> None:
        # The whole point: the send happened and is accounted for, even though the
        # caller receives an error.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, self._dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 502, response.text
        metadata = response.json()["_aigw"]
        (attempt,) = metadata["usage_accounting"]["attempts"]
        assert metadata["request_economics"]["observed_new_attempts"] == 1
        assert attempt["http_status"] == 200

    def test_the_outcome_is_conversion_error_not_provider_error(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, self._dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        (attempt,) = response.json()["_aigw"]["usage_accounting"]["attempts"]
        assert attempt["outcome"] == "conversion_error"
        assert attempt["failure_code"] == "response_conversion_failed"

    def test_captured_usage_survives_a_conversion_failure(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, self._dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)

        (attempt,) = response.json()["_aigw"]["usage_accounting"]["attempts"]
        assert attempt["usage"]["input"]["total"] is None
        assert attempt["usage"]["input"]["uncached"] == 7
        assert attempt["usage"]["source"] == "provider_raw_response"
        assert attempt["usage"]["status"] == "partial"

    def test_nothing_is_cached_when_the_response_could_not_be_rendered(
        self, credential_blobs, chat_client
    ) -> None:
        # A row that cannot be rendered must never be replayed to future callers.
        _arrange_account(chat_client, credential_blobs)
        store = _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, self._dispatch()):
            chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert store.set_calls == []

    def test_no_internal_or_provider_text_leaks_into_the_error(
        self, credential_blobs, chat_client
    ) -> None:
        # §9.19 — the exception text is provider-influenced and must not be published.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, self._dispatch()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        rendered = json.dumps(response.json())
        assert "SECRET-INTERNAL-STATE" not in rendered
        assert "primes below one hundred" not in rendered

    def test_a_default_on_conversion_failure_carries_accounting(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        class _Plain:
            async def __call__(self, body: dict[str, Any]) -> Any:
                return TestConversionFailure._Unrenderable()

        with patch(_ANTHROPIC_DISPATCH, _Plain()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body())
        assert response.status_code == 502
        assert set(response.json()) == {"detail", "_aigw"}

    def test_a_non_object_provider_result_is_a_conversion_failure(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        store = _install(chat_client, _Store())

        class _ListResult:
            async def __call__(self, body: dict[str, Any]) -> Any:
                return [{"provider_private": "must-not-cross"}]

        with patch(_ANTHROPIC_DISPATCH, _ListResult()):
            response = chat_client.post(_CHAT_PATH, json=_chat_body())

        assert response.status_code == 502
        assert "provider_private" not in response.text
        accounting = response.json()["_aigw"]["usage_accounting"]
        assert accounting["capture_status"] == "partial"
        assert accounting["attempts"] == []
        assert store.rows == {}

    def test_plugin_local_conversion_failure_uses_the_core_conversion_outcome(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        class _PluginConversionError(HTTPException):
            aigw_non_retryable = True
            aigw_response_conversion_error = True

        async def dispatch(_plugin: Any, _body: dict[str, Any]) -> Any:
            collector = active_collector()
            assert collector is not None
            marker = object()
            collector.on_send_admitted(marker)
            collector.on_response_completed(
                marker,
                status=200,
                raw_evidence={
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    }
                },
            )
            raise _PluginConversionError(502, detail={"code": "provider_error"})

        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 502
        (attempt,) = response.json()["_aigw"]["usage_accounting"]["attempts"]
        assert attempt["outcome"] == "conversion_error"
        assert attempt["failure_code"] == "response_conversion_failed"


class TestDispatchFailureClassification:
    def test_http_200_body_error_is_not_published_as_success(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        async def dispatch(_plugin: Any, _body: dict[str, Any]) -> Any:
            collector = active_collector()
            assert collector is not None
            marker = object()
            collector.on_send_admitted(marker)
            collector.on_response_completed(
                marker,
                status=200,
                raw_evidence={
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    }
                },
            )
            raise _embedded_error_exception(429)

        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 429
        attempts = response.json()["_aigw"]["usage_accounting"]["attempts"]
        assert attempts
        assert all(attempt["outcome"] == "provider_error" for attempt in attempts)
        assert all(attempt["failure_code"] == "provider_status_error" for attempt in attempts)
        assert all(attempt["usage"]["input"]["total"] == 2 for attempt in attempts)

    def test_unclassified_local_error_after_response_is_indeterminate_not_success(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        class _GatewayLocalError(HTTPException):
            aigw_non_retryable = True

        async def dispatch(_plugin: Any, _body: dict[str, Any]) -> Any:
            collector = active_collector()
            assert collector is not None
            marker = object()
            collector.on_send_admitted(marker)
            collector.on_response_completed(marker, status=200, raw_evidence={})
            raise _GatewayLocalError(503, detail={"code": "gateway_local"})

        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 503
        (attempt,) = response.json()["_aigw"]["usage_accounting"]["attempts"]
        assert attempt["outcome"] == "indeterminate"
        assert attempt["failure_code"] is None

    def test_final_transport_escape_resolves_the_open_attempt(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        async def dispatch(_plugin: Any, _body: dict[str, Any]) -> Any:
            collector = active_collector()
            assert collector is not None
            collector.on_send_admitted(object())
            raise httpx.ConnectError("provider-controlled text")

        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 502
        metadata = response.json()["_aigw"]
        (attempt,) = metadata["usage_accounting"]["attempts"]
        assert attempt["outcome"] == "transport_error"
        assert attempt["failure_code"] == "transport_connect_error"
        assert metadata["usage_accounting"]["capture_status"] == "complete"
        assert "provider-controlled text" not in response.text

    def test_pre_dispatch_error_keeps_the_actual_cache_miss_status(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        async def reject_credentials(*_args: Any, **_kwargs: Any) -> Any:
            raise HTTPException(401, detail={"code": "auth_required"})

        with patch("aigateway.routes.chat._credential_target_for_chat", reject_credentials):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 401
        cache = response.json()["_aigw"]["usage_accounting"]["cache"]
        assert cache["status"] == "miss"


class TestTheClientFieldIsGatewayOwned:
    """OME-303 makes ``client`` in the dispatch body MEANINGFUL, so it becomes a target.

    A caller who could plant one would hand LiteLLM an httpx client of their choosing —
    their own transport, their own TLS policy, their own destination — with the
    gateway's provider credential injected into every request it makes. These tests
    assert that stays impossible on both the negotiated and the plain path.
    """

    @pytest.mark.parametrize("headers", [{}, _ACCOUNTING_HEADERS])
    def test_a_caller_supplied_client_is_refused(
        self, credential_blobs, chat_client, headers: dict[str, str]
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_INNER_DISPATCH, dispatch):
            response = chat_client.post(
                _CHAT_PATH, json=_chat_body(client="hostile"), headers=headers
            )
        assert response.status_code == 400, response.text
        assert dispatch.calls == [], "a caller-planted client reached provider dispatch"

    def test_a_caller_cannot_disable_tls_verification(self, credential_blobs, chat_client) -> None:
        # `ssl_verify` is a stripped dispatch control, so it must never survive to the
        # body LiteLLM sees — and must not be turned into an unknown-param 400 either.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_INNER_DISPATCH, dispatch):
            response = chat_client.post(
                _CHAT_PATH, json=_chat_body(ssl_verify=False), headers=_ACCOUNTING_HEADERS
            )
        assert response.status_code == 200, response.text
        (body,) = dispatch.calls
        assert body.get("ssl_verify") is not False

    def test_a_caller_cannot_reintroduce_hidden_retries(
        self, credential_blobs, chat_client
    ) -> None:
        # Caller-set retry counts would silently multiply sends beyond the accounting
        # contract's pinned observation boundary.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with patch(_ANTHROPIC_INNER_DISPATCH, dispatch):
            response = chat_client.post(
                _CHAT_PATH,
                json=_chat_body(num_retries=5, max_retries=5),
                headers=_ACCOUNTING_HEADERS,
            )
        if response.status_code == 200:
            (body,) = dispatch.calls
            assert body["num_retries"] == 0
            assert body["max_retries"] == 0
        else:
            assert response.status_code == 400
            assert dispatch.calls == []


# --- unsupported providers ----------------------------------------------------


class TestUnsupportedProviderEconomics:
    """The route-level half of the ``collector is None`` ambiguity.

    A provider with no declared accounting strategy still DISPATCHES, so provider activity
    may happen, but produces no observed records. The renderer sees the same
    ``collector is None`` a cache hit produces, so only ``supported``/``cache_status`` can
    keep "we cannot see this provider's spend" from being published as "this cost
    nothing".
    """

    def test_an_unsupported_miss_dispatches_yet_never_claims_complete_cost_evidence(
        self, credential_blobs, chat_client
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with (
            patch(_ANTHROPIC_STRATEGY, return_value=UsageAccountingStrategy.unsupported()),
            patch(_ANTHROPIC_DISPATCH, dispatch),
        ):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert response.status_code == 200, response.text
        assert response.headers["X-AIGW-Cache"] == "miss"
        assert len(dispatch.calls) == 1, "premise changed: the unsupported provider never ran"
        metadata = _aigw(response)
        assert metadata["usage_accounting"]["capture_status"] == "accounting_not_supported"
        assert metadata["usage_accounting"]["attempts"] == []
        economics = metadata["request_economics"]
        # Zero observed attempts means attempt-level cost is not applicable. The separate
        # capture status carries the measurement limit and prevents a complete-cost claim.
        assert economics["observed_new_attempts"] == 0
        assert economics["known_direct_cost_subtotals"] == []
        assert economics["direct_cost_status"] == "not_applicable"

    def test_an_unsupported_cache_hit_reports_no_current_cost(
        self, credential_blobs, chat_client
    ) -> None:
        # The exemption that keeps the fix honest rather than merely pessimistic: on a hit
        # no new provider work happened at all, so there is no unobserved cost to be
        # missing. The status word still says the provider is unaccountable.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        dispatch = _Dispatch()
        with (
            patch(_ANTHROPIC_STRATEGY, return_value=UsageAccountingStrategy.unsupported()),
            patch(_ANTHROPIC_DISPATCH, dispatch),
        ):
            first = chat_client.post(_CHAT_PATH, json=_chat_body())
            assert first.status_code == 200, first.text
            hit = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert hit.headers["X-AIGW-Cache"] == "hit"
        assert len(dispatch.calls) == 1, "the hit dispatched the provider again"
        metadata = _aigw(hit)
        assert metadata["usage_accounting"]["capture_status"] == "accounting_not_supported"
        economics = metadata["request_economics"]
        assert economics["observed_new_attempts"] == 0
        assert economics["direct_cost_status"] == "not_applicable"
