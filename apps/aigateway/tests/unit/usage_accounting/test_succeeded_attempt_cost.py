"""OME-1686 — the successful attempt's direct cost and token usage in ``_aigw``.

FEATURE: cost of intelligence (spec ``docs/spec/2026-10-20-OME-1686-succeeded-attempt-cost.md``).
STORY: as a leaderboard reader I see the price of a model's answer, not the price of the
gateway's retries, so a call that needed a retry still has a price.

INVARIANT: ``request_economics.succeeded_attempt_direct_cost`` and
``usage_accounting.succeeded_attempt_usage`` are the ``direct_cost`` and ``usage`` of the SAME
successful attempt, taken from ALL observed records — never from the rendered (truncated)
attempts — or both ``null`` when no attempt succeeded. The actual-spend fields
(``direct_cost_status``, ``known_direct_cost_subtotals``) keep their own meaning and are asserted
unchanged here.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aigateway.plugins.taxonomy import (
    DirectCost,
    InputTokenUsage,
    OutputTokenUsage,
    ProviderAttemptRecord,
    ProviderExtension,
    ProviderExtensionFact,
    TokenUsage,
)
from aigateway.plugins.taxonomy.render import (
    MAX_METADATA_BYTES,
    MAX_RENDERED_ATTEMPTS,
    render_aigw_metadata,
)

_KEY = "succeeded_attempt_direct_cost"
_USAGE_KEY = "succeeded_attempt_usage"
_CALL_ID = "call_" + "a" * 32
_UNIT = "openrouter_credits"
_SOURCE = "openrouter.usage.cost"


def _reported(amount: str) -> DirectCost:
    return DirectCost.reported(amount=amount, unit=_UNIT, source=_SOURCE)


def _record(sequence: int, **overrides: Any) -> ProviderAttemptRecord:
    values: dict[str, Any] = {
        "attempt_id": f"attempt_{sequence:032x}",
        "sequence": sequence,
        "dispatch_index": sequence,
        "attempt_index": 1,
        "provider": "openrouter",
        "transport": "litellm_async_http",
        "outcome": "succeeded",
        "http_status": 200,
    }
    values.update(overrides)
    return ProviderAttemptRecord(**values)


def _tokens(total_in: int, total_out: int) -> TokenUsage:
    return TokenUsage(
        status="complete",
        source="provider_raw_response",
        input=InputTokenUsage(total=total_in, uncached=total_in),
        output=OutputTokenUsage(total=total_out),
    )


def _failed(sequence: int, status: int, **overrides: Any) -> ProviderAttemptRecord:
    return _record(
        sequence,
        outcome="provider_error",
        http_status=status,
        failure_code="provider_status_error",
        **overrides,
    )


class _Collector:
    def __init__(self, *records: ProviderAttemptRecord, status: str = "complete") -> None:
        self._records = records
        self._status = status

    def records(self) -> tuple[ProviderAttemptRecord, ...]:
        return self._records

    def status(self) -> str:
        return self._status


def _render(collector: Any = None, **kwargs: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "collector": collector,
        "supported": True,
        "cache_status": "miss",
        "gateway_call_id": _CALL_ID,
    }
    params.update(kwargs)
    return render_aigw_metadata(**params)


def _validator() -> Draft202012Validator:
    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


def _cost_json(amount: str) -> dict[str, Any]:
    return {"status": "reported", "amount": amount, "unit": _UNIT, "source": _SOURCE}


class TestSuccessfulAttemptCost:
    def test_a_single_success_reports_its_own_direct_cost(self) -> None:
        economics = _render(_Collector(_record(1, direct_cost=_reported("0.001"))))[
            "request_economics"
        ]
        assert economics[_KEY] == _cost_json("0.001")
        assert economics["direct_cost_status"] == "complete"

    def test_a_503_then_200_reports_only_the_success_and_keeps_the_spend_partial(self) -> None:
        # WHY: the retry trap. The failed 503 has no cost evidence, so the ACTUAL spend stays
        # partial — but the price of the answer is the successful attempt's cost.
        economics = _render(
            _Collector(_failed(1, 503), _record(2, direct_cost=_reported("0.00042")))
        )["request_economics"]
        assert economics[_KEY] == _cost_json("0.00042")
        assert economics["direct_cost_status"] == "partial"
        assert economics["known_direct_cost_subtotals"] == [
            {"amount": "0.00042", "unit": _UNIT, "source": _SOURCE}
        ]

    def test_a_proven_zero_429_then_200_reports_the_success_and_stays_complete(self) -> None:
        zero = DirectCost.provider_guaranteed_zero(unit=_UNIT, source="openrouter.zci")
        economics = _render(
            _Collector(_failed(1, 429, direct_cost=zero), _record(2, direct_cost=_reported("0.02")))
        )["request_economics"]
        assert economics[_KEY] == _cost_json("0.02")
        assert economics["direct_cost_status"] == "complete"

    def test_an_unproven_429_then_200_reports_the_success(self) -> None:
        economics = _render(_Collector(_failed(1, 429), _record(2, direct_cost=_reported("0.02"))))[
            "request_economics"
        ]
        assert economics[_KEY] == _cost_json("0.02")
        assert economics["direct_cost_status"] == "partial"

    def test_a_success_without_cost_evidence_is_an_unknown_price_not_null(self) -> None:
        economics = _render(_Collector(_failed(1, 503), _record(2)))["request_economics"]
        assert economics[_KEY] == {
            "status": "unavailable",
            "amount": None,
            "unit": None,
            "source": None,
        }

    def test_two_successes_select_the_highest_sequence(self) -> None:
        # INVARIANT (spec D1): deterministic even if a future path keeps two successes.
        economics = _render(
            _Collector(
                _record(1, direct_cost=_reported("0.1")),
                _record(2, direct_cost=_reported("0.2")),
            )
        )["request_economics"]
        assert economics[_KEY] == _cost_json("0.2")

    def test_the_success_is_found_beyond_the_rendered_attempt_bound(self) -> None:
        records = [_failed(index, 503) for index in range(1, MAX_RENDERED_ATTEMPTS + 1)]
        records.append(_record(MAX_RENDERED_ATTEMPTS + 1, direct_cost=_reported("0.5")))
        metadata = _render(_Collector(*records))
        assert metadata["usage_accounting"]["rendered_attempts"] == MAX_RENDERED_ATTEMPTS
        assert metadata["usage_accounting"]["omitted_attempts"] == 1
        assert all(
            attempt["outcome"] != "succeeded"
            for attempt in metadata["usage_accounting"]["attempts"]
        )
        assert metadata["request_economics"][_KEY] == _cost_json("0.5")

    def test_size_degradation_keeps_the_key(self) -> None:
        fact = ProviderExtensionFact(
            name="n" * 64, kind="enum", value="v" * 64, unit=None, source="s" * 128
        )
        extension = ProviderExtension(namespace="x", facts=(fact,) * 8)
        requested_model = "m" * 512
        records = [
            _failed(
                index,
                503,
                requested_model=requested_model,
                response_model="r" * 512,
                provider_extensions=(extension,),
            )
            for index in range(1, MAX_RENDERED_ATTEMPTS)
        ]
        records.append(
            _record(
                MAX_RENDERED_ATTEMPTS,
                requested_model=requested_model,
                response_model="r" * 512,
                direct_cost=_reported("0.7"),
            )
        )
        metadata = _render(_Collector(*records))
        accounting = metadata["usage_accounting"]
        assert accounting["omitted_attempts"] > 0, "the fixture must force degradation"
        size = len(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode())
        assert size <= MAX_METADATA_BYTES
        assert metadata["request_economics"]["direct_cost_status"] == "partial"
        assert metadata["request_economics"][_KEY] == _cost_json("0.7")


class TestNoSuccessfulAttempt:
    def test_only_failed_attempts_give_null(self) -> None:
        economics = _render(_Collector(_failed(1, 503), _failed(2, 502)))["request_economics"]
        assert economics[_KEY] is None

    def test_a_cache_hit_gives_null(self) -> None:
        economics = _render(cache_status="hit")["request_economics"]
        assert economics[_KEY] is None

    def test_a_cache_hit_gives_null_even_when_records_exist(self) -> None:
        # WHY: a hit performs no dispatch; the key follows `_direct_cost_status`, which is
        # `not_applicable` for every hit.
        economics = _render(
            _Collector(_record(1, direct_cost=_reported("0.1"))), cache_status="hit"
        )["request_economics"]
        assert economics[_KEY] is None
        assert economics["direct_cost_status"] == "not_applicable"

    def test_no_collector_gives_null(self) -> None:
        assert _render(None)["request_economics"][_KEY] is None

    def test_an_unsupported_provider_gives_null(self) -> None:
        assert _render(None, supported=False)["request_economics"][_KEY] is None


class TestSchema:
    @pytest.mark.parametrize(
        "collector",
        [
            None,
            _Collector(_record(1, direct_cost=_reported("0.001"))),
            _Collector(_failed(1, 503), _record(2, direct_cost=_reported("0.00042"))),
            _Collector(_failed(1, 503), _record(2)),
            _Collector(_failed(1, 503)),
        ],
        ids=["no-collector", "success", "retry", "unknown-success", "failure"],
    )
    def test_every_rendered_shape_is_schema_valid(self, collector: Any) -> None:
        errors = list(_validator().iter_errors(_render(collector)))
        assert not errors, errors

    def test_the_key_is_required(self) -> None:
        metadata = _render(_Collector(_record(1, direct_cost=_reported("0.001"))))
        del metadata["request_economics"][_KEY]
        assert list(_validator().iter_errors(metadata))

    @pytest.mark.parametrize(
        "value",
        [
            {"status": "reported", "amount": 0.001, "unit": _UNIT, "source": _SOURCE},
            {**_cost_json("0.001"), "extra": True},
            {"status": "reported", "amount": None, "unit": None, "source": None},
            "0.001",
        ],
        ids=["number-amount", "extra-property", "reported-without-amount", "bare-string"],
    )
    def test_a_wrong_shape_is_rejected(self, value: Any) -> None:
        metadata = _render(_Collector(_record(1, direct_cost=_reported("0.001"))))
        metadata["request_economics"][_KEY] = value
        assert list(_validator().iter_errors(metadata))


class TestSuccessfulAttemptUsage:
    def test_a_single_success_reports_its_own_usage(self) -> None:
        metadata = _render(_Collector(_record(1, usage=_tokens(10, 5))))
        accounting = metadata["usage_accounting"]
        assert accounting[_USAGE_KEY] == accounting["attempts"][0]["usage"]
        assert accounting[_USAGE_KEY]["input"]["total"] == 10

    def test_a_retry_reports_only_the_successful_attempts_tokens(self) -> None:
        # WHY: a failed attempt may have consumed tokens; the cost of intelligence ignores them.
        metadata = _render(
            _Collector(
                _failed(1, 503, usage=_tokens(10, 0)),
                _record(2, usage=_tokens(12, 7), direct_cost=_reported("0.00042")),
            )
        )
        usage = metadata["usage_accounting"][_USAGE_KEY]
        assert usage == _tokens(12, 7).as_json()
        assert metadata["request_economics"][_KEY] == _cost_json("0.00042")

    def test_usage_and_cost_come_from_the_same_record(self) -> None:
        metadata = _render(
            _Collector(
                _record(1, usage=_tokens(1, 1), direct_cost=_reported("0.1")),
                _record(2, usage=_tokens(2, 2), direct_cost=_reported("0.2")),
            )
        )
        assert metadata["usage_accounting"][_USAGE_KEY] == _tokens(2, 2).as_json()
        assert metadata["request_economics"][_KEY] == _cost_json("0.2")

    def test_a_success_without_usage_evidence_reports_unavailable_usage_not_null(self) -> None:
        usage = _render(_Collector(_record(1)))["usage_accounting"][_USAGE_KEY]
        assert usage is not None
        assert usage["status"] == "unavailable"

    def test_usage_is_found_beyond_the_rendered_attempt_bound(self) -> None:
        records = [_failed(index, 503) for index in range(1, MAX_RENDERED_ATTEMPTS + 1)]
        records.append(_record(MAX_RENDERED_ATTEMPTS + 1, usage=_tokens(30, 3)))
        accounting = _render(_Collector(*records))["usage_accounting"]
        assert accounting["omitted_attempts"] == 1
        assert accounting[_USAGE_KEY] == _tokens(30, 3).as_json()

    def test_size_degradation_keeps_the_usage_key(self) -> None:
        fact = ProviderExtensionFact(
            name="n" * 64, kind="enum", value="v" * 64, unit=None, source="s" * 128
        )
        extension = ProviderExtension(namespace="x", facts=(fact,) * 8)
        records = [
            _failed(
                index,
                503,
                requested_model="m" * 512,
                response_model="r" * 512,
                provider_extensions=(extension,),
            )
            for index in range(1, MAX_RENDERED_ATTEMPTS)
        ]
        records.append(
            _record(
                MAX_RENDERED_ATTEMPTS,
                requested_model="m" * 512,
                response_model="r" * 512,
                usage=_tokens(40, 4),
                direct_cost=_reported("0.7"),
            )
        )
        metadata = _render(_Collector(*records))
        assert metadata["usage_accounting"]["omitted_attempts"] > 0, "must force degradation"
        assert metadata["usage_accounting"][_USAGE_KEY] == _tokens(40, 4).as_json()
        assert metadata["request_economics"][_KEY] == _cost_json("0.7")

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"collector": _Collector(_failed(1, 503), _failed(2, 502))},
            {"collector": _Collector(_record(1, usage=_tokens(1, 1))), "cache_status": "hit"},
            {"collector": None},
            {"collector": None, "supported": False},
        ],
        ids=["only-failures", "cache-hit", "no-collector", "unsupported"],
    )
    def test_usage_is_null_exactly_when_cost_is_null(self, kwargs: dict[str, Any]) -> None:
        metadata = _render(**kwargs)
        assert metadata["usage_accounting"][_USAGE_KEY] is None
        assert metadata["request_economics"][_KEY] is None

    def test_the_usage_key_is_required_by_the_schema(self) -> None:
        metadata = _render(_Collector(_record(1, usage=_tokens(1, 1))))
        assert not list(_validator().iter_errors(metadata))
        del metadata["usage_accounting"][_USAGE_KEY]
        assert list(_validator().iter_errors(metadata))

    @pytest.mark.parametrize(
        "value",
        [{**_tokens(1, 1).as_json(), "extra": True}, {"total": 3}, 3],
        ids=["extra-property", "not-usage-shape", "bare-number"],
    )
    def test_a_wrong_usage_shape_is_rejected(self, value: Any) -> None:
        metadata = _render(_Collector(_record(1, usage=_tokens(1, 1))))
        metadata["usage_accounting"][_USAGE_KEY] = value
        assert list(_validator().iter_errors(metadata))
