"""OME-307 Unit 2 — OAuth flow generation ownership.

FEATURE: profile OAuth authentication with concurrent-flow safety.
STORY: as a user who restarts an OAuth login for a profile while an earlier attempt is
still exchanging its code, the earlier (stale) attempt must not hijack the profile the
new attempt now owns.

INVARIANT: pending-profile publication is bound to the CURRENT OAuth operation, not
merely to ``profile.state == pending``. A stale callback whose operation has been
superseded by a newer pending flow for the same account/provider/profile receives the
retryable ``profile_auth_conflict`` (409) and modifies neither the credential nor the
profile owned by the newer flow. The profile-state CAS remains as defense in depth for
the case where the newer flow has already committed.

The Profile OAuth start route answers 410 since OME-1209 Stage E3, but the legacy-pending callback
branch these tests observe still ships until E4 (owner decision D2): flows are opened with the
shared `open_oauth_flow` seeder and the profile is read from the index. Tests whose only subject or
only legacy actor was a retired route (a failing start or redirect never superseding an older flow;
a stale failure racing a Profile API-key PUT or a Profile DELETE; a delete-and-recreate reusing a
generation) retired with those routes (owner decision D1); `test_legacy_profile_routes_retired.py`
pins the 410.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from typing import Any

import httpx
import pytest

import aigateway.routes.auth as auth_module
from aigateway.core.credential_names import credential_name_for, profile_id_for
from aigateway.core.profile_index import ProfileIndexStore, ProfileTransitionConflict
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.plugins.anthropic_provider.auth import credential_service_for

from ._pg_mvcc_store import MvccRowStore
from .oauth_flow_seed import open_oauth_flow


@contextmanager
def _server_errors_as_responses(client) -> Iterator[None]:
    """Return unhandled route exceptions as 500 responses (as the ASGI server would) instead
    of re-raising them into the sync TestClient's calling thread."""
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


def _token_factory(
    token: str,
    *,
    stall: threading.Event | None = None,
    started: threading.Event | None = None,
):
    async def token_handler(_request: httpx.Request) -> httpx.Response:
        if started is not None:
            started.set()
        if stall is not None and not await asyncio.to_thread(stall.wait, 5):
            raise TimeoutError("OAuth exchange was not released")
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


def _failing_token_factory(
    *,
    stall: threading.Event | None = None,
    started: threading.Event | None = None,
    sentinel: str = "SENSITIVE-PROVIDER-BODY",
):
    async def token_handler(_request: httpx.Request) -> httpx.Response:
        if started is not None:
            started.set()
        if stall is not None and not await asyncio.to_thread(stall.wait, 5):
            raise TimeoutError("OAuth exchange was not released")
        # A provider-side failure whose body carries a sentinel we assert never leaks.
        return httpx.Response(400, json={"error": "invalid_grant", "detail": sentinel})

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


# WHY: the Profile OAuth start and status routes answer 410 since OME-1209 Stage E3; the seeder
# leaves exactly the pending document and entry the start route left, which is all the callback
# reads, and the index holds what the status route rendered.
def _open_flow(client, account_id: str) -> str:
    """Open one Profile OAuth flow for `anthropic/work`; returns its `state`."""
    return client.portal.call(
        partial(
            open_oauth_flow, client.app, account_id=account_id, provider="anthropic", name="work"
        )
    )


def _profile(client, account_id: str) -> dict[str, Any]:
    """The `anthropic/work` Profile as the retired status route rendered it."""
    index: ProfileIndexStore = client.app.state.profile_index
    profile = client.portal.call(index.get, account_id, "anthropic", "work")
    assert profile is not None, "profile anthropic/work is missing from the index"
    return profile.model_dump(mode="json")


