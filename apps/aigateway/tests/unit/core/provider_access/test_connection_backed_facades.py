"""The Profile status/patch facades of a MIGRATED pair render from its effective Connection (S2'b3).

# FEATURE: Stage B Target — locator-authoritative reads: `GET …/profiles/{name}/status`,
# `PATCH …/profiles/{name}` and the admin PATCH show the effective Connection's state and auth
# type; `defaults`/`account_label` stay on the compatibility document (D16 (a)). Item 0 pins that
# the chat route already speaks to the port over a migrated pair, so op 5's error marking and the
# status facade agree.
# INVARIANT: an unmigrated pair keeps today's bodies byte for byte and never writes a marker.
"""

from __future__ import annotations

from ipaddress import ip_network
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from connection_backed_admin_probes import connection, document, marker
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import detach_effective, status
from fastapi.testclient import TestClient
from litellm.exceptions import AuthenticationError
from provider_access_harness import PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.profile_index import ProfileTransitionConflict
from aigateway.core.profile_models import ProfileDefaults, ProfileState, credential_name_for
from aigateway.core.provider_access import PairAuthorityStore

ADMIN = "admin@openmined.org"
CHAT_COMPLETION = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)
REAUTH = f"/v1/auth/{PROVIDER}/profiles/default"


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


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


def patch_profile(harness: Any, name: str = "default", **body: Any) -> httpx.Response:
    return harness.client.patch(f"/v1/auth/{PROVIDER}/profiles/{name}", json=body)


def mark_effective_error(harness: Any, connection_id: str, message: str = "rejected") -> None:
    row = connection(harness, connection_id)
    assert harness.call(OAuthConnectionStore().mark_error, row, message) is not None


def admin_client(harness: Any) -> TestClient:
    """The app in header mode with `ADMIN` allowlisted, addressed from a trusted peer."""
    settings = harness.client.app.state.settings
    settings.auth_mode = "cloudflare_headers"
    settings.allowed_networks = (ip_network("10.0.0.0/8"),)
    settings.admin_emails = frozenset({ADMIN})
    return TestClient(
        harness.client.app, client=("10.1.2.3", 50000), headers={"X-User-Email": ADMIN}
    )


# --- item 0: the chat route over a migrated pair -----------------------------------------------


def test_chat_over_a_migrated_pair_sends_the_connection_credential(migrated) -> None:
    h = migrated
    h.seed_profile()  # document + Profile-addressed blob "tok" + active Connection + marker
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
    h.seed_profile()
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
    shown = status(h)
    assert shown.status_code == 200
    assert shown.json()["state"] == "error"
    assert h.profile_state() == "error"


# --- status ------------------------------------------------------------------------------------


def test_status_renders_a_migrated_pair_from_its_effective_connection(migrated) -> None:
    h = migrated
    h.seed_profile()  # the document says authenticated / oauth
    effective = h.migrated["default"]
    row = connection(h, effective)
    assert h.call(OAuthConnectionStore().set_auth_type, row, "api_key") is not None
    mark_effective_error(h, effective)

    body = status(h).json()

    assert (body["state"], body["auth_type"]) == ("error", "api_key")
    assert body["account_label"] is None
    # WHY: the document is a rollback mirror, never load-bearing for a read (D-S2b3-2).
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED


def test_status_is_404_when_a_migrated_pair_has_no_effective_connection(migrated) -> None:
    h = migrated
    h.seed_profile()
    detach_effective(h, h.migrated["default"])

    shown = status(h)

    assert shown.status_code == 404
    assert shown.json()["detail"] == {
        "code": "profile_not_found",
        "provider": PROVIDER,
        "name": "default",
    }
    listed = h.client.get("/v1/auth/profiles").json()["profiles"]
    assert [p["name"] for p in listed if p["provider"] == PROVIDER] == []


