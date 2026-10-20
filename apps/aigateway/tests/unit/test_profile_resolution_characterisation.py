"""Characterisation of today's Profile-vs-Connection resolution (OME-1198, Stage 0 of OME-1138).

# FEATURE: OME-1138 adapter-first convergence. Stage A1 relocates the resolver cluster in
# `routes/chat_credentials.py` behind the provider-access port. These tests pin behaviours the
# resolver has TODAY but that no other test asserts, so the relocation has a parity net.
# INVARIANT: this module records LEGACY behaviour exactly; it does not judge or fix it. Two of
# the pinned behaviours are known risks (the shadow Connection that stays reachable after a
# Profile delete; the unhandled resolver-read fault) — changing them is a separate, later decision
# (spec `docs/spec/2026-09-09-OME-1138-converge-connections.md` §8 D14 and §10). A test here
# going red after A1 means the boundary changed behaviour, never that the behaviour was wrong.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from aigateway.core.credential_names import credential_name_for, profile_id_for
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.core.provider_access import PairAuthorityStore
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_CHAT = "/v1/chat/completions"
_ANTHROPIC_CHAT = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)
_PROFILE_TOKEN = "profile-tok"


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _body() -> dict:
    return {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hi"}],
    }


def _oauth_blob(access_token: str) -> str:
    return json.dumps(
        {
            "access_token": access_token,
            "refresh_token": "rt",
            "expires_at_ms": int(time.time() * 1000) + 3_600_000,
            "token_type": "Bearer",
        }
    )


async def _seed_default_profile(credential_blobs, account_id: str) -> None:
    """An AUTHENTICATED Profile named `default` for anthropic, with its OAuth blob."""
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, "default")),
        "default",
        _oauth_blob(_PROFILE_TOKEN),
    )
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )


async def _create_active_connection(account_id: str, *, label: str):
    store = OAuthConnectionStore()
    connection = await store.create_pending(
        account_id=account_id,
        provider="anthropic",
        label=label,
        connection_id=uuid4(),
    )
    return await store.complete(connection, label=label, identity=None)


def _seed_connection_credentials(
    credential_blobs, account_id: str, connection_id: UUID, *, access_token: str
) -> None:
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection_id)),
        "default",
        _oauth_blob(access_token),
    )


def _active_connection(client, credential_blobs, account_id: str, *, label: str, token: str):
    connection = client.portal.call(partial(_create_active_connection, account_id, label=label))
    _seed_connection_credentials(credential_blobs, account_id, connection.id, access_token=token)
    return connection


@contextmanager
def _server_errors_as_responses(client) -> Iterator[None]:
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


_UNSUPPORTED_DETAIL = {
    "code": "x_profile_unsupported",
    "message": "X-Profile is no longer supported; omit the header.",
}


# --- 1. a selector-less Profile `default` beside an active Connection -----------------------
# WHY: the "Profile beats Connection" pin retired at OME-1209 Stage E4a. Resolve reads no Profile
# document, so the Connection answers (`test_connection_only_resolve.py`); only the control stays.


def test_literal_default_x_profile_is_rejected_without_dispatch(
    credential_blobs, authenticated_client
) -> None:
    """Literal ``default`` is an explicit selector and is rejected before target resolution."""
    account_id = _account_id(authenticated_client)
    authenticated_client.portal.call(partial(_seed_default_profile, credential_blobs, account_id))
    _active_connection(
        authenticated_client,
        credential_blobs,
        account_id,
        label="work-anthropic",
        token="connection-tok",
    )

    dispatched = AsyncMock()
    with patch(_ANTHROPIC_CHAT, dispatched):
        resp = authenticated_client.post(_CHAT, headers={"X-Profile": "default"}, json=_body())

    assert resp.status_code == 400
    assert resp.json()["detail"] == _UNSUPPORTED_DETAIL
    assert "default" not in resp.text
    dispatched.assert_not_called()


# --- 2. blank `X-Profile` is absent; every named selector is rejected ------------------------


@pytest.mark.parametrize("blank", ["   ", "\t", " \t "])
def test_whitespace_only_x_profile_header_behaves_as_absent(
    credential_blobs, authenticated_client, blank: str
) -> None:
    """# INVARIANT (legacy, pinned): `chat.py:242` collapses a blank header to `default`
    (`(header or "default").strip() or "default"`). Two active Connections and no Profile make
    the `default` selector ambiguous (409), while a NAMED selector would answer 404
    `connection_not_found` — so the status code distinguishes "absent" from "named blank".
    """
    account_id = _account_id(authenticated_client)
    _active_connection(
        authenticated_client, credential_blobs, account_id, label="work-anthropic", token="w"
    )
    _active_connection(
        authenticated_client, credential_blobs, account_id, label="personal-anthropic", token="p"
    )

    absent = authenticated_client.post(_CHAT, json=_body())
    blank_header = authenticated_client.post(_CHAT, headers={"X-Profile": blank}, json=_body())

    assert absent.status_code == 409
    assert absent.json()["detail"]["code"] == "connection_ambiguous"
    assert blank_header.status_code == absent.status_code
    # `detail` is the resolver's contract; the `_aigw` envelope carries a per-call id.
    assert blank_header.json()["detail"] == absent.json()["detail"]


def test_a_named_x_profile_header_is_rejected_without_dispatch(
    credential_blobs, authenticated_client
) -> None:
    """Control for the blank-header pin: a nonblank value is rejected at ingress."""
    account_id = _account_id(authenticated_client)
    _active_connection(
        authenticated_client, credential_blobs, account_id, label="work-anthropic", token="w"
    )
    _active_connection(
        authenticated_client,
        credential_blobs,
        account_id,
        label="personal-anthropic",
        token="personal-tok",
    )

    dispatched = AsyncMock()
    with patch(_ANTHROPIC_CHAT, dispatched):
        resp = authenticated_client.post(
            _CHAT, headers={"X-Profile": "personal-anthropic"}, json=_body()
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == _UNSUPPORTED_DETAIL
    assert "personal-anthropic" not in resp.text
    dispatched.assert_not_called()


# --- 3. the shadow Connection outlives the Profile that created it ---------------------------
# WHY: retired at OME-1209 Stage E3. The pin needed a Profile-only delete, and the Profile DELETE
# route answers 410 since then (`test_legacy_profile_routes_retired.py`), so no live route can
# delete a Profile while leaving its shadow Connection behind.


# --- 4. a persistent marker fault at the resolver read is UNHANDLED --------------------------


async def _always_failing_read(*_args, **_kwargs):
    raise RuntimeError("the pair marker row could not be decoded")


def test_a_persistent_marker_fault_at_the_resolver_read_escapes_the_route(
    authenticated_client, monkeypatch
) -> None:
    """# INVARIANT (legacy, pinned — spec §10): the resolver's first read, the pair marker
    (OME-1209 Stage E4a), sits BEFORE the dispatch exception boundary and has no handler
    of its own, so a store fault that persists past the pre-cache read (which swallows it and
    bypasses the cache) escapes the route as the raw exception. Nothing is dispatched.
    The class seam is patched because the port reads the marker through its own
    `PairAuthorityStore` instance.
    """
    monkeypatch.setattr(PairAuthorityStore, "read", _always_failing_read)
    dispatched = AsyncMock()

    with (
        patch(_ANTHROPIC_CHAT, dispatched),
        pytest.raises(RuntimeError, match="could not be decoded"),
    ):
        authenticated_client.post(_CHAT, json=_body())

    dispatched.assert_not_called()


def test_a_persistent_marker_fault_at_the_resolver_read_renders_a_bare_500(
    authenticated_client, monkeypatch
) -> None:
    """The wire outcome of the same fault: Starlette's default server-error page, not the
    gateway's JSON `detail` envelope and not the 503 `profile_index_conflict` mapping (that
    handler covers only CAS-retry exhaustion, `main.py:296-307`)."""
    monkeypatch.setattr(PairAuthorityStore, "read", _always_failing_read)

    with _server_errors_as_responses(authenticated_client):
        resp = authenticated_client.post(_CHAT, json=_body())

    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == "gateway_internal_error"
    assert resp.json()["detail"]["gateway_call_id"].startswith("call_")
