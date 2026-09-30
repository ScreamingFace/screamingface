"""``capture_outcome``: how a call was answered decides its capture row, for every combination.

FEATURE: OME-1307 (E14) - the chat route's stages return how the call was answered, and this pure
mapping is the one place that turns that into a capture outcome.
INVARIANT: the mapping is total. Every source x cache status x write status is a known outcome.
"""

from __future__ import annotations

import itertools
from typing import get_args

import pytest

from aigateway.core.cache_versions.ports import CAPTURE_OUTCOMES, CaptureOutcome
from aigateway.routes.chat_cache_stage import CacheStatus, WriteStatus
from aigateway.routes.chat_capture_stage import AnsweredBy, capture_outcome

_CACHE_STATUSES: list[CacheStatus | None] = [*get_args(CacheStatus), None]
_WRITE_STATUSES: list[WriteStatus | None] = [*get_args(WriteStatus), None]


def test_the_sources_are_the_four_the_route_can_answer_from() -> None:
    assert set(get_args(AnsweredBy)) == {"version", "global_cache", "provider", "provider_stream"}


@pytest.mark.parametrize(
    ("answered_by", "cache_status", "write_status"),
    list(itertools.product(get_args(AnsweredBy), _CACHE_STATUSES, _WRITE_STATUSES)),
)
def test_every_combination_maps_to_a_known_outcome(
    answered_by: AnsweredBy, cache_status: CacheStatus | None, write_status: WriteStatus | None
) -> None:
    outcome = capture_outcome(answered_by, cache_status=cache_status, write_status=write_status)

    assert outcome in CAPTURE_OUTCOMES


@pytest.mark.parametrize(
    ("answered_by", "cache_status", "write_status", "outcome"),
    [
        pytest.param("version", None, None, "version_hit", id="version-hit"),
        pytest.param("global_cache", "hit", None, "hit", id="global-hit"),
        pytest.param("provider_stream", "bypass", None, "bypass", id="stream"),
        pytest.param("provider", "miss", "stored", "stored", id="miss-stored"),
        pytest.param("provider", "miss", "race_lost", "unstored", id="miss-race-lost"),
        pytest.param("provider", "miss", "not_stored", "unstored", id="miss-not-stored"),
        pytest.param("provider", "bypass", None, "bypass", id="bypass"),
        pytest.param("provider", "miss", None, "unstored", id="miss-without-write"),
    ],
)
def test_the_table_the_route_relies_on(
    answered_by: AnsweredBy,
    cache_status: CacheStatus | None,
    write_status: WriteStatus | None,
    outcome: CaptureOutcome,
) -> None:
    assert (
        capture_outcome(answered_by, cache_status=cache_status, write_status=write_status)
        == outcome
    )
