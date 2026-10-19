"""OME-307 Unit 1 — OAuth completion keeps the stable-row-first lock order.

FEATURE: OAuth Connection completion with its D14 compat-document mirror (credential blob +
profile-index write).
STORY: as an operator completing an OAuth login on a PostgreSQL-backed gateway worker while a key
write runs for the same account, both publications complete instead of deadlocking.

INVARIANT: every lifecycle transaction mutates the always-present account index row before the
optional credential row; the reverse order deadlocks against index-first writers on PostgreSQL.

WHY no single-acquisition deadlock schedule here: it pinned `authenticate_pending`, which retired
with the legacy Profile OAuth callback at OME-1209 Stage E3b. Concurrent index publications are
pinned in `test_profile_index.py` (`test_concurrent_upserts_preserve_both_profiles`) and
`test_profile_delete_set_race.py`.
"""

from __future__ import annotations

import httpx

import aigateway.routes.auth as auth_module
from aigateway.core.credential_names import profile_id_for
from aigateway.core.profile_models import Profile, ProfileState


def test_oauth_profile_completion_locks_index_before_optional_credential(
    authenticated_client,
    monkeypatch,
) -> None:
    """OAuth completion must share profile set/delete's stable-row-first lock order.

    INVARIANT: every profile lifecycle transaction mutates the always-present account index row
    before touching the optional credential row. Credential-first OAuth completion can deadlock
    against index-first API-key set/delete on PostgreSQL.
    """
    calls: list[str] = []
    index = authenticated_client.app.state.profile_index
    upsert = index.upsert
    persist_credentials = auth_module.persist_credentials_or_503

    async def _record_index(profile, **kwargs) -> None:
        calls.append("index")
        await upsert(profile, **kwargs)

    async def _record_credential(*args, **kwargs) -> None:
        if kwargs.get("description") == "OAuth connection credentials":
            calls.append("credential")
        await persist_credentials(*args, **kwargs)

    async def _token_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "oauth-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    # WHY a seeded PENDING document: the native callback mirrors its success onto a same-named
    # compat document (D14), which is the index write this order is about.
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    authenticated_client.portal.call(
        index.upsert,
        Profile(
            id=profile_id_for(account_id, "anthropic", "work"),
            account_id=account_id,
            provider="anthropic",
            name="work",
            state=ProfileState.PENDING,
        ),
    )
    monkeypatch.setattr(index, "upsert", _record_index)
    monkeypatch.setattr(auth_module, "persist_credentials_or_503", _record_credential)
    authenticated_client.app.state.anthropic_http_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_token_handler), timeout=httpx.Timeout(5.0)
    )
    started = authenticated_client.post(
        "/v1/oauth/connections", json={"provider": "anthropic", "label": "work"}
    )
    assert started.status_code == 201, started.text
    state = started.json()["state"]
    completed = authenticated_client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert completed.status_code == 200
    assert calls == ["index", "credential"]
