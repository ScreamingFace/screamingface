"""OME-303 U3 — the shared LiteLLM transport observer, against REAL httpx and LiteLLM.

These tests deliberately drive ``litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler``
itself rather than a stand-in. The whole design rests on two claims about installed
LiteLLM 1.95.0 / httpx 0.28.1 that only the real objects can prove:

* ``post()`` resends on ``ConnectError`` via a REPLACEMENT client built by
  ``create_client()`` — which upstream calls without ``ssl_verify``; and
* httpx fires the request hook once per REDIRECT HOP.

A mocked handler would happily agree with whatever this implementation believes.
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncIterator
from decimal import Decimal, ExtendedContext, InvalidOperation, localcontext
from typing import Any

import httpx
import litellm
import pytest
from litellm.exceptions import Timeout
from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from aigateway.core.usage_accounting.hooks import (
    MAX_RAW_EVIDENCE_BYTES,
    AccountingAsyncHTTPHandler,
    build_accounting_handler,
)
from aigateway.core.usage_accounting.signals import bound_collector
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import TRANSPORT_LITELLM_ASYNC_HTTP
from aigateway.plugins.taxonomy.collector import RequestAccountingCollector

_URL = "https://provider.example/v1/chat/completions"


def _collector() -> RequestAccountingCollector:
    return RequestAccountingCollector(
        provider="openrouter",
        requested_model="openrouter/some-model",
        transport=TRANSPORT_LITELLM_ASYNC_HTTP,
    )


@pytest.fixture
def transport_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace only the TRANSPORT, leaving every other client property real.

    Patching ``_create_async_transport`` is the authoritative seam: it is the exact
    function ``create_client`` calls, so what it receives IS what the client was built
    with. That is what lets the TLS assertions below be evidence rather than assertion.
    """
    spy: dict[str, Any] = {"tls_seen": [], "handler": None}

    def _fake_transport(
        ssl_context: Any = None, ssl_verify: Any = None, shared_session: Any = None
    ) -> httpx.MockTransport:
        spy["tls_seen"].append((ssl_context, ssl_verify))
        return httpx.MockTransport(lambda request: spy["handler"](request))

    monkeypatch.setattr(AsyncHTTPHandler, "_create_async_transport", staticmethod(_fake_transport))
    return spy


