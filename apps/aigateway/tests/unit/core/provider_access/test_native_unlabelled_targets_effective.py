"""A native connection with no label targets the migrated pair's effective row (OME-1209, E1b).

# FEATURE: Stage E spec R6 — "no label = the pair's main connection", as the Profile API's default
# name did: on a `migrated` pair with an effective row, an unlabelled OAuth flow or API-key create
# replaces that row, working or not, and keeps its label when it is a real one. Extra connections
# beside the main one need an explicit label of their own.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from connection_backed_admin_probes import blob_at_connection_address, connection, marker
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of, callback, use_tokens
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.identity import AccountIdentity
from tests.unit.seed_state import SeedState

KEY = "sk-ant-api03-e1b-unlabelled-key-1111"


class _ValidKeys:
    async def validate(self, _plugin: Any, _provider: str, _key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


@pytest.fixture
def migrated(
    authenticated_client, credential_blobs, monkeypatch: pytest.MonkeyPatch
) -> ConnectionBackedHarness:
    harness = ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)
    authenticated_client.app.state.api_key_validation_service = _ValidKeys()
    # WHY: the anthropic plugin requires a label; the unlabelled flow is what codex, gemini and
    # antigravity send, so the requirement is lifted for these cases.
    monkeypatch.setattr(type(ANTHROPIC), "requires_oauth_connection_label", lambda _self: False)
    return harness


def _effective(harness: ConnectionBackedHarness) -> str | None:
    effective = marker(harness).effective_connection_id
    return None if effective is None else str(effective)


def _unlabelled_oauth(harness: ConnectionBackedHarness, token: str = "new-tok") -> str:
    use_tokens(harness, token)
    started = harness.client.post("/v1/oauth/connections", json={"provider": PROVIDER})
    assert started.status_code == 201, started.text
    completed = callback(harness, started.json()["state"])
    assert completed.status_code == 200, completed.text
    return str(started.json()["connection_id"])


def test_an_unlabelled_flow_replaces_a_working_effective_row_and_keeps_its_label(
    migrated: ConnectionBackedHarness,
) -> None:
    h = migrated
    h.seed_credential(state=SeedState.AUTHENTICATED)
    old = h.migrated["default"]

    new = _unlabelled_oauth(h)

    assert _effective(h) == new
    assert connection(h, old).status == "revoked"
    assert (connection(h, new).status, connection(h, new).label) == ("active", "default")
    assert access_token_of(blob_at_connection_address(h, new)) == "new-tok"


def test_an_unlabelled_re_login_of_the_same_identity_refreshes_the_main_connection(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: re-signing into the main connection's own provider account must land fresh tokens on
    # the pair — not answer 200 and discard them as a duplicate.
    h = migrated
    h.seed_credential(state=SeedState.AUTHENTICATED)
    old = h.migrated["default"]
    row = connection(h, old)
    row.identity_sub = "user-1"
    h.call(row.save, update_fields=["identity_sub"])

    async def same_identity(*_args: Any, **_kwargs: Any) -> AccountIdentity:
        return AccountIdentity(sub="user-1")

    monkeypatch.setattr(type(ANTHROPIC), "extract_identity", same_identity)

    new = _unlabelled_oauth(h)

    assert _effective(h) == new
    assert (connection(h, new).identity_sub, connection(h, new).label) == ("user-1", "default")
    assert access_token_of(blob_at_connection_address(h, new)) == "new-tok"


def test_an_unlabelled_flow_does_not_inherit_a_placeholder_label(
    migrated: ConnectionBackedHarness,
) -> None:
    # WHY: an errored OAuth row's label is an `error:<id>` placeholder, not a name to keep.
    h = migrated
    h.seed_credential(state=SeedState.ERROR)
    old = h.migrated["default"]
    assert connection(h, old).label.startswith("error:")

    new = _unlabelled_oauth(h)

    assert _effective(h) == new
    assert not connection(h, new).label.startswith(("error:", "revoked:"))


def test_an_unlabelled_key_replaces_a_working_effective_row_and_keeps_its_label(
    migrated: ConnectionBackedHarness,
) -> None:
    h = migrated
    h.seed_credential(state=SeedState.AUTHENTICATED)
    old = h.migrated["default"]

    created = h.client.post(
        "/v1/oauth/connections/api-key", json={"provider": PROVIDER, "api_key": KEY}
    )

    assert created.status_code == 201, created.text
    new = str(created.json()["id"])
    assert _effective(h) == new
    assert connection(h, old).status == "revoked"
    assert (connection(h, new).label, connection(h, new).auth_type) == ("default", "api_key")
    assert json.loads(blob_at_connection_address(h, new) or "{}")["api_key"] == KEY
