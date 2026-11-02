"""G0 writer floor — error marks check the pair generation they observed (OME-1497, part 3).

# FEATURE: OME-1138 D18, G0 (contract §5.3, owner decisions 2026-10-06 and 2026-10-13) — "OAuth
# failure and error marks only check the observed generation where a lockable row exists and
# never advance it". A Connection on a `none` or unmarked pair is marked `error` only while the
# pair still sits at the generation the request observed before its provider call.
# STORY: as an operator who just replaced a rejected API key, I am not told to reconnect because a
# request that was still using the old key failed a moment later.
# INVARIANT: an API-key Connection is re-keyed IN PLACE (same row, still `active`), so `id` and
# `status=active` cannot tell the old key's failure from the new key's; the generation can.
# INVARIANT: a lost check marks nothing and changes no answer; a check never moves the generation.
# WHY no `migrated` pair here: it keeps its own fences (§5.3). The Profile-mark pin retired with
# the Profile dispatch target (OME-1209 E4a): a key replaced during dispatch is pinned on its
# Connection below. The legacy OAuth-callback pin retired with that callback (OME-1209 E3b).
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import marker
from provider_access_harness import ANTHROPIC, PROVIDER, RealAppHarness

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.errors import AuthError, ReauthRequiredError
from aigateway.core.provider_access import (
    CredentialTarget,
    PairAuthorityStore,
    Selector,
    TargetReauthRequired,
)
from aigateway.core.provider_access.writer_floor import claim_pair

DEFAULT = Selector.from_header(None)
REVOKED = {"code": "auth_required", "message": "revoked"}
NEW_KEY = "sk-ant-api03-error-mark-floor-2222"


class _ValidKeys:
    async def validate(self, _plugin: Any, _provider: str, _key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


@pytest.fixture
def harness(authenticated_client, credential_blobs, monkeypatch) -> RealAppHarness:
    authenticated_client.app.state.api_key_validation_service = _ValidKeys()
    return RealAppHarness(authenticated_client, credential_blobs, monkeypatch)


async def _claim_current(account_id: str) -> None:
    """Another ownership writer wins the pair (what a key PUT, create or delete does)."""
    await claim_pair(await PairAuthorityStore().read(account_id, PROVIDER))


def _claim(harness: RealAppHarness) -> None:
    harness.call(_claim_current, harness.account_id)


def _resolve(harness: RealAppHarness) -> CredentialTarget:
    return harness.call(
        harness.access.resolve, harness.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC
    )


def _record(harness: RealAppHarness, target: CredentialTarget) -> Any:
    return harness.call(
        harness.access.record_dispatch_failure, target, 401, REVOKED, plugin=ANTHROPIC
    )


class _LosesThePairThenFails:
    """A provider call whose window sees another owner win the pair, then rejects the credential."""

    def __init__(self, account_id: str, exc: Exception) -> None:
        self._account_id = account_id
        self._exc = exc

    async def _lose(self) -> None:
        await _claim_current(self._account_id)
        raise self._exc

    async def get_authorization_header(self) -> dict[str, str]:
        await self._lose()
        return {}

    async def refresh_credentials(self) -> None:
        await self._lose()

    async def get_token_with_expiry(self) -> tuple[str, int, bool]:
        await self._lose()
        return "", 0, False


def _fail_in_the_window(harness: RealAppHarness, credential_name: str, exc: Exception) -> None:
    credential_strategy_cache(harness.client.app).get_or_create(
        provider=PROVIDER,
        auth_type="oauth",
        credential_name=credential_name,
        build=lambda: _LosesThePairThenFails(harness.account_id, exc),
    )


# --- dispatch failure (record_dispatch_failure) ---------------------------------------------


def test_a_dispatch_failure_after_an_ownership_change_marks_nothing(harness) -> None:
    connection_id = harness.seed_connection(label="work")
    _claim(harness)  # a marked `none` pair
    target = _resolve(harness)
    _claim(harness)

    assert _record(harness, target) is None
    assert harness.connection_status(connection_id) == "active"


def test_a_dispatch_failure_after_the_first_marker_appeared_marks_nothing(harness) -> None:
    # WHY: resolve saw an unmarked pair; the first ownership write since then created the marker.
    connection_id = harness.seed_connection(label="work")
    target = _resolve(harness)
    _claim(harness)

    assert _record(harness, target) is None
    assert harness.connection_status(connection_id) == "active"


def test_a_native_key_replacement_during_dispatch_keeps_the_new_key_usable(harness) -> None:
    # STORY: the old key's 401 arrives after the operator replaced it in place.
    created = harness.client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": "work", "api_key": "sk-ant-api03-old-key-1111"},
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    target = _resolve(harness)
    replaced = harness.client.put(
        f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": NEW_KEY}
    )
    assert replaced.status_code == 200, replaced.text

    _record(harness, target)

    assert harness.connection_status(connection_id) == "active"


def test_a_dispatch_failure_with_no_interference_still_marks_and_never_advances(harness) -> None:
    # Over-correction guard: the check only refuses a moved pair.
    connection_id = harness.seed_connection(label="work")
    _claim(harness)
    before = marker(harness).generation
    target = _resolve(harness)

    _record(harness, target)

    assert harness.connection_status(connection_id) == "error"
    assert marker(harness).generation == before


def test_a_dispatch_failure_on_an_unmarked_pair_still_marks_and_mints_no_marker(harness) -> None:
    connection_id = harness.seed_connection(label="work")
    target = _resolve(harness)

    _record(harness, target)

    assert harness.connection_status(connection_id) == "error"
    assert marker(harness).generation == 0


# --- authorize (a rejected credential) ------------------------------------------------------


def test_a_credential_rejected_after_an_ownership_change_still_refuses_but_marks_nothing(
    harness,
) -> None:
    connection_id = harness.seed_connection(label="work")
    _claim(harness)
    target = _resolve(harness)
    _fail_in_the_window(harness, str(target.credential_name), AuthError("refresh rejected"))

    with pytest.raises(TargetReauthRequired):
        harness.call(harness.access.authorize, target, plugin=ANTHROPIC, provider=PROVIDER)

    assert harness.connection_status(connection_id) == "active"


# --- token endpoint and manual refresh ------------------------------------------------------


def test_a_token_refresh_rejected_after_an_ownership_change_answers_401_and_marks_nothing(
    harness,
) -> None:
    connection_id = harness.seed_connection(label="work")
    _claim(harness)
    target = _resolve(harness)
    _fail_in_the_window(harness, str(target.credential_name), ReauthRequiredError("revoked"))

    response = harness.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "auth_required"
    assert harness.connection_status(connection_id) == "active"


def test_a_token_refresh_rejected_with_no_interference_still_marks(harness) -> None:
    connection_id = harness.seed_connection(label="work")
    _claim(harness)
    target = _resolve(harness)
    credential_strategy_cache(harness.client.app).get_or_create(
        provider=PROVIDER,
        auth_type="oauth",
        credential_name=str(target.credential_name),
        build=lambda: _Rejects(ReauthRequiredError("revoked")),
    )

    response = harness.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert response.status_code == 401, response.text
    assert harness.connection_status(connection_id) == "error"


def test_a_manual_refresh_rejected_after_an_ownership_change_answers_401_and_marks_nothing(
    harness,
) -> None:
    connection_id = harness.seed_connection(label="work")
    _claim(harness)
    target = _resolve(harness)
    _fail_in_the_window(harness, str(target.credential_name), AuthError("refresh rejected"))

    response = harness.client.post(f"/v1/oauth/connections/{connection_id}/refresh")

    assert response.status_code == 401, response.text
    assert harness.connection_status(connection_id) == "active"


class _Rejects:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def get_token_with_expiry(self) -> tuple[str, int, bool]:
        raise self._exc