def test_stale_oauth_callback_does_not_publish_into_newer_flow(
    authenticated_client,
    credential_blobs,
) -> None:
    """Concrete schedule:

    1. Flow A starts (seeded pending flow) and its callback stalls during token exchange
       (A has already consumed its own pending state before the exchange await).
    2. Flow B starts for the SAME account/provider/profile, creating a new pending
       operation that now owns the profile.
    3. Flow A is released and resumes; its publication must be rejected with a retryable
       409 profile_auth_conflict, leaving no orphan credential and B still the owner.
    4. Flow B completes and wins.
    """
    exchange_started = threading.Event()
    release_exchange = threading.Event()
    authenticated_client.app.state.anthropic_http_factory = _token_factory(
        "oauth-A-token", stall=release_exchange, started=exchange_started
    )

    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    state_a = _open_flow(authenticated_client, account_id)
    service = credential_service_for(credential_name_for(account_id, "work"))

    with ThreadPoolExecutor(max_workers=1) as executor:
        callback_a = executor.submit(
            authenticated_client.get,
            "/v1/auth/anthropic/callback",
            params={"code": "code-A", "state": state_a},
            follow_redirects=False,
        )
        assert exchange_started.wait(5), "flow A never reached token exchange"

        # Flow B starts for the same profile while A is stalled: B is now the owner.
        state_b = _open_flow(authenticated_client, account_id)

        release_exchange.set()
        response_a = callback_a.result(timeout=5)

    # Flow A is stale: retryable conflict, and it published nothing of B's.
    assert response_a.status_code == 409
    assert response_a.json()["detail"]["code"] == "profile_auth_conflict"
    assert "oauth-A-token" not in response_a.text
    profile = _profile(authenticated_client, account_id)
    assert profile["state"] == "pending"  # still B's pending profile
    # INVARIANT: a rejected stale publication leaves no orphan credential behind.
    assert credential_blobs.read(service, "default") is None

    # Flow B remains the owner and completes successfully with its own credentials.
    authenticated_client.app.state.anthropic_http_factory = _token_factory("oauth-B-token")
    response_b = authenticated_client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code-B", "state": state_b},
        follow_redirects=False,
    )
    assert response_b.status_code == 200
    profile_b = _profile(authenticated_client, account_id)
    assert profile_b["state"] == "authenticated"
    assert profile_b["auth_type"] == "oauth"
    assert "oauth-B-token" in json.loads(credential_blobs.read(service, "default"))["access_token"]


