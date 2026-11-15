"""A malformed dimension of a captured call drops only that dimension of the replay reference.

FEATURE (E4c, OME-1291, review of PR #1733): the live engine reads cost, tokens and latency of
the priced attempt independently (``signal_accounting_from_aigw``: "every absent or malformed
piece is None for that field only"). A replay must give the engine the same numbers, so one
malformed dimension must not discard the others: before this, the whole ``cache.reference``
became ``None`` and a valid cost or token count was lost, and a budget Gate could take another
branch on replay.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.plugins.taxonomy.entry_metadata import cache_reference_from_captured_aigw
from tests.unit.test_frozen_copy_replay_reference import _live_miss, _record


def _captured(**attempt: Any) -> dict[str, Any]:
    aigw = _live_miss(_record(1))
    aigw["usage_accounting"]["attempts"][0].update(attempt)
    return aigw


def test_a_malformed_usage_keeps_the_cost_and_the_latency() -> None:
    reference = cache_reference_from_captured_aigw(_captured(usage={"status": "bogus"}))

    assert reference is not None
    assert reference.usage.status == "unavailable"
    assert reference.usage.input.total is None
    assert (reference.direct_cost.status, reference.direct_cost.amount) == ("reported", "0.001")
    assert reference.provider_latency_ms == 100


@pytest.mark.parametrize("cost", [{"status": "bogus"}, "garbage", {"status": "reported"}])
def test_a_malformed_cost_keeps_the_tokens_and_the_latency(cost: Any) -> None:
    reference = cache_reference_from_captured_aigw(_captured(direct_cost=cost))

    assert reference is not None
    assert reference.direct_cost.status == "unavailable"
    assert (reference.usage.input.total, reference.usage.output.total) == (10, 1)
    assert reference.provider_latency_ms == 100


@pytest.mark.parametrize("latency", [-5, "fast", 1.5, True])
def test_a_malformed_latency_keeps_the_cost_and_the_tokens(latency: Any) -> None:
    reference = cache_reference_from_captured_aigw(_captured(latency_ms=latency))

    assert reference is not None
    assert reference.provider_latency_ms is None
    assert reference.usage.input.total == 10
    assert reference.direct_cost.amount == "0.001"


def test_a_malformed_response_model_keeps_the_price() -> None:
    reference = cache_reference_from_captured_aigw(_captured(response_model=7))

    assert reference is not None
    assert reference.response_model is None
    assert reference.direct_cost.amount == "0.001"


def test_a_captured_hit_with_one_malformed_dimension_keeps_the_others() -> None:
    reference = cache_reference_from_captured_aigw(_captured())
    assert reference is not None
    payload = reference.as_json()
    payload["usage"] = "garbage"
    hit = {"usage_accounting": {"cache": {"status": "hit", "reference": payload}}}

    replayed = cache_reference_from_captured_aigw(hit)

    assert replayed is not None
    assert replayed.usage.status == "unavailable"
    assert replayed.direct_cost.amount == "0.001"
