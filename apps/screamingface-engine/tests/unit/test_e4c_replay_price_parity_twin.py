"""A live call and its replay give the budget the same numbers, on the gateway's real blocks (E4c).

FEATURE (E4c ans:Q21b, budget BU-27, OME-1291; review of PR #1733): one price source live and on
replay. ``test_e4c_replay_price_parity.py`` checks this rule against a hand copy of the gateway's
replay rule. This test reads the blocks the gateway itself renders:
``apps/aigateway/tests/fixtures/replay_reference_twins/twins.json``, produced and guarded by
``apps/aigateway/tests/unit/test_replay_reference_twin_fixture.py``. It is read by repository
path, never imported: apps never import each other. So a change to the gateway's replay rule
reaches this check through the regenerated fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.world.accounting import signal_accounting_from_aigw
from screamingface_engine.world.cache_readback import CacheOutcome, CacheStatus

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE = _REPO_ROOT / "apps/aigateway/tests/fixtures/replay_reference_twins/twins.json"
_TWINS: dict[str, dict[str, Any]] = json.loads(_FIXTURE.read_text(encoding="utf-8"))["twins"]


def _cache(status: CacheStatus) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=None, retried=False)


def _live_cache(live: Any) -> CacheOutcome:
    return _cache(live["usage_accounting"]["cache"]["status"])


@pytest.mark.parametrize("name", list(_TWINS))
def test_the_replay_block_gives_the_live_numbers(name: str) -> None:
    twin = _TWINS[name]
    live = signal_accounting_from_aigw(twin["live"], _live_cache(twin["live"]))
    replay = signal_accounting_from_aigw(twin["replay"], _cache("hit"))

    assert replay == live


def test_the_fixture_holds_priced_calls() -> None:
    # Guards the parity test above from passing on readings that are all empty.
    twin = _TWINS["retry"]
    numbers = signal_accounting_from_aigw(twin["replay"], _cache("hit"))

    assert numbers.tokens_in == 20
    assert numbers.latency_ms == 200


def test_the_fixture_holds_a_usd_price() -> None:
    numbers = signal_accounting_from_aigw(_TWINS["usd-unit"]["replay"], _cache("hit"))

    assert numbers.cost_usd == 0.25