def test_oauth_callback_cancellation_restores_consumed_pending_state(
    authenticated_client,
    credential_blobs,
    monkeypatch,
) -> None:
    """OME-307 Blocker 5 — a cancelled callback must not strand the profile pending.

    Schedule:
    1. Flow A starts (seeded pending flow) and publishes its pending profile + ownership generation.
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
    state = _open_flow(authenticated_client, account_id)
    service = credential_service_for(credential_name_for(account_id, "work"))

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
    # The profile is untouched and no credential was written or corrupted.
    profile = _profile(authenticated_client, account_id)
    assert profile["state"] == "pending"
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
    profile_done = _profile(authenticated_client, account_id)
    assert profile_done["state"] == "authenticated"
    assert profile_done["auth_type"] == "oauth"
    assert "oauth-A-token" in json.loads(credential_blobs.read(service, "default"))["access_token"]


def test_stale_oauth_failure_does_not_corrupt_newer_owner(
    authenticated_client,
    credential_blobs,
) -> None:
    """OME-307 Blocker 2 — a stale OAuth FAILURE must not corrupt the newer owner.

    Schedule:
    1. Flow A starts and its callback stalls during token exchange.
    2. Flow B starts for the same profile and becomes the pending owner (a newer generation).
    3. Flow A's exchange then fails. Its failure handler must mark the profile ERROR only if A
       still owns the pending profile — since B now owns it, A's failure is a no-op. An
       unconditional error-upsert (the pre-fix behavior) would instead flip B's pending profile
       to ERROR, and B's later completion would then 409 (``state != pending``). The provider
       failure body must also never leak into the sanitized callback response.
    """
    exchange_started = threading.Event()
    release_exchange = threading.Event()
    sentinel = "SENSITIVE-PROVIDER-BODY"
    authenticated_client.app.state.anthropic_http_factory = _failing_token_factory(
        stall=release_exchange, started=exchange_started, sentinel=sentinel
    )

    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    state_a = _open_flow(authenticated_client, account_id)
    service = credential_service_for(credential_name_for(account_id, "work"))

    with (
        _server_errors_as_responses(authenticated_client),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        callback_a = executor.submit(
            authenticated_client.get,
            "/v1/auth/anthropic/callback",
            params={"code": "code-A", "state": state_a},
            follow_redirects=False,
        )
        assert exchange_started.wait(5), "flow A never reached token exchange"

        # Flow B starts and becomes the pending owner while A is stalled.
        state_b = _open_flow(authenticated_client, account_id)

        release_exchange.set()
        response_a = callback_a.result(timeout=5)

    # A failed, sanitized — no provider body leaked into the response.
    assert response_a.status_code == 500
    assert sentinel not in response_a.text
    # B still owns a PENDING profile — A's stale failure did NOT mark it ERROR.
    profile = _profile(authenticated_client, account_id)
    assert profile["state"] == "pending"
    assert credential_blobs.read(service, "default") is None  # no credential written or corrupted

    # B completes and wins — impossible if A had marked the profile ERROR.
    authenticated_client.app.state.anthropic_http_factory = _token_factory("oauth-B-token")
    response_b = authenticated_client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code-B", "state": state_b},
        follow_redirects=False,
    )
    assert response_b.status_code == 200
    profile_b = _profile(authenticated_client, account_id)
    assert profile_b["state"] == "authenticated"
    assert profile_b["auth_type"] == "oauth"
    assert "oauth-B-token" in json.loads(credential_blobs.read(service, "default"))["access_token"]


@pytest.mark.asyncio
async def test_newer_flow_published_after_success_precondition_owns_durable_cas() -> None:
    """Pause A at the durable-CAS boundary, then let B claim the profile.

    INVARIANT: the generation comparison belongs to the same durable mutation that publishes
    AUTHENTICATED. A precondition checked immediately before this boundary cannot authorize A
    after B has durably claimed a newer generation.
    """
    account_id = "account-1"
    profile_id = profile_id_for(account_id, "anthropic", "work")
    store = MvccRowStore()
    index_a = ProfileIndexStore(credential_store=store)
    index_b = ProfileIndexStore(credential_store=store)
    pending = Profile(
        id=profile_id,
        account_id=account_id,
        provider="anthropic",
        name="work",
        state=ProfileState.PENDING,
    )
    generation_a = await index_a.begin_pending(pending)
    a_checked_precondition = asyncio.Event()
    release_a = asyncio.Event()
    credential_key = ("aigateway:anthropic:work", "default")

    async def publish_a() -> None:
        observed = await index_a.get(account_id, "anthropic", "work")
        assert observed is not None and observed.state is ProfileState.PENDING
        a_checked_precondition.set()
        await release_a.wait()
        authenticated = pending.model_copy(update={"state": ProfileState.AUTHENTICATED})
        async with store.transaction():
            await index_a.authenticate_pending(authenticated, expected_generation=generation_a)
            await store.write(*credential_key, "oauth-A-token")

    task_a = asyncio.create_task(publish_a())
    await a_checked_precondition.wait()
    generation_b = await index_b.begin_pending(pending)
    release_a.set()
    result_a = (await asyncio.gather(task_a, return_exceptions=True))[0]

    assert isinstance(result_a, ProfileTransitionConflict)
    assert store.committed.get(credential_key) is None
    current = await index_b.get(account_id, "anthropic", "work")
    assert current is not None and current.state is ProfileState.PENDING

    authenticated_b = pending.model_copy(update={"state": ProfileState.AUTHENTICATED})
    async with store.transaction():
        await index_b.authenticate_pending(authenticated_b, expected_generation=generation_b)
        await store.write(*credential_key, "oauth-B-token")
    assert store.committed[credential_key] == "oauth-B-token"


@pytest.mark.asyncio
async def test_oauth_completion_preserves_metadata_patch_committed_before_cas() -> None:
    """Lifecycle publication must merge into the latest profile, not replace its metadata."""
    account_id = "account-1"
    profile_id = profile_id_for(account_id, "anthropic", "work")
    store = MvccRowStore()
    index = ProfileIndexStore(credential_store=store)
    pending = Profile(
        id=profile_id,
        account_id=account_id,
        provider="anthropic",
        name="work",
        state=ProfileState.PENDING,
    )
    generation = await index.begin_pending(pending)
    stale_for_callback = await index.get(account_id, "anthropic", "work")
    assert stale_for_callback is not None

    patched_defaults = stale_for_callback.defaults.model_copy(update={"max_tokens": 2048})
    await index.update_metadata(profile_id, defaults=patched_defaults)
    stale_for_callback.state = ProfileState.AUTHENTICATED
    stale_for_callback.auth_type = "oauth"
    await index.authenticate_pending(
        stale_for_callback,
        expected_generation=generation,
    )

    completed = await index.get(account_id, "anthropic", "work")
    assert completed is not None
    assert completed.state is ProfileState.AUTHENTICATED
    assert completed.defaults.max_tokens == 2048
