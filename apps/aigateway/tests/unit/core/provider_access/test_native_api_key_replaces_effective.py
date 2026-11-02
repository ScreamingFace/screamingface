"""A native API-key connection replaces a migrated pair's effective row (OME-1209, E1b).

# FEATURE: Stage E spec R6 — E3 names `POST /v1/oauth/connections/api-key` as the successor of the
# Profile key write, which always set the pair's credential. On a `migrated` pair the new key
# becomes effective when the effective row is unusable, or when it asks for that row's own label;
# with any other label a working effective row stays — the same rule as the native OAuth flow.
# INVARIANT: fenced by the marker generation captured before the key validation; a change in
# between loses with 409 `connection_conflict` and creates nothing.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from connection_backed_admin_probes import (
    blob_at_connection_address,
    connection,
    connections,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import PROVIDER

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import PairAuthorityStore
from tests.unit.seed_state import SeedState

KEY = "sk-ant-api03-e1b-replacement-key-1111"
CHAT_COMPLETION = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)


class _ValidKeys:
    """Every key is valid; `during` runs inside the validation (after the pair capture)."""

    def __init__(self) -> None:
        self.during: Callable[[], Awaitable[None]] | None = None

    async def validate(self, _plugin: Any, _provider: str, _key: str) -> ApiKeyValidationResult:
        if self.during is not None:
            await self.during()
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    harness = ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)
    authenticated_client.app.state.api_key_validation_service = _ValidKeys()
    return harness


def _create(harness: ConnectionBackedHarness, label: str = "work") -> Any:
    return harness.client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": label, "api_key": KEY},
    )


def _created(harness: ConnectionBackedHarness, label: str = "work") -> str:
    response = _create(harness, label)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _effective(harness: ConnectionBackedHarness) -> str | None:
    effective = marker(harness).effective_connection_id
    return None if effective is None else str(effective)


def _chat_key(harness: ConnectionBackedHarness) -> tuple[int, Any]:
    captured: dict[str, Any] = {}

    async def completion(_self: Any, body: dict[str, Any]) -> Any:
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(CHAT_COMPLETION, completion):
        response = harness.client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    return response.status_code, captured.get("api_key")


def test_a_new_key_replaces_a_broken_effective_oauth_row(
    migrated: ConnectionBackedHarness,
) -> None:
    h = migrated
    h.seed_credential(state=SeedState.ERROR)
    old = h.migrated["default"]

    new = _created(h)

    assert _effective(h) == new
    assert connection(h, old).status == "revoked"
    row = connection(h, new)
    assert (row.status, row.auth_type, row.label) == ("active", "api_key", "work")
    assert json.loads(blob_at_connection_address(h, new) or "{}")["api_key"] == KEY
    assert _chat_key(h) == (200, KEY)


def test_a_key_named_like_a_working_effective_row_replaces_it(
    migrated: ConnectionBackedHarness,
) -> None:
    # WHY: the effective row's own label addresses it — how a working OAuth pair switches to an
    # API key in one step, as the Profile key write did.
    h = migrated
    h.seed_credential(state=SeedState.AUTHENTICATED)
    old = h.migrated["default"]
    label = connection(h, old).label

    new = _created(h, label=label)

    assert _effective(h) == new
    assert connection(h, old).status == "revoked"
    assert (connection(h, new).label, connection(h, new).auth_type) == (label, "api_key")
    assert _chat_key(h) == (200, KEY)


def test_a_key_with_another_label_leaves_a_working_effective_row(
    migrated: ConnectionBackedHarness,
) -> None:
    h = migrated
    h.seed_credential(state=SeedState.AUTHENTICATED)
    old = h.migrated["default"]
    before = marker(h)

    new = _created(h)

    assert marker(h) == before
    assert connection(h, old).status == "active"
    assert connection(h, new).status == "active"


def test_a_marker_move_during_the_validation_wins_and_creates_nothing(
    migrated: ConnectionBackedHarness,
) -> None:
    h = migrated
    h.seed_credential(state=SeedState.ERROR)
    old = h.migrated["default"]

    async def move_the_marker() -> None:
        pair = await PairAuthorityStore().read(h.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            h.account_id,
            PROVIDER,
            expected_generation=pair.generation,
            migration_state="migrated",
            effective_connection_id=pair.effective_connection_id,
        )

    h.client.app.state.api_key_validation_service.during = move_the_marker
    rows_before = len(connections(h))

    response = _create(h)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "connection_conflict"
    assert _effective(h) == old
    assert connection(h, old).status == "error"
    assert len(connections(h)) == rows_before
    assert not h.call(OAuthConnectionStore().label_exists, h.account_id, PROVIDER, "work")
