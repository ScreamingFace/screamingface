"""OME-307 Unit 2 — a cancelled OAuth callback keeps its flow completable.

FEATURE: OAuth Connection authentication (no compat-document mirror since OME-1209 E4b).
STORY: as a user whose OAuth callback is cancelled during the token exchange, I can retry the same
flow instead of being stranded with a consumed state.

INVARIANT: a callback that consumed its pending state before the token-exchange await re-publishes
it when cancelled, so the flow stays completable; the cancellation itself propagates.

WHY the other schedules are gone: since OME-1209 Stage E3b every pending flow is a native Connection
flow, so the Profile ownership generations they pinned no longer exist. A stale callback superseded
by a newer start is pinned in `core/provider_access/test_writer_floor_native.py`
(`test_a_second_native_oauth_start_supersedes_the_first_flow`); a stale failure that must not
corrupt a newer owner, and its sanitized response, in `test_auth_routes.py`
(`test_connection_delete_wins_over_stalled_oauth_failure`,
`test_callback_error_html_sanitizes_provider_response`). The two direct index schedules pinned
`begin_pending` and `authenticate_pending`, which retired with the legacy callback branch.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any

import httpx
import pytest

import aigateway.routes.auth as auth_module
from aigateway.core.oauth.store import credential_key_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for


def _token_factory(token: str):
    async def token_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": f"refresh-{token}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


def _open_flow(client) -> tuple[str, str]:
    """Open one native OAuth flow labelled `work`; returns its `state` and `connection_id`."""
    started = client.post("/v1/oauth/connections", json={"provider": "anthropic", "label": "work"})
    assert started.status_code == 201, started.text
    body = started.json()
    return body["state"], body["connection_id"]


# WHY the Connection (OME-1209 E4b): the callback mirrors its outcome onto no Profile document, so
# the flow's own Connection is what observes it.
def _connection(client, connection_id: str) -> dict[str, Any]:
    response = client.get(f"/v1/oauth/connections/{connection_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_oauth_callback_cancellation_restores_consumed_pending_state(
    authenticated_client,
    credential_blobs,
    monkeypatch,
) -> None:
    """OME-307 Blocker 5 — a cancelled callback must not strand the profile pending.

    Schedule:
    1. Flow A starts natively over a seeded pending profile and claims the pair's generation.
    2. A's callback consumes (pops) its pending state, then a ``BaseException`` cancellation
       fires during the token-exchange await (Python 3.12 ``asyncio.CancelledError`` escapes
       ``except Exception``).
    3. The consumed state MUST be re-published synchronously so the flow stays retryable, and
       the cancellation MUST propagate (cleanup, never suppress). The profile is untouched
       (still pending) and no credential is written.
    4. A retry of the SAME flow, with a working exchange, completes successfully — proving the
       restored state carried the original ownership generation.

    Against the pre-fix code the state is popped before the exchange await and never restored,
    so the flow is unrecoverable (``peek`` returns ``None``) — this test is RED there.
    """
    authenticated_client.app.state.anthropic_http_factory = _token_factory("oauth-A-token")

    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    state, connection_id = _open_flow(authenticated_client)
    service = credential_service_for(credential_key_for(account_id, connection_id))

    async def _cancel_during_exchange(*_args, **_kwargs):
        # A cooperative cancellation at the network await — the realistic callback cancel window.
        raise asyncio.CancelledError()

    monkeypatch.setattr(auth_module, "_exchange_oauth_code_for_pending", _cancel_during_exchange)

    with pytest.raises((concurrent.futures.CancelledError, asyncio.CancelledError)) as excinfo:
        authenticated_client.get(
            "/v1/auth/anthropic/callback",
            params={"code": "code-A", "state": state},
            follow_redirects=False,
        )
    # The cancellation propagated to the caller — it was not caught-and-suppressed.
    assert isinstance(excinfo.value, (concurrent.futures.CancelledError, asyncio.CancelledError))

    # INVARIANT (Blocker 5): the consumed state is restored, so the flow is still completable.
    assert authenticated_client.app.state.pending_auth.peek(state) is not None
    # The Connection is untouched and no credential was written or corrupted.
    assert _connection(authenticated_client, connection_id)["status"] == "pending"
    assert credential_blobs.read(service, "default") is None

    # Retrying the SAME flow with a working exchange completes — the restored entry still owns it.
    monkeypatch.undo()
    authenticated_client.app.state.anthropic_http_factory = _token_factory("oauth-A-token")
    retry = authenticated_client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code-A", "state": state},
        follow_redirects=False,
    )
    assert retry.status_code == 200
    done = _connection(authenticated_client, connection_id)
    assert done["status"] == "active"
    assert done["auth_type"] == "oauth"
    assert "oauth-A-token" in json.loads(credential_blobs.read(service, "default"))["access_token"]
