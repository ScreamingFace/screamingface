"""SC-E5 (registry errors), SC-E-size and the coded error mapping of `POST /v1/scores`.

FEATURE: OME-1307 (E14). D7 X-8: `{"detail": {"code", "message", ...}}`. D7 X-22: one status (422)
for "the url4 is too large".
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from scoreboard.core.registry import RegistryConflict, RegistryService, Url4TooLarge
from scoreboard.scores.models import ReportedResult, Score, System
from tests.unit.submissions._receipts import ANA, BRUNO, URL4_A, URL4_B, post_score

pytestmark = pytest.mark.asyncio


async def _assert_nothing_new() -> None:
    assert await ReportedResult.all().count() == 0
    assert await Score.all().count() == 0


async def test_registry_errors_map_to_http(clustered_cf_client: AsyncClient) -> None:
    await post_score(clustered_cf_client, user=BRUNO, url4_expression=URL4_A)
    baseline = (await Score.all().count(), await System.all().count())

    # WHY URL4_B: a known fingerprint always wins, also with `revision_of` (I-N2), so the unknown
    # system name is only reached with a NEW fingerprint.
    unknown = await post_score(
        clustered_cf_client, user=ANA, url4_expression=URL4_B, revision_of="unknown"
    )
    not_owner = await post_score(
        clustered_cf_client, user=ANA, url4_expression=URL4_B, revision_of="kevins-best"
    )
    taken = await post_score(clustered_cf_client, user=ANA, url4_expression=URL4_B)
    bad_name = await post_score(clustered_cf_client, user=ANA, spec_id="Bad/Name")
    bad_url4 = await post_score(clustered_cf_client, user=ANA, url4_expression="not a url4")

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "system_not_found"
    assert not_owner.status_code == 403
    assert not_owner.json()["detail"]["code"] == "not_system_owner"
    assert taken.status_code == 409
    assert taken.json()["detail"]["code"] == "system_name_taken"
    assert taken.json()["detail"]["suggestion"]
    assert bad_name.status_code == 422
    assert bad_name.json()["detail"]["code"] == "invalid_system_name"
    assert bad_name.json()["detail"]["rule"] == "slash"
    assert bad_name.json()["detail"]["message"]
    assert bad_url4.status_code == 422
    assert bad_url4.json()["detail"]["code"] == "invalid_url4"
    # SC-E5: a refused submit rolls the transaction back, so nothing is written.
    assert (await Score.all().count(), await System.all().count()) == baseline


async def test_registry_conflict_maps_to_409(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lost(self: RegistryService, *args: Any, **kwargs: Any) -> None:
        raise RegistryConflict("lost twice")

    monkeypatch.setattr(RegistryService, "resolve_for_submit", lost)

    response = await post_score(clustered_cf_client)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "registry_conflict"
    await _assert_nothing_new()


async def test_url4_over_cap_is_422_not_413(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The 32,001-char text stops at the existing `ScoreSubmission` cap: the standard 422.
    too_long = await post_score(clustered_cf_client, url4_expression="x" * 32_001)

    async def too_large(self: RegistryService, *args: Any, **kwargs: Any) -> None:
        raise Url4TooLarge(40_000, 32_000)

    monkeypatch.setattr(RegistryService, "resolve_for_submit", too_large)
    registry = await post_score(clustered_cf_client, user=ANA)

    assert too_long.status_code == 422
    assert registry.status_code == 422
    assert registry.json()["detail"]["code"] == "url4_too_large"
    await _assert_nothing_new()


async def test_untrusted_peer_and_missing_identity_are_refused_before_any_receipt_work(
    clustered_cf_client: AsyncClient, clustered_untrusted_client: AsyncClient
) -> None:
    no_identity = await post_score(clustered_cf_client, user=None, receipt="not-a-jws")
    untrusted = await post_score(clustered_untrusted_client, user=ANA, receipt="not-a-jws")

    assert no_identity.status_code == 401
    assert untrusted.status_code == 403
    await _assert_nothing_new()
