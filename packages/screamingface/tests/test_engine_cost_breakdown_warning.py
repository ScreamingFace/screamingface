"""When the Engine reports a cost total with no per-class breakdown, say nothing.

FEATURE: per-run cost reporting (`OME-849`/`OME-861`). A provider may author ONE amount with no
split — OpenRouter does — so `url4.streaming`'s `CostBreakdown` now accepts
`Σ components <= total_usd` and the Engine publishes a total with every component at zero. The old
total-vs-parts warning therefore fired on EVERY priced run.

STORY: as a researcher reading my Report in a notebook, a successful priced run is quiet. A warning
means something is actually wrong with the numbers, so it has to stay rare enough to be worth
reading.

A separate module rather than an append to `test_engine_contract.py`: the repo's append-only gate
compares file status, so growing an existing test file reads as a modified prior test even when the
diff is purely additive.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import pytest

import screamingface as sf
from screamingface._engine.contract import display_event

_LOGGER = "screamingface._engine.contract"


def _cost_frame(cost: dict[str, str], *, pricing_version: str = "openrouter-credits-1usd") -> str:
    """One `ai.url4.cost.usage` frame carrying `cost` verbatim."""
    payload: dict[str, Any] = {
        "specversion": "1.0",
        "id": "event_1",
        "source": "/trace/run_1/node/root",
        "subject": "run_1",
        "time": "2026-07-25T16:00:00Z",
        "type": "ai.url4.cost.usage",
        "datacontenttype": "application/json",
        "sequence": "1",
        "sequencetype": "Integer",
        "data": {
            "scope": "subtree",
            "gen_ai.provider.name": "openrouter",
            "gen_ai.response.model": "openrouter/anthropic/claude-haiku-4.5",
            "pricing_version": pricing_version,
            "usage": {
                "gen_ai.usage.input_tokens": 651,
                "gen_ai.usage.output_tokens": 25,
                "gen_ai.usage.cache_read_tokens": 0,
                "gen_ai.usage.cache_creation_tokens": 0,
                "gen_ai.usage.reasoning_tokens": 0,
            },
            "cost": cost,
        },
    }
    return json.dumps(payload)


def _accept(frame: str, caplog: pytest.LogCaptureFixture) -> sf.events.Usage:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        event = display_event(json.loads(frame))
    assert isinstance(event, sf.events.Usage)
    return event


def test_a_total_with_no_breakdown_is_not_a_contradiction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The exact shape url4-cloud publishes for a priced OpenRouter run.

    INVARIANT: an ABSENT breakdown is silence, not disagreement. Warning here fired on every priced
    run and told the reader nothing they could act on.
    """
    event = _accept(
        _cost_frame(
            {
                "input_usd": "0",
                "output_usd": "0",
                "cache_read_usd": "0",
                "cache_creation_usd": "0",
                "reasoning_usd": "0",
                "total_usd": "0.007905",
            }
        ),
        caplog,
    )

    assert event.usage.cost_usd == Decimal("0.007905")
    assert caplog.text == ""


def test_a_bare_total_with_the_components_omitted_is_also_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Components default to zero when absent, so an omitted breakdown must behave as a zero one."""
    event = _accept(_cost_frame({"total_usd": "0.001"}), caplog)

    assert event.usage.cost_usd == Decimal("0.001")
    assert caplog.text == ""


def test_a_supplied_breakdown_that_disagrees_still_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """INVARIANT: the guard narrows the condition, it does not remove it.

    A producer that DID compute a breakdown and still disagrees with its own total is reporting
    something incoherent, and that stays worth a line in the log.
    """
    event = _accept(
        _cost_frame({"input_usd": "0.01", "output_usd": "0.02", "total_usd": "0.030001"}),
        caplog,
    )

    assert event.usage.cost_usd == Decimal("0.030001")
    assert "does not equal its parts" in caplog.text


def test_an_all_zero_cost_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    """The shape an unpriced run publishes — total and components all zero."""
    event = _accept(
        _cost_frame({"total_usd": "0"}, pricing_version="unpriced"),
        caplog,
    )

    assert event.usage.cost_usd is None
    assert caplog.text == ""


def test_an_unpriced_frame_still_nulls_the_derived_token_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression guard for the neighbouring behaviour this change must not disturb."""
    event = _accept(_cost_frame({"total_usd": "0"}, pricing_version="unpriced"), caplog)

    assert event.usage.cost_usd is None
    assert event.usage.cache_read_tokens is None
    assert event.usage.cache_creation_tokens is None
    assert event.usage.reasoning_tokens is None
    # Input/output counts are NOT nulled by unpriced — they are provider-reported either way.
    assert event.usage.input_tokens == 651
    assert event.usage.output_tokens == 25