def test_status_of_an_unmigrated_pair_keeps_the_legacy_document(legacy) -> None:
    h = legacy
    h.seed_profile(state=ProfileState.ERROR)

    body = status(h).json()

    assert body == {
        "state": "error",
        "auth_type": "oauth",
        "account_label": None,
        "last_refreshed_at": None,
    }
    pair = marker(h)
    assert (pair.migration_state, pair.generation) == ("none", 0)


def test_status_of_a_quarantined_pair_keeps_the_legacy_document(legacy) -> None:
    h = legacy
    h.seed_profile(state=ProfileState.ERROR)
    h.call(
        PairAuthorityStore().advance,
        h.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note="ambiguous pair",
    )

    body = status(h).json()

    assert (body["state"], body["auth_type"]) == ("error", "oauth")
    pair = marker(h)
    assert (pair.migration_state, pair.generation) == ("quarantined", 1)


# --- patch -------------------------------------------------------------------------------------


def test_patch_keeps_metadata_on_the_document_and_renders_the_connection_state(migrated) -> None:
    h = migrated
    h.seed_profile(defaults=ProfileDefaults(max_tokens=3))
    effective = h.migrated["default"]
    mark_effective_error(h, effective)

    resp = patch_profile(h, defaults={"max_tokens": 7}, account_label="Work")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["state"], body["auth_type"]) == ("error", "oauth")
    assert body["defaults"]["max_tokens"] == 7
    assert body["account_label"] == "Work"
    doc = document(h)
    assert doc is not None
    assert (doc.defaults.max_tokens, doc.account_label) == (7, "Work")
    after = connection(h, effective)
    assert (after.status, after.label) == ("error", f"error:{effective}")
    # INVARIANT: a metadata edit is not authority-changing — the marker does not move.
    assert marker(h).generation == 1


def test_patch_is_404_when_a_migrated_pair_has_no_effective_connection(migrated) -> None:
    h = migrated
    h.seed_profile(defaults=ProfileDefaults(max_tokens=3))
    detach_effective(h, h.migrated["default"])

    resp = patch_profile(h, defaults={"max_tokens": 7})

    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "profile_not_found"}
    doc = document(h)
    assert doc is not None and doc.defaults.max_tokens == 3


def test_patch_answers_the_legacy_conflict_when_the_document_vanishes(
    migrated, monkeypatch
) -> None:
    h = migrated
    h.seed_profile()
    index = h.client.app.state.profile_index

    async def vanished(*_args: Any, **_kwargs: Any) -> Any:
        raise ProfileTransitionConflict("profile was concurrently deleted")

    monkeypatch.setattr(index, "update_metadata", vanished)

    resp = patch_profile(h, account_label="Work")

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "code": "profile_conflict",
        "provider": PROVIDER,
        "profile": "default",
    }


def test_patch_of_an_unmigrated_pair_keeps_the_legacy_body(legacy) -> None:
    h = legacy
    h.seed_profile(state=ProfileState.ERROR, defaults=ProfileDefaults(max_tokens=3))

    resp = patch_profile(h, defaults={"max_tokens": 7})

    assert resp.status_code == 200, resp.text
    assert (resp.json()["state"], resp.json()["defaults"]["max_tokens"]) == ("error", 7)
    pair = marker(h)
    assert (pair.migration_state, pair.generation) == ("none", 0)


def test_the_admin_patch_renders_the_connection_state_too(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    mark_effective_error(h, effective)
    admin = admin_client(h)

    resp = admin.patch(
        f"/v1/admin/accounts/{h.account_id}/profiles/{PROVIDER}/default",
        json={"account_label": "Team"},
    )

    assert resp.status_code == 200, resp.text
    assert (resp.json()["state"], resp.json()["account_label"]) == ("error", "Team")
    doc = document(h)
    assert doc is not None
    assert (doc.account_label, doc.state) == ("Team", ProfileState.AUTHENTICATED)
    assert connection(h, effective).status == "error"
