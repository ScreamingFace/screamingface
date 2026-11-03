"""A labelled create replaces an `expired` effective row (OME-1138 close-out, L7a).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2 and §8.1 (owner,
# 2026-11-02) — Stage E (R6, OME-1209 E1b) named only `active` and `pending` usable; an `expired`
# effective row serves nothing, so a create under another label replaces it, as it replaces an
# `error` or `revoked` one. The Local Engine's create carries the label `screamingface`.
# INVARIANT: a `pending` effective row stays — R6, pinned by
# `test_native_oauth_replaces_unusable_effective.py::test_a_usable_effective_row_is_not_displaced`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from connection_backed_admin_probes import connection, marker
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import callback, use_tokens
from provider_access_harness import PROVIDER

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.models import OAuthConnection
from tests.unit.seed_state import SeedState

KEY = "sk-ant-api03-expired-effective-key-8642"
LABEL = "screamingface"


class _ValidKeys:
    async def validate(self, _plugin: Any, _provider: str, _key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


@pytest.fixture
def expired(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    """A migrated pair whose effective OAuth row is `expired`."""
    harness = ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)
    authenticated_client.app.state.api_key_validation_service = _ValidKeys()
    harness.seed_credential(state=SeedState.AUTHENTICATED)

    async def expire() -> None:
        await OAuthConnection.filter(id=UUID(harness.migrated["default"])).update(status="expired")

    harness.call(expire)
    return harness


def _effective(harness: ConnectionBackedHarness) -> str | None:
    effective = marker(harness).effective_connection_id
    return None if effective is None else str(effective)


def _assert_replaced(harness: ConnectionBackedHarness, new: str) -> None:
    old = harness.migrated["default"]
    assert _effective(harness) == new
    assert connection(harness, old).status == "revoked"
    assert (connection(harness, new).status, connection(harness, new).label) == ("active", LABEL)


def test_a_labelled_key_replaces_an_expired_effective_row(expired: ConnectionBackedHarness) -> None:
    created = expired.client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": LABEL, "api_key": KEY},
    )
    assert created.status_code == 201, created.text

    _assert_replaced(expired, str(created.json()["id"]))


def test_a_labelled_oauth_flow_replaces_an_expired_effective_row(
    expired: ConnectionBackedHarness,
) -> None:
    use_tokens(expired, "new-tok")
    started = expired.client.post(
        "/v1/oauth/connections", json={"provider": PROVIDER, "label": LABEL}
    )
    assert started.status_code == 201, started.text
    completed = callback(expired, started.json()["state"])
    assert completed.status_code == 200, completed.text

    _assert_replaced(expired, str(started.json()["connection_id"]))
