"""The chat route over a MIGRATED pair speaks to its effective Connection (S2'b3).

# FEATURE: Stage B Target — locator-authoritative reads. Item 0 pins that the chat route already
# speaks to the port over a migrated pair, so op 5's error marking and the pair's state agree.
# WHY the status/patch facade tests are gone: OME-1209 Stage E3 retired `GET …/profiles/{name}/
# status`, `PATCH …/profiles/{name}` and the admin PATCH (they answer 410), so the tests that
# rendered a pair through them retired with the routes. The Connection reads that replace them are
# covered by `test_connection_backed_native_routes.py` and
# `tests/unit/test_provider_access_availability_route.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from connection_backed_admin_probes import connection, marker
from connection_backed_harness import ConnectionBackedHarness
from litellm.exceptions import AuthenticationError
from provider_access_harness import PROVIDER

from aigateway.core.credential_names import credential_name_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

CHAT_COMPLETION = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)
REAUTH = "/v1/oauth/connections"


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def chat(harness: Any, completion: Any) -> httpx.Response:
    with patch(CHAT_COMPLETION, completion):
        return harness.client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )


# --- item 0: the chat route over a migrated pair -----------------------------------------------


def test_chat_over_a_migrated_pair_sends_the_connection_credential(migrated) -> None:
    h = migrated
    h.seed_credential()  # document + Profile-addressed blob "tok" + active Connection + marker
    captured: dict[str, Any] = {}

    async def completion(_self: Any, body: dict[str, Any]) -> Any:
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    resp = chat(h, completion)

    assert resp.status_code == 200, resp.text
    assert captured["api_key"] == "tok"
    row = connection(h, h.migrated["default"])
    assert (row.status, row.last_used_at is not None) == ("active", True)
    assert marker(h).generation == 1


def test_a_rejected_dispatch_marks_the_connection_and_the_status_facade_agrees(migrated) -> None:
    h = migrated
    h.seed_credential()
    effective = h.migrated["default"]

    async def rejecting(_self: Any, _body: dict[str, Any]) -> Any:
        raise AuthenticationError(
            "invalid x-api-key", llm_provider="anthropic", model="anthropic/claude-haiku-4-5"
        )

    resp = chat(h, rejecting)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "auth_required"
    assert resp.json()["detail"]["reauth_url"] == REAUTH
    assert connection(h, effective).status == "error"
    assert credential_name_for(h.account_id, "default") in h.evicted()
    # INVARIANT: op 5 marked the AUTHORITY; the facade must show that, not the mirror's old state.
    assert h.credential_state() == "error"


def test_migrated_api_key_401_keeps_legacy_handling_without_observing_anthropic(
    migrated,
) -> None:
    h = migrated
    h.seed_credential(auth_type="api_key")
    effective = h.migrated["default"]
    calls = 0

    async def rejecting(_self: Any, _body: dict[str, Any]) -> Any:
        nonlocal calls
        calls += 1
        raise AuthenticationError(
            "invalid x-api-key", llm_provider="anthropic", model="anthropic/claude-haiku-4-5"
        )

    first = chat(h, rejecting)

    assert first.status_code == 401, first.text
    assert first.json()["detail"] == {
        "code": "auth_required",
        "message": "The stored provider credential was rejected.",
        "reauth_url": f"{REAUTH}/{effective}/api-key",
    }
    assert connection(h, effective).status == "error"
    listed = {
        row["provider"]: row["status"]
        for row in h.client.get("/v1/provider-access").json()["providers"]
    }
    assert listed[PROVIDER] == "error"

    second = chat(h, rejecting)
    assert second.status_code == 401
    assert calls == 1, "resolve must reject the revoked key before a second provider dispatch"

    state = h.call(
        h.client.app.state.credential_store.operational_state,
        credential_service_for(credential_name_for(h.account_id, "default")),
        "default",
    )
    assert state is not None
    assert state.next_dispatch_sequence == 0