def _json_response(payload: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


class _BodyReadTimeoutStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"partial":'
        raise httpx.ReadTimeout("body stalled")


class _BodyReadCancelledStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"partial":'
        raise asyncio.CancelledError


class TestSendCardinality:
    @pytest.mark.asyncio
    async def test_one_send_yields_one_record_with_raw_evidence(
        self, transport_spy: dict[str, Any]
    ) -> None:
        transport_spy["handler"] = lambda _r: _json_response({"id": "gen-1", "usage": {"cost": 1}})
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            await handler.post(url=_URL, json={"model": "m"})
        (record,) = collector.records()
        assert record.sequence == 1
        assert record.http_status == 200
        assert record.outcome == "succeeded"
        assert record.latency_ms is not None
        raw = collector.open_records()[0][1]
        assert raw == {"id": "gen-1", "usage": {"cost": 1}}
        await handler.close()

    @pytest.mark.asyncio
    async def test_hidden_connect_error_retry_produces_two_ordered_records(
        self, transport_spy: dict[str, Any]
    ) -> None:
        # Plan §4.2 / §9.8. Installed litellm 1.95.0 post() catches ConnectError, builds a
        # REPLACEMENT client and sends again. Both admissions are observed and must
        # appear — and be distinguishable as ONE dispatch.
        calls = {"n": 0}

        def _respond(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("connection refused", request=request)
            return _json_response({"id": "gen-2"})

        transport_spy["handler"] = _respond
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})
        records = collector.records()
        assert calls["n"] == 2, "litellm's hidden retry did not fire; the premise changed"
        assert len(records) == 2
        assert [r.dispatch_index for r in records] == [1, 1]
        assert [r.attempt_index for r in records] == [1, 2]
        assert records[0].outcome == "transport_error"
        assert records[0].failure_code == "transport_error"
        assert records[0].latency_ms is None
        assert records[1].outcome == "succeeded"
        await handler.close()

    @pytest.mark.asyncio
    async def test_redirect_chain_does_not_inflate_observed_attempts(
        self, transport_spy: dict[str, Any]
    ) -> None:
        # §9.13. httpx dispatches event hooks INSIDE its redirect loop, so a 307 chain
        # fires the request hook once per hop. One generation call must stay one record.
        seen = {"n": 0}

        def _respond(request: httpx.Request) -> httpx.Response:
            seen["n"] += 1
            if seen["n"] == 1:
                return httpx.Response(307, headers={"location": "https://elsewhere.example/v1"})
            return _json_response({"id": "gen-3"})

        transport_spy["handler"] = _respond
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})
        assert seen["n"] == 2, "the redirect was not followed; the premise changed"
        (record,) = collector.records()
        assert record.redirect_hop_count == 1
        assert record.http_status == 200
        await handler.close()

    @pytest.mark.asyncio
    async def test_an_unfollowable_redirect_does_not_swallow_the_litellm_resend(
        self, transport_spy: dict[str, Any]
    ) -> None:
        """A plan §12 stop condition: no observed send may disappear.

        The trace, all three steps verified against installed httpx 0.28.1 / litellm
        1.95.0 rather than assumed:

        1. ``Location`` carrying a non-printable ASCII byte IS deliverable as a header
           value, and ``httpx.URL()`` rejects it with ``InvalidURL``;
        2. ``Client._redirect_url`` converts exactly that into ``RemoteProtocolError``;
        3. ``AsyncHTTPHandler.post`` resends the ORIGINAL request once on that error.

        So the next admission is a second observed generation attempt — not the hop the
        307 promised. Folding it into the redirect's record deleted it silently while the
        request still rendered ``status=complete``. Receipt and billing remain unknown.
        """
        seen: dict[str, Any] = {"urls": []}

        def _respond(request: httpx.Request) -> httpx.Response:
            seen["urls"].append(str(request.url))
            if len(seen["urls"]) == 1:
                return httpx.Response(307, headers={"location": "https://exa\x00mple/x"})
            return _json_response({"id": "gen-after-resend"})

        transport_spy["handler"] = _respond
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})

        assert seen["urls"] == [_URL, _URL], (
            "premise changed: litellm no longer resends the original request after httpx "
            "refuses an unfollowable Location"
        )
        records = collector.records()
        assert len(records) == 2, "the resend was folded into the redirect's record"
        assert [r.dispatch_index for r in records] == [1, 1]
        assert [r.attempt_index for r in records] == [1, 2]
        # Neither is a hop: the promised redirect was never followed.
        assert [r.redirect_hop_count for r in records] == [0, 0]
        assert records[1].http_status == 200
        # The redirect's own target was never observed, so the request may not claim
        # complete evidence no matter what the mappers later attach.
        assert collector.status() == "partial"
        assert collector.status() == "partial"
        await handler.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("plugin", "model", "payload"),
        [
            (
                AnthropicProviderPlugin(),
                "anthropic/claude-3-haiku-20240307",
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-3-haiku-20240307",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            ),
            (
                OpenRouterProviderPlugin(),
                "openrouter/openai/gpt-4o-mini",
                {
                    "id": "gen-1",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "openai/gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            ),
        ],
    )
    async def test_each_supported_plugin_reaches_the_observed_handler_through_real_litellm(
        self,
        monkeypatch: pytest.MonkeyPatch,
        transport_spy: dict[str, Any],
        plugin: Any,
        model: str,
        payload: dict[str, Any],
    ) -> None:
        transport_spy["handler"] = lambda _request: _json_response(payload)

        def fail_unobserved_fallback(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("LiteLLM ignored the injected accounting handler")

        monkeypatch.setattr(
            "litellm.llms.anthropic.chat.handler.get_async_httpx_client",
            fail_unobserved_fallback,
        )
        monkeypatch.setattr(
            "litellm.llms.custom_httpx.llm_http_handler.get_async_httpx_client",
            fail_unobserved_fallback,
        )
        for field in (
            "pre_call_rules",
            "post_call_rules",
            "callbacks",
            "input_callback",
            "success_callback",
            "failure_callback",
            "_async_input_callback",
            "_async_success_callback",
            "_async_failure_callback",
        ):
            monkeypatch.setattr(litellm, field, [], raising=False)
        monkeypatch.setattr(litellm, "model_fallbacks", None, raising=False)
        monkeypatch.setattr(litellm, "model_alias_map", {}, raising=False)

        def discard_background_log(async_coroutine: Any) -> None:
            async_coroutine.close()

        monkeypatch.setattr(
            GLOBAL_LOGGING_WORKER,
            "ensure_initialized_and_enqueue",
            discard_background_log,
        )

        handler = AccountingAsyncHTTPHandler()
        collector = RequestAccountingCollector(
            provider=plugin.custom_llm_provider,
            requested_model=model,
            transport=TRANSPORT_LITELLM_ASYNC_HTTP,
        )
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 1,
            "api_key": "test-key",
            "api_base": _URL,
            "client": handler,
        }
        try:
            with bound_collector(collector):
                collector.begin_dispatch()
                await plugin.chat_completion(body)

            assert len(collector.records()) == 1
        finally:
            await handler.close()


def _is_verifying(entry: tuple[Any, Any]) -> bool:
    """Whether a captured ``(ssl_context, ssl_verify)`` pair means TLS is verified.

    LiteLLM resolves ``ssl_verify=True`` into a certifi-backed ``SSLContext`` and passes
    it as ``ssl_context`` (with ``ssl_verify=None``); it passes ``False`` through as the
    bool. So "is this verified" is a question about the pair, not either half.
    """
    ssl_context, ssl_verify = entry
    if isinstance(ssl_context, ssl.SSLContext):
        return ssl_context.verify_mode is not ssl.CERT_NONE
    return ssl_verify is True


class TestTlsPreservation:
    @pytest.mark.asyncio
    async def test_primary_and_replacement_clients_both_verify_tls(
        self, transport_spy: dict[str, Any]
    ) -> None:
        calls = {"n": 0}

        def _respond(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("boom", request=request)
            return _json_response({"ok": True})

        transport_spy["handler"] = _respond
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})
        seen = transport_spy["tls_seen"]
        assert len(seen) >= 2, "expected a primary and a replacement client"
        assert all(_is_verifying(entry) for entry in seen), seen
        await handler.close()

    @pytest.mark.asyncio
    async def test_a_hostile_global_cannot_disarm_tls_on_either_client(
        self, transport_spy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The test that makes the ``create_client`` override load-bearing.

        Upstream's retry calls ``create_client(timeout=…, event_hooks=…)`` with NO
        ``ssl_verify``, so the replacement client re-resolves TLS from
        ``litellm.ssl_verify`` / ``$SSL_VERIFY``. With that global turned off, an
        unpinned handler silently sends the gateway's provider credential over an
        unverified connection on the RETRY path only — a failure that never shows up in
        the happy path. The paired assertion below proves the base class really does
        behave that way, so this is a defence against a live hazard, not a ritual.
        """
        monkeypatch.setattr(litellm, "ssl_verify", False)
        monkeypatch.delenv("SSL_VERIFY", raising=False)

        # Baseline: the UNPINNED base class, called exactly as litellm's retry calls it.
        AsyncHTTPHandler(ssl_verify=True).create_client(timeout=None, event_hooks=None)
        baseline = transport_spy["tls_seen"][-1]
        assert not _is_verifying(baseline), (
            "premise changed: the base class now inherits ssl_verify on the retry path, "
            "so the create_client override may no longer be required"
        )

        transport_spy["tls_seen"].clear()
        handler = AccountingAsyncHTTPHandler()
        handler.create_client(timeout=None, event_hooks=None)
        seen = transport_spy["tls_seen"]
        assert len(seen) == 2, "expected a primary and a replacement client"
        assert all(_is_verifying(entry) for entry in seen), seen
        await handler.close()

    def test_the_upstream_retry_still_omits_ssl_verify(self) -> None:
        # A TRIPWIRE, not a behaviour test. If a LiteLLM upgrade starts forwarding
        # ssl_verify on the retry path, the override below becomes redundant — and if it
        # renames create_client, the override silently stops applying. Either way a human
        # must look. Verified against installed 1.95.0.
        import inspect

        source = inspect.getsource(AsyncHTTPHandler.post)
        assert "self.create_client(timeout=timeout, event_hooks=self.event_hooks)" in source

    @pytest.mark.asyncio
    async def test_replacement_client_keeps_the_accounting_hooks(
        self, transport_spy: dict[str, Any]
    ) -> None:
        handler = AccountingAsyncHTTPHandler()
        replacement = handler.create_client(timeout=None, event_hooks=None)
        assert replacement.event_hooks["request"], "replacement lost the request hook"
        assert replacement.event_hooks["response"], "replacement lost the response hook"
        await replacement.aclose()
        await handler.close()

    def test_default_transport_and_redirect_behaviour_are_untouched(self) -> None:
        # Plan §12: changing LiteLLM's production transport/redirect behaviour is a stop
        # condition. The handler must inherit them, not restate them.
        handler = build_accounting_handler()
        assert handler.client.follow_redirects is True


class TestHooksAreTotal:
    @pytest.mark.asyncio
    async def test_a_failing_hook_cannot_fail_or_create_another_send_admission(
        self, transport_spy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # §9.11 and a plan §12 stop condition. A hook raising ConnectError would be
        # caught by litellm's post() and cause a SECOND observed send admission.
        calls = {"n": 0}

        def _respond(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return _json_response({"id": "gen-4"})

        transport_spy["handler"] = _respond

        def _explode(_request: object) -> None:
            raise httpx.ConnectError("hook sabotage")

        monkeypatch.setattr(
            RequestAccountingCollector, "on_send_admitted", lambda self, request: _explode(request)
        )
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            response = await handler.post(url=_URL, json={"model": "m"})
        assert response is not None
        assert response.status_code == 200, "the caller lost a completed provider response"
        assert calls["n"] == 1, "a hook failure caused a second observed send admission"
        assert collector.status() == "partial"
        assert collector.status() == "partial"
        await handler.close()

    @pytest.mark.asyncio
    async def test_body_read_failure_preserves_the_transport_timeout(
        self, transport_spy: dict[str, Any]
    ) -> None:
        """Accounting is an observer: it must not turn transport errors into hook errors."""
        calls = {"n": 0}

        def _respond(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, stream=_BodyReadTimeoutStream())

        transport_spy["handler"] = _respond
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector), pytest.raises(Timeout):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})

        assert calls["n"] == 1, "a body-read failure must not cause a hidden resend"
        (record,) = collector.records()
        assert record.outcome == "indeterminate"
        assert record.latency_ms is None
        assert collector.status() == "partial"
        assert collector.status() == "partial"
        await handler.close()

    @pytest.mark.asyncio
    async def test_cancellation_still_propagates(self, transport_spy: dict[str, Any]) -> None:
        # The reachable cancellation point is the response hook's awaited body read. The
        # production hooks stay installed here; replacing event_hooks would only test httpx.
        transport_spy["handler"] = lambda _r: httpx.Response(200, stream=_BodyReadCancelledStream())

        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector), pytest.raises(asyncio.CancelledError):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})

        (record,) = collector.records()
        assert record.outcome == "indeterminate"
        assert record.http_status is None
        assert record.latency_ms is None
        assert collector.status() == "partial"
        await handler.close()

    @pytest.mark.asyncio
    async def test_no_collector_bound_is_a_no_op(self, transport_spy: dict[str, Any]) -> None:
        # A streaming or otherwise unaccounted request shares the app-lifetime handler
        # only if something goes wrong elsewhere.
        # wrong upstream; either way an unbound context must not explode.
        transport_spy["handler"] = lambda _r: _json_response({"ok": True})
        handler = AccountingAsyncHTTPHandler()
        response = await handler.post(url=_URL, json={"model": "m"})
        assert response is not None
        assert response.status_code == 200
        await handler.close()


class TestBoundedEvidence:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            b'{"usage":{"cost":0.0012},"metadata":1e1000000000000000000}',
            b'{"usage":{"cost":0.0012},"metadata":NaN}',
            b'{"usage":{"cost":0.0012},"metadata":Infinity}',
            b'{"usage":{"cost":0.0012},"metadata":-Infinity}',
        ],
        ids=["extreme-exponent", "nan", "positive-infinity", "negative-infinity"],
    )
    async def test_unsafe_json_numbers_cannot_fail_a_completed_response(
        self, transport_spy: dict[str, Any], payload: bytes
    ) -> None:
        # INVARIANT: provider evidence is optional observation. A parser callback failure
        # must discard the raw body, never replace the provider's completed response.
        transport_spy["handler"] = lambda _r: httpx.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        try:
            with bound_collector(collector):
                collector.begin_dispatch()
                response = await handler.post(url=_URL, json={"model": "m"})
        finally:
            await handler.close()

        assert response is not None
        assert response.status_code == 200
        assert collector.open_records()[0][1] is None
        (record,) = collector.records()
        assert record.outcome == "succeeded"
        assert record.http_status == 200
        assert collector.status() == "complete"

    @pytest.mark.asyncio
    async def test_decimal_context_cannot_admit_non_finite_raw_evidence(
        self, transport_spy: dict[str, Any]
    ) -> None:
        payload = b'{"usage":{"cost":0.0012},"metadata":1e1000000000000000000}'
        transport_spy["handler"] = lambda _r: httpx.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        try:
            with localcontext(ExtendedContext) as context, bound_collector(collector):
                context.traps[InvalidOperation] = False
                collector.begin_dispatch()
                response = await handler.post(url=_URL, json={"model": "m"})
        finally:
            await handler.close()

        assert response is not None
        assert response.status_code == 200
        assert collector.open_records()[0][1] is None

    @pytest.mark.asyncio
    async def test_unparseable_content_length_cannot_fail_a_completed_response(
        self, transport_spy: dict[str, Any]
    ) -> None:
        transport_spy["handler"] = lambda _r: httpx.Response(
            200,
            content=b'{"usage":{"cost":0.0012}}',
            headers={
                "content-type": "application/json",
                "content-length": "9" * 4_301,
            },
        )
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        try:
            with bound_collector(collector):
                collector.begin_dispatch()
                response = await handler.post(url=_URL, json={"model": "m"})
        finally:
            await handler.close()

        assert response is not None
        assert response.status_code == 200
        assert collector.open_records()[0][1] is None
        (record,) = collector.records()
        assert record.latency_ms is None
        assert collector.status() == "partial"

    @pytest.mark.asyncio
    async def test_an_oversized_body_is_not_retained_and_latency_is_null(
        self, transport_spy: dict[str, Any]
    ) -> None:
        big = {"pad": "x" * (MAX_RAW_EVIDENCE_BYTES + 1024)}
        transport_spy["handler"] = lambda _r: _json_response(big)
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})
        (record,) = collector.records()
        assert collector.open_records()[0][1] is None
        assert record.latency_ms is None, "unread body must not report time-to-headers"
        assert collector.status() == "partial"
        await handler.close()

    @pytest.mark.asyncio
    async def test_deep_json_cannot_fail_an_otherwise_successful_response(
        self, transport_spy: dict[str, Any]
    ) -> None:
        payload = b"[" * 20_000 + b"0" + b"]" * 20_000
        transport_spy["handler"] = lambda _r: httpx.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            response = await handler.post(url=_URL, json={"model": "m"})
        assert response is not None
        assert response.status_code == 200
        assert collector.open_records()[0][1] is None
        (record,) = collector.records()
        assert record.outcome == "succeeded"
        assert collector.status() == "complete"
        await handler.close()

    @pytest.mark.asyncio
    async def test_raw_decimal_cost_keeps_all_wire_digits(
        self, transport_spy: dict[str, Any]
    ) -> None:
        payload = b'{"usage":{"cost":0.123456789012345678}}'
        transport_spy["handler"] = lambda _r: httpx.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})
        raw = collector.open_records()[0][1]
        assert raw is not None
        assert raw["usage"]["cost"] == Decimal("0.123456789012345678")
        await handler.close()

    @pytest.mark.asyncio
    async def test_a_non_json_body_yields_no_evidence_but_still_records_the_send(
        self, transport_spy: dict[str, Any]
    ) -> None:
        transport_spy["handler"] = lambda _r: httpx.Response(200, text="not json")
        handler = AccountingAsyncHTTPHandler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "m"})
        (record,) = collector.records()
        assert record.http_status == 200
        assert collector.open_records()[0][1] is None
        await handler.close()


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_closes_the_underlying_client(self, transport_spy: dict[str, Any]) -> None:
        # §9.12 — the app-lifetime handler must be closed in lifespan shutdown, not left
        # to __del__.
        #
        # AIDEV-NOTE (OME-918): bind the client ONCE and assert on that object. Since
        # litellm 1.97 ``AsyncHTTPHandler.client`` is a self-healing property that rebuilds
        # the client whenever it finds the stored one closed, so re-reading it here would
        # hand back a fresh OPEN client and undo the very thing being measured. The
        # invariant is unchanged — the pool this handler opened must really be released.
        handler = build_accounting_handler()
        client = handler.client
        assert client.is_closed is False
        await handler.close()
        assert client.is_closed is True


class TestSharedHandlerConcurrency:
    """§9.25 against the SHARED handler — the form of the claim that can actually fail.

    ``test_collector`` proves the ContextVar isolates collectors. What it cannot prove is
    that ONE app-lifetime handler, whose hooks are bound once at construction and reused
    by every caller in the process, routes each send to the right caller's records.
    Cross-attribution here would put one tenant's provider spend on another's invoice.
    """

    @pytest.mark.asyncio
    async def test_interleaved_requests_never_exchange_records(
        self, transport_spy: dict[str, Any]
    ) -> None:
        started = asyncio.Event()

        async def _respond(request: httpx.Request) -> httpx.Response:
            # Force real interleaving: the first caller parks inside the transport until
            # the second has also entered it, so both are mid-send simultaneously.
            body = request.content.decode()
            if "slow" in body:
                started.set()
                await asyncio.sleep(0.05)
            else:
                await started.wait()
            return _json_response({"who": "slow" if "slow" in body else "fast"})

        transport_spy["handler"] = _respond
        handler = build_accounting_handler()

        async def _call(model: str, sends: int) -> tuple[str, int, set[int]]:
            collector = RequestAccountingCollector(
                provider="openrouter",
                requested_model=model,
                transport=TRANSPORT_LITELLM_ASYNC_HTTP,
            )
            with bound_collector(collector):
                collector.begin_dispatch()
                for _ in range(sends):
                    await handler.post(url=_URL, json={"model": model})
            records = collector.records()
            response_owners = {
                raw["who"] for _attempt_id, raw, _succeeded in collector.open_records() if raw
            }
            assert response_owners == {model}, (
                f"{model} collected another caller's response: {response_owners}"
            )
            return model, len(records), {r.sequence for r in records}

        slow, fast = await asyncio.gather(_call("slow", 2), _call("fast", 3))
        assert slow[1] == 2, "the slow caller lost or gained a record"
        assert fast[1] == 3, "the fast caller lost or gained a record"
        # Sequence is per-collector, so each caller counts from 1 independently rather
        # than sharing a process-wide counter that would leak concurrency into the wire.
        assert slow[2] == {1, 2}
        assert fast[2] == {1, 2, 3}
        await handler.close()

    @pytest.mark.asyncio
    async def test_an_unaccounted_caller_sharing_the_handler_records_nothing(
        self, transport_spy: dict[str, Any]
    ) -> None:
        # The handler is app-lifetime; a request with no bound collector must not spill
        # its sends into whichever collector happens to be alive elsewhere.
        transport_spy["handler"] = lambda _r: _json_response({"ok": True})
        handler = build_accounting_handler()
        collector = _collector()
        with bound_collector(collector):
            collector.begin_dispatch()
            await handler.post(url=_URL, json={"model": "accounted"})
        # Outside the binding entirely — this send belongs to nobody.
        await handler.post(url=_URL, json={"model": "unaccounted"})
        assert len(collector.records()) == 1
        await handler.close()
