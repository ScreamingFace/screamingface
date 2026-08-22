"""OME-791 (B1) — does ``KNOWN_ROUTER_BACKENDS`` still match the live router vocabulary?

Opt-in only: set ``AIGW_LIVE=1``. This lives under ``tests/live/`` so it is structurally outside
the unit suite — a drift check that silently became ordinary CI network traffic would be both
flaky and a quiet dependency on Hugging Face's uptime.

WHAT THE ENDPOINT CAN AND CANNOT TELL US. ``MODELS_URL`` is the chat-completions MODEL CATALOG.
Every slug it reports is POSITIVE evidence that a provider is currently attached to a returned
chat model. Its silence is NOT evidence of removal: a partner that serves only image, video or
ASR models never appears here at all, and neither does one that is simply absent from today's
catalog page. So the two directions are not symmetric, and neither is what the check does with
them:

  * ``observed - allowlist`` — a slug the router attaches to chat models that we do not admit.
    This is REVIEW-REQUIRED drift. Cost today is only a lost optimisation (requests pinned to it
    dispatch normally, uncached), and it must stay that way: a new slug may never become
    cacheable automatically, because admitting one without review is how a routing POLICY gets
    treated as a fixed backend.
  * ``allowlist - observed`` — CATALOG COVERAGE, not proof a backend is gone. Only the entries
    that are NOT in ``_EXPECTED_CATALOG_OMISSIONS`` are worth a human's attention, and those
    fail the test so a release does not sail past them.

WHY THE STALE DIRECTION IS THE ONE THAT FAILS HARD: rows keyed under an allowlisted suffix never
expire, so a suffix the router has genuinely retired would keep being replayed for a backend that
no longer serves the model. A new-and-unadmitted slug cannot do that; it has no rows.

AIDEV-NOTE: the router does NOT publish routing policies (``:fastest``/``:cheapest``/
``:preferred``) in this metadata — they are a request-time selection rule, not catalog entries.
So a policy will never appear here, and its absence is not evidence the allowlist is clean. The
unit-level guard for that hazard is
``test_huggingface_provider_allowlist.py::test_the_allowlist_is_exactly_the_independently_transcribed_partner_table``,
which is where a bad MEMBER is caught. This test only watches the live vocabulary move.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from aigateway.plugins.huggingface_provider.discovery import MODELS_URL
from aigateway.plugins.huggingface_provider.settings import KNOWN_ROUTER_BACKENDS

# Allowlisted partners that are legitimately ABSENT from the chat-completions catalog, and are
# therefore expected noise rather than drift. Baseline observed 2026-08-22 (14 live slugs).
#
# WHY each is here: ``fal-ai``, ``replicate`` and ``wavespeed`` carry no ``conversational`` task
# in ``huggingface_hub``'s provider table at all — they are image/video/ASR backends, so a
# chat-model catalog structurally cannot list them. ``hf-inference`` does serve conversational
# models but is not attached to any model on the catalog page today.
#
# INVARIANT: this set only SUPPRESSES noise. It is subtracted, never compared for equality — an
# entry reappearing in the catalog is good news and must not fail the test. Removing a name from
# this set makes the check stricter, which is always safe; adding one needs the reason recorded
# above, because it silences a real signal.
_EXPECTED_CATALOG_OMISSIONS = frozenset({"fal-ai", "hf-inference", "replicate", "wavespeed"})


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
    not_in_catalog = sorted(KNOWN_ROUTER_BACKENDS - observed)
    unexpected_omissions = set(not_in_catalog) - _EXPECTED_CATALOG_OMISSIONS

    # Both directions are always reported, whatever the verdict, so a hand-run of this test is a
    # complete picture rather than only the half that happened to trip.
    print(f"\nlive provider slugs observed  : {len(observed)}")
    print(f"allowlisted                   : {len(KNOWN_ROUTER_BACKENDS)}")
    print(f"NEW (live, not allowlisted)   : {newly_observed or 'none'}")
    print(f"NOT IN CATALOG (allowlisted)  : {not_in_catalog or 'none'}")
    print(f"  └ expected/benign            : {sorted(_EXPECTED_CATALOG_OMISSIONS) or 'none'}")
    print(f"  └ UNEXPECTED                 : {sorted(unexpected_omissions) or 'none'}")

    # The failing direction. Never expires means never self-corrects, so an allowlisted partner
    # dropping out of the catalog is a release-blocking question rather than a print.
    assert not unexpected_omissions, (
        "allowlisted providers disappeared from the live model catalog; review before release: "
        f"{sorted(unexpected_omissions)}"
    )

    # Reported, not enforced: a new partner costs only a missed optimisation until it is
    # reviewed into the static table. Failing here would make an upstream launch break our CI.
    if newly_observed:
        pytest.skip(
            f"allowlist drift — add after review: {newly_observed}. "
            "Requests pinned to these dispatch normally but are not cached."
        )
