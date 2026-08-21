"""OME-791 (B1) — does ``KNOWN_ROUTER_BACKENDS`` still match the live router vocabulary?

Opt-in only: set ``AIGW_LIVE=1``. This lives under ``tests/live/`` so it is structurally outside
the unit suite — a drift check that silently became ordinary CI network traffic would be both
flaky and a quiet dependency on Hugging Face's uptime.

WHAT DRIFT MEANS HERE, and why the two directions are NOT symmetric:

  * a provider live-but-MISSING from the allowlist is a LOST OPTIMISATION. Requests pinned to it
    dispatch normally and simply never cache. Safe, and the reason the allowlist may lag.
  * a provider allowlisted but GONE from the router is the direction that matters more: rows
    keyed under it never expire, so they would keep being replayed for a backend that no longer
    serves the model.

Neither is an outage, so this test REPORTS rather than fails hard on the first direction — the
allowlist is a deliberate, reviewed transcription of the partner table, not a live mirror.

AIDEV-NOTE: the router does NOT publish routing policies (``:fastest``/``:cheapest``/
``:preferred``) in this metadata — they are a request-time selection rule, not catalog entries.
So a policy will never appear here, and its absence is not evidence the allowlist is complete.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from aigateway.plugins.huggingface_provider.discovery import MODELS_URL
from aigateway.plugins.huggingface_provider.settings import KNOWN_ROUTER_BACKENDS


def _live_enabled() -> bool:
    return os.environ.get("AIGW_LIVE") == "1"


def _observed_provider_slugs(payload: dict[str, Any]) -> set[str]:
    """The union of every ``providers[].provider`` slug the router reports."""
    observed: set[str] = set()
    for row in payload.get("data") or []:
        if not isinstance(row, dict):
            continue
        for entry in row.get("providers") or []:
            if isinstance(entry, dict) and isinstance(entry.get("provider"), str):
                observed.add(entry["provider"])
    return observed


@pytest.mark.live
@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_the_static_allowlist_still_matches_the_live_router_vocabulary() -> None:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    response = httpx.get(MODELS_URL, headers=headers, timeout=30.0)
    response.raise_for_status()
    observed = _observed_provider_slugs(response.json())

    assert observed, "the router returned no provider entries — the metadata shape may have moved"

    newly_observed = sorted(observed - KNOWN_ROUTER_BACKENDS)
    no_longer_observed = sorted(KNOWN_ROUTER_BACKENDS - observed)

    print(f"\nlive provider slugs observed : {len(observed)}")
    print(f"allowlisted                  : {len(KNOWN_ROUTER_BACKENDS)}")
    print(f"NEW (live, not allowlisted)  : {newly_observed or 'none'}")
    print(f"STALE (allowlisted, not live): {no_longer_observed or 'none'}")

    # Reported, not enforced: a new partner costs only a missed optimisation until it is
    # reviewed into the static table. Failing here would make an upstream launch break our CI.
    if newly_observed:
        pytest.skip(
            f"allowlist drift — add after review: {newly_observed}. "
            "Requests pinned to these dispatch normally but are not cached."
        )
