"""OME-303 — the route-facing seam in ``routes.chat_accounting``.

Two properties dominate here and neither is visible from the route tests:

* **least privilege** — a provider mapper must never be handed a credential or a prompt;
* **non-raising** — a mapper bug must never fail a completed provider response. The
  gateway degrades the evidence instead of losing the caller's answer.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import (
    CacheReference,
    DirectCost,
    InputTokenUsage,
    ProviderUsageAccountingEvidence,
    RequestAccountingCollector,
    TokenUsage,
    UsageAccountingStrategy,
    new_gateway_call_id,
)
from aigateway.routes.chat_accounting import (
    AccountingSession,
    attach_hit_metadata,
    attach_success_metadata,
    begin_accounting,
    dispatch_body_with_accounting,
    finalize_provider_evidence,
    note_conversion_failure,
    note_dispatch_failure,
    safe_request_view,
)


def _session(*, supported: bool = True, provider: str = "openrouter") -> AccountingSession:
    collector = (
        RequestAccountingCollector(
            provider=provider, requested_model="x/y", transport="litellm_async_http"
        )
        if supported
        else None
    )
    return AccountingSession(
        provider=provider,
        supported=supported,
        collector=collector,
        gateway_call_id=(
            collector.gateway_call_id if collector is not None else new_gateway_call_id()
        ),
        inject_shared_handler=supported,
    )


class _RecordingPlugin:
    """A provider plugin stand-in that captures exactly what the mappers were shown."""

    def __init__(self, *, raises: bool = False, reference: CacheReference | None = None) -> None:
        self.seen: list[dict[str, Any]] = []
        self.reference_seen: list[Any] = []
        self._raises = raises
        self._reference = reference

    def usage_accounting_strategy(self) -> UsageAccountingStrategy:
        return UsageAccountingStrategy.litellm_async_http()

    def normalize_chat_usage_accounting(
        self, *, request_body: Any, raw_response: Any, final_response: Any, failed: bool = False
    ) -> ProviderUsageAccountingEvidence:
        self.seen.append(
            {
                "request_body": dict(request_body),
                "raw_response": raw_response,
                "final_response": final_response,
                "failed": failed,
            }
        )
        if self._raises:
            raise RuntimeError("mapper exploded")
        return ProviderUsageAccountingEvidence(
            supported=True,
            usage=TokenUsage(
                status="partial",
                source="provider_raw_response",
                input=InputTokenUsage(total=1),
            ),
        )

    def cache_reference_from_cached_response(self, cached: Any) -> CacheReference | None:
        self.reference_seen.append(cached)
        if self._raises:
            raise RuntimeError("cache reference mapper exploded")
        return self._reference


class _Request:
    headers: dict[str, str] = {}

    class _State:
        pass

    state = _State()


def _observe(collector: RequestAccountingCollector, *, status: int = 200) -> object:
    marker = object()
    collector.begin_dispatch()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=status, raw_evidence={"usage": {"cost": 1}})
    return marker


class TestSafeRequestView:
    def test_the_credential_never_reaches_a_mapper(self) -> None:
        # §7 least privilege. By finalize time the body carries the injected provider
        # credential; a mapper needs none of it to read a `usage` block.
        view = safe_request_view({"model": "x/y", "api_key": "sk-ant-SECRET"})
        assert "api_key" not in view
        assert "SECRET" not in str(view)

    def test_prompt_content_never_reaches_a_mapper(self) -> None:
        view = safe_request_view(
            {
                "model": "x/y",
                "messages": [{"role": "user", "content": "PRIVATE PROMPT"}],
                "system": "PRIVATE SYSTEM",
            }
        )
        assert "PRIVATE PROMPT" not in str(view)
        assert "PRIVATE SYSTEM" not in str(view)

    def test_the_injected_transport_client_is_hidden(self) -> None:
        # Handing a mapper the live handler would give a plugin the shared transport.
        view = safe_request_view({"model": "x/y", "client": object()})
        assert "client" not in view

    def test_any_structured_value_is_dropped_whatever_its_name_is(self) -> None:
        """The structural half of the guard — this is what makes it hold over time.

        A future provider adding ``prompt_blocks`` or ``input_items`` would otherwise
        leak content through a field name this allowlist had never heard of.
        """
        view = safe_request_view(
            {
                "model": "x/y",
                "prompt_blocks": [{"text": "FUTURE LEAK"}],
                "tool_config": {"secret": "FUTURE LEAK"},
            }
        )
        assert "FUTURE LEAK" not in str(view)
        assert set(view) == {"model"}

    def test_scalar_dispatch_facts_a_mapper_legitimately_needs_survive(self) -> None:
        view = safe_request_view(
            {"model": "x/y", "temperature": 0.7, "max_tokens": 100, "api_key": "k"}
        )
        assert view == {"model": "x/y", "temperature": 0.7, "max_tokens": 100}


class TestFinalizeIsNonRaising:
    def test_a_raising_mapper_does_not_propagate(self) -> None:
        """The response was already produced and may have been billed.

        Letting a mapper bug raise here would turn a completed, potentially billed
        provider attempt into a 500 for the caller — accounting causing the very loss it
        exists to measure.
        """
        session = _session()
        assert session.collector is not None
        _observe(session.collector)
        finalize_provider_evidence(
            session,
            plugin=_RecordingPlugin(raises=True),  # type: ignore[arg-type]
            request_body={"model": "x/y"},
            final_response={"usage": {}},
        )
        assert session.collector.status() == "complete"

    def test_a_raising_mapper_leaves_usage_unavailable_without_poisoning_capture(self) -> None:
        session = _session()
        assert session.collector is not None
        _observe(session.collector)
        finalize_provider_evidence(
            session,
            plugin=_RecordingPlugin(raises=True),  # type: ignore[arg-type]
            request_body={"model": "x/y"},
            final_response=None,
        )
        assert session.collector.records()[0].usage.status == "unavailable"
        assert session.collector.status() == "complete"

    def test_no_session_is_a_silent_no_op(self) -> None:
        finalize_provider_evidence(
            None,
            plugin=_RecordingPlugin(),  # type: ignore[arg-type]
            request_body={},
            final_response=None,
        )

    def test_an_unsupported_provider_session_is_a_no_op(self) -> None:
        plugin = _RecordingPlugin()
        finalize_provider_evidence(
            _session(supported=False),
            plugin=plugin,  # type: ignore[arg-type]
            request_body={},
            final_response=None,
        )
        assert plugin.seen == []

    def test_a_malformed_mapper_result_cannot_fail_success_attachment(self) -> None:
        session = _session()
        assert session.collector is not None
        _observe(session.collector)

        class _Malformed(_RecordingPlugin):
            def normalize_chat_usage_accounting(self, **_kwargs: Any) -> Any:
                return object()

        finalize_provider_evidence(
            session,
            plugin=_Malformed(),  # type: ignore[arg-type]
            request_body={"model": "x/y"},
            final_response={"usage": {}},
        )
        body = attach_success_metadata({"id": "msg_1"}, session, cache_status="miss")
        assert body["id"] == "msg_1"
        (attempt,) = body["_aigw"]["usage_accounting"]["attempts"]
        assert attempt["usage"]["status"] == "unavailable"

    def test_an_evidence_subclass_degrades_before_overrides_can_run(self) -> None:
        class _HostileEvidence(ProviderUsageAccountingEvidence):
            armed = False

            def __getattribute__(self, name: str) -> Any:
                if type(self).armed and name == "usage":
                    raise RuntimeError("subclass field override must not run")
                return super().__getattribute__(name)

        evidence = _HostileEvidence(supported=True)
        _HostileEvidence.armed = True

        class _SubclassMapper(_RecordingPlugin):
            def normalize_chat_usage_accounting(self, **_kwargs: Any) -> Any:
                return evidence

        session = _session()
        assert session.collector is not None
        _observe(session.collector)
        finalize_provider_evidence(
            session,
            plugin=_SubclassMapper(),  # type: ignore[arg-type]
            request_body={"model": "x/y"},
            final_response={"usage": {}},
        )

        body = attach_success_metadata({"id": "msg_1"}, session, cache_status="miss")
        (attempt,) = body["_aigw"]["usage_accounting"]["attempts"]
        assert attempt["usage"]["status"] == "unavailable"


class TestFinalResponseFallbackTargeting:
    def test_only_the_last_succeeded_send_receives_the_converted_response(self) -> None:
        """The converted body describes ONE call — the one that became the answer.

        Offering it to an earlier failed attempt would let that attempt's record inherit
        usage it never produced, inflating the accounted spend.
        """
        session = _session()
        collector = session.collector
        assert collector is not None
        collector.begin_dispatch()
        first = object()
        collector.on_send_admitted(first)
        collector.on_response_completed(first, status=500, raw_evidence=None)
        second = object()
        collector.on_send_admitted(second)
        collector.on_response_completed(second, status=200, raw_evidence={"usage": {}})

        plugin = _RecordingPlugin()
        final = {"usage": {"prompt_tokens": 3}}
        finalize_provider_evidence(
            session,
            plugin=plugin,  # type: ignore[arg-type]
            request_body={"model": "x/y"},
            final_response=final,
        )
        assert [call["final_response"] for call in plugin.seen] == [None, final]
        assert [call["failed"] for call in plugin.seen] == [True, False]

    def test_with_no_successful_send_nothing_receives_the_converted_response(self) -> None:
        session = _session()
        collector = session.collector
        assert collector is not None
        collector.begin_dispatch()
        marker = object()
        collector.on_send_admitted(marker)
        collector.on_response_completed(marker, status=500, raw_evidence=None)

        plugin = _RecordingPlugin()
        finalize_provider_evidence(
            session,
            plugin=plugin,  # type: ignore[arg-type]
            request_body={"model": "x/y"},
            final_response={"usage": {"prompt_tokens": 3}},
        )
        assert [call["final_response"] for call in plugin.seen] == [None]


class TestCacheHitWiring:
    def test_the_plugin_is_asked_for_limited_cached_response_evidence(self) -> None:
        # §9.5 — core cannot parse `usage.cost` itself; that would put provider
        # semantics in core, which may not import a plugin.
        reference = CacheReference(
            direct_cost=DirectCost.reported(
                amount="0.0012",
                unit="openrouter_credits",
                source="cached_response.usage.cost",
            )
        )
        plugin = _RecordingPlugin(reference=reference)
        cached = {"id": "gen-1", "usage": {"cost": 0.0012}}
        body = attach_hit_metadata(cached, _session(), plugin=plugin)  # type: ignore[arg-type]
        assert plugin.reference_seen == [cached]
        rendered = body["_aigw"]["usage_accounting"]["cache"]["reference"]
        assert rendered["direct_cost"]["unit"] == "openrouter_credits"
        assert body["_aigw"]["request_economics"]["observed_new_attempts"] == 0

    def test_the_real_openrouter_plugin_does_not_claim_cached_float_is_exact(self) -> None:
        # The cache stores LiteLLM's converted response, so a historical float has no
        # proof that it preserves the provider's original JSON number.
        body = attach_hit_metadata(
            {"id": "gen-1", "usage": {"cost": 0.0012, "prompt_tokens": 56}},
            _session(),
            plugin=OpenRouterProviderPlugin(),
        )
        reference = body["_aigw"]["usage_accounting"]["cache"]["reference"]
        assert reference["direct_cost"] == {
            "status": "unavailable",
            "amount": None,
            "unit": None,
            "source": None,
        }
        assert reference["coverage"] == "final_successful_response_only"
        assert "usd" not in str(reference).lower()

    def test_a_raising_reference_mapper_still_returns_the_cached_answer(self) -> None:
        cached = {"id": "gen-1", "choices": []}
        body = attach_hit_metadata(
            cached,
            _session(),
            plugin=_RecordingPlugin(raises=True),  # type: ignore[arg-type]
        )
        assert body["id"] == "gen-1"
        assert body["_aigw"]["usage_accounting"]["cache"]["reference"] is None

    def test_a_malformed_reference_result_still_returns_the_cached_answer(self) -> None:
        cached = {"id": "gen-1", "choices": []}

        class _Malformed(_RecordingPlugin):
            def cache_reference_from_cached_response(self, _cached: Any) -> Any:
                return object()

        body = attach_hit_metadata(
            cached,
            _session(),
            plugin=_Malformed(),  # type: ignore[arg-type]
        )
        assert body["id"] == "gen-1"
        assert body["_aigw"]["usage_accounting"]["cache"]["reference"] is None

    def test_a_reference_subclass_degrades_before_overrides_can_run(self) -> None:
        class _HostileReference(CacheReference):
            def as_json(self) -> dict[str, Any]:
                raise RuntimeError("subclass method must not run")

        cached = {"id": "gen-1", "choices": []}
        body = attach_hit_metadata(
            cached,
            _session(),
            plugin=_RecordingPlugin(reference=_HostileReference()),  # type: ignore[arg-type]
        )

        assert body["id"] == "gen-1"
        assert body["_aigw"]["usage_accounting"]["cache"]["reference"] is None

    def test_the_replayed_cache_row_is_never_mutated(self) -> None:
        # INVARIANT (§6): `cached` is the store's row. Mutating it would put `_aigw`
        # into the cache — for this process and, with a shared store, for everyone.
        cached = {"id": "gen-1", "usage": {"cost": 1}}
        attach_hit_metadata(cached, _session(), plugin=OpenRouterProviderPlugin())
        assert "_aigw" not in cached

    def test_a_missing_session_hit_is_returned_byte_for_byte(self) -> None:
        cached = {"id": "gen-1"}
        assert attach_hit_metadata(cached, None, plugin=OpenRouterProviderPlugin()) is cached

    def test_cache_decimals_are_restored_to_the_previous_json_number_shape(self) -> None:
        cached = {"id": "gen-1", "score": Decimal("1E+2")}

        body = attach_hit_metadata(cached, None, plugin=OpenRouterProviderPlugin())

        assert body == {"id": "gen-1", "score": 100.0}
        assert type(body["score"]) is float
        assert cached["score"] == Decimal("1E+2")

    def test_cache_decimal_carrier_does_not_claim_original_money_provenance(self) -> None:
        cached: dict[str, Any] = {
            "id": "gen-1",
            "usage": {"cost": Decimal("0.0038799200000000002")},
        }

        body = attach_hit_metadata(cached, _session(), plugin=OpenRouterProviderPlugin())

        reference = body["_aigw"]["usage_accounting"]["cache"]["reference"]
        assert reference["direct_cost"]["status"] == "unavailable"
        assert type(body["usage"]["cost"]) is float
        assert cached["usage"]["cost"] == Decimal("0.0038799200000000002")


class TestSuccessAttachment:
    def test_a_missing_session_miss_is_returned_untouched(self) -> None:
        result = {"id": "msg_1"}
        assert attach_success_metadata(result, None, cache_status="miss") is result

    def test_the_stored_object_is_not_mutated(self) -> None:
        result = {"id": "msg_1"}
        attached = attach_success_metadata(result, _session(), cache_status="miss")
        assert "_aigw" not in result
        assert attached["_aigw"]["usage_accounting"]["cache"] == {
            "status": "miss",
            "reference": None,
        }


class TestHandlerInjection:
    def test_the_body_is_not_mutated_when_the_client_is_injected(self) -> None:
        # INVARIANT: `body` is the dict the OME-305 cache keyed. A dispatch control
        # written into it would leak backwards into the cache identity.
        body = {"model": "x/y"}
        handler = object()
        out = dispatch_body_with_accounting(body, _session(), handler)
        assert out is not body
        assert "client" not in body
        assert out["client"] is handler

    @pytest.mark.parametrize(
        ("session", "handler"),
        [(None, object()), ("supported", None)],
    )
    def test_nothing_is_injected_without_both_a_session_and_a_handler(
        self, session: Any, handler: Any
    ) -> None:
        resolved = _session() if session == "supported" else session
        body = {"model": "x/y"}
        assert dispatch_body_with_accounting(body, resolved, handler) is body

    def test_an_unsupported_provider_is_never_instrumented(self) -> None:
        # Injecting the observed handler for a provider that declared no strategy would
        # record sends the contract promises not to account for.
        body = {"model": "x/y"}
        assert dispatch_body_with_accounting(body, _session(supported=False), object()) is body

    def test_a_future_provider_owned_transport_never_gets_the_shared_litellm_client(self) -> None:
        session = _session()
        session.inject_shared_handler = False
        body = {"model": "x/y"}
        assert dispatch_body_with_accounting(body, session, object()) is body

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("plugin", "model"),
        [
            (AnthropicProviderPlugin(), "anthropic/claude-haiku-4-5"),
            (OpenRouterProviderPlugin(), "openrouter/x/y"),
        ],
    )
    async def test_supported_provider_dispatch_forwards_the_declared_shared_handler(
        self, monkeypatch: pytest.MonkeyPatch, plugin: Any, model: str
    ) -> None:
        seen: dict[str, Any] = {}

        async def fake_acompletion(**body: Any) -> dict[str, Any]:
            seen.update(body)
            return {"id": "response"}

        monkeypatch.setattr("litellm.acompletion", fake_acompletion)
        strategy = plugin.usage_accounting_strategy()
        assert strategy.uses_shared_litellm_http is True

        session = _session(provider=plugin.custom_llm_provider)
        handler = object()
        body = dispatch_body_with_accounting({"model": model}, session, handler)
        await plugin.chat_completion(body)

        assert seen["client"] is handler


class TestStrategyContainment:
    def test_a_raising_strategy_degrades_to_unsupported(self) -> None:
        class _RaisingStrategy(_RecordingPlugin):
            def usage_accounting_strategy(self) -> UsageAccountingStrategy:
                raise ValueError("bad provider strategy")

        session = begin_accounting(
            _Request(),  # type: ignore[arg-type]
            plugin=_RaisingStrategy(),  # type: ignore[arg-type]
            provider="future-provider",
            model="future-provider/model",
        )

        assert session is not None
        assert session.supported is False
        assert session.collector is None

    def test_a_strategy_subclass_degrades_to_unsupported(self, caplog) -> None:
        class _HostileStrategy(UsageAccountingStrategy):
            @property
            def is_supported(self) -> bool:
                raise RuntimeError("subclass property must not run")

        class _SubclassPlugin(_RecordingPlugin):
            def usage_accounting_strategy(self) -> UsageAccountingStrategy:
                return _HostileStrategy.litellm_async_http()

        session = begin_accounting(
            _Request(),  # type: ignore[arg-type]
            plugin=_SubclassPlugin(),  # type: ignore[arg-type]
            provider="future-provider",
            model="future-provider/model",
        )

        assert session is not None
        assert session.supported is False
        assert session.collector is None
        assert "provider usage-accounting strategy is invalid" in caplog.text


class TestConversionFailureWiring:
    def test_the_open_record_is_marked_with_the_core_owned_code(self) -> None:
        session = _session()
        assert session.collector is not None
        _observe(session.collector)
        note_conversion_failure(session)
        (record,) = session.collector.records()
        assert record.outcome == "conversion_error"
        assert record.failure_code == "response_conversion_failed"

    def test_it_is_a_no_op_without_a_collector(self) -> None:
        note_conversion_failure(None)
        note_conversion_failure(_session(supported=False))


class TestDispatchFailureWiring:
    def test_final_transport_failure_resolves_the_open_attempt(self) -> None:
        session = _session()
        collector = session.collector
        assert collector is not None
        collector.begin_dispatch()
        marker = object()
        collector.on_send_admitted(marker)
        note_dispatch_failure(session, httpx.ConnectError("provider-controlled text"))
        (record,) = collector.records()
        assert record.outcome == "transport_error"
        assert record.failure_code == "transport_connect_error"
        assert collector.status() == "complete"
        assert "provider-controlled text" not in str(record.as_json())

    def test_http_200_body_error_corrects_the_succeeded_attempt(self) -> None:
        session = _session()
        collector = session.collector
        assert collector is not None
        _observe(collector)
        note_dispatch_failure(
            session,
            HTTPException(status_code=429, detail={"code": "rate_limited"}),
            provider_error_after_response=True,
        )
        (record,) = collector.records()
        assert record.outcome == "provider_error"
        assert record.failure_code == "provider_status_error"

    def test_unclassified_local_failure_after_response_is_indeterminate(self) -> None:
        session = _session()
        collector = session.collector
        assert collector is not None
        _observe(collector)

        note_dispatch_failure(session, RuntimeError("local failure"))

        (record,) = collector.records()
        assert record.outcome == "indeterminate"
        assert record.failure_code is None

    def test_terminal_finalized_attempt_does_not_mutate_an_earlier_success(self) -> None:
        session = _session()
        collector = session.collector
        assert collector is not None
        collector.begin_dispatch()
        first = object()
        collector.on_send_admitted(first)
        collector.on_response_completed(first, status=200, raw_evidence={})
        second = object()
        collector.on_send_admitted(second)
        assert (
            collector.finalize_last_open_failure(
                outcome="transport_error",
                failure_code="transport_connect_error",
            )
            is True
        )

        note_dispatch_failure(session, httpx.ConnectError("terminal failure"))

        records = collector.records()
        assert [record.outcome for record in records] == ["succeeded", "transport_error"]

    def test_conversion_after_retry_targets_only_the_final_success(self) -> None:
        session = _session()
        collector = session.collector
        assert collector is not None
        collector.begin_dispatch()
        first = object()
        collector.on_send_admitted(first)
        assert (
            collector.finalize_last_open_failure(
                outcome="transport_error",
                failure_code="transport_connect_error",
            )
            is True
        )
        second = object()
        collector.on_send_admitted(second)
        collector.on_response_completed(second, status=200, raw_evidence={})

        note_conversion_failure(session)

        records = collector.records()
        assert [record.outcome for record in records] == ["transport_error", "conversion_error"]


class TestErrorRenderingIsContained:
    """The app-wide handler must never make an error worse than it already was."""

    def _request(self, session: Any) -> Any:
        class _State:
            aigw_accounting = session

        class _Request:
            state = _State()

        return _Request()

    def test_an_unrenderable_detail_falls_back_to_the_default_handler(self) -> None:
        # A `detail` that JSONResponse cannot encode must not take down error handling
        # for every route in the gateway — it degrades to Starlette's own handler.
        from fastapi import HTTPException

        from aigateway.routes.chat_accounting import accounting_error_response

        exc = HTTPException(status_code=400, detail={"bad": object()})
        assert accounting_error_response(self._request(_session()), exc) is None

    def test_a_request_without_a_session_is_never_intercepted(self) -> None:
        from fastapi import HTTPException

        from aigateway.routes.chat_accounting import accounting_error_response

        assert accounting_error_response(self._request(None), HTTPException(404)) is None

    def test_an_accounted_error_keeps_the_exception_headers(self) -> None:
        # Dropping `Retry-After` on a 429 would make accounting change backpressure
        # behaviour for the caller.
        from fastapi import HTTPException

        from aigateway.routes.chat_accounting import accounting_error_response

        exc = HTTPException(429, detail={"code": "rate_limited"}, headers={"Retry-After": "5"})
        rendered = accounting_error_response(self._request(_session()), exc)
        assert rendered is not None
        assert rendered.headers["retry-after"] == "5"
        assert rendered.status_code == 429

    def test_a_dispatched_bypass_error_keeps_the_actual_cache_status(self) -> None:
        from aigateway.routes.chat_accounting import accounting_error_response

        session = _session()
        session.cache_status = "bypass"
        session.note_dispatch()
        rendered = accounting_error_response(
            self._request(session), HTTPException(502, detail={"code": "provider_error"})
        )
        assert rendered is not None
        body = json.loads(bytes(rendered.body))
        assert body["_aigw"]["usage_accounting"]["cache"]["status"] == "bypass"
