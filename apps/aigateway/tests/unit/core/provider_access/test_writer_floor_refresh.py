"""G0 writer floor — an OAuth refresh publishes only while its credential holds (OME-1497).

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3) — the four OAuth plugins only FETCH a refreshed
# token; the strategy publishes it through a guard that checks the owner and the revision of the
# blob it read, then writes the blob in one short transaction.
# INVARIANT: refresh is not an ownership change — it never advances the generation, and a refresh
# whose credential moved during its network window writes nothing, marks nothing errored and answers
# the existing superseded conflict (409 `profile_conflict` / `connection_conflict`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest
from connection_backed_admin_probes import (
    KEY,
    admin_of,
    blob_at_connection_address,
    blob_at_profile_address,
    connection,
    document,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of, callback, start, use_tokens
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.errors import AuthError, RefreshSuperseded
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import credential_key_for
from aigateway.core.profile_models import ProfileState, credential_name_for
from aigateway.core.provider_access import (
    PairAuthorityStore,
    ResolvePolicy,
    Selector,
    WriteConflict,
)
from aigateway.core.provider_access.refresh_guard import (
    ConnectionRefreshOwner,
    GuardedRefreshPublication,
)
from aigateway.core.provider_access.writer_floor import claim_pair
from aigateway.plugins.anthropic_provider.auth import AnthropicOAuth, credential_service_for

Intrusion = Callable[[], Awaitable[Any]]


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def use_intruding_tokens(
    h: Any, token: str | list[str], intrude: Intrusion, *, expires_in: int = 3600
) -> None:
    """A token endpoint that commits `intrude` INSIDE the refresh's provider network window.

    WHY in the handler: it runs on the app loop between the capture and the publication — the
    exact moment §5.3 says an ownership change must win over the refresh. A list of tokens is
    answered in order, one per refresh (a cached strategy keeps the factory it was built with).
    """
    tokens = [token] if isinstance(token, str) else list(token)
    answered: list[str] = []

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        if not answered:
            await intrude()
        current = tokens[min(len(answered), len(tokens) - 1)]
        answered.append(current)
        return httpx.Response(
            200,
            json={
                "access_token": current,
                "refresh_token": f"refresh-{current}",
                "expires_in": expires_in,
                "token_type": "Bearer",
            },
        )

    h.client.app.state.anthropic_http_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


def nothing() -> Intrusion:
    async def intrude() -> None:
        return None

    return intrude


def an_ownership_claim(h: Any) -> Intrusion:
    """Any ownership writer's claim on the pair — what a native create or a key change commits."""

    async def intrude() -> None:
        await claim_pair(await PairAuthorityStore().read(h.account_id, PROVIDER))

    return intrude


def a_key_replacement(h: Any) -> Intrusion:
    async def intrude() -> None:
        await admin_of(h).set_api_key(
            h.account_id, PROVIDER, raw_api_key=KEY, legacy_name="default"
        )

    return intrude


def a_delete(h: Any) -> Intrusion:
    async def intrude() -> None:
        await admin_of(h).delete(h.account_id, PROVIDER, legacy_name="default")

    return intrude


def expired_blob(token: str = "stale") -> str:
    return json.dumps(
        {
            "access_token": token,
            "refresh_token": "rt",
            "token_type": "Bearer",
            "expires_at_ms": int(time.time() * 1000) - 1_000,
        }
    )


def profile_service(h: Any) -> str:
    return credential_service_for(credential_name_for(h.account_id, "default"))


def connection_service(h: Any, connection_id: str) -> str:
    return credential_service_for(credential_key_for(h.account_id, connection_id))


def resolve_and_authorize(h: Any) -> Any:
    target = h.call(
        h.access.resolve,
        h.account_id,
        PROVIDER,
        Selector.from_header(None),
        plugin=ANTHROPIC,
        policy=ResolvePolicy.DISPATCH,
    )
    return h.call(h.access.authorize, target, plugin=ANTHROPIC, provider=PROVIDER)


# --- the exception boundary --------------------------------------------------------------------


def test_a_lost_refresh_is_not_an_auth_error() -> None:
    # INVARIANT: every caller marks a row errored on `AuthError`; a lost race is not a rejected
    # credential, so it must never travel that path.
    assert not issubclass(RefreshSuperseded, AuthError)


# --- the legacy Profile refresh route ----------------------------------------------------------


def test_a_legacy_refresh_that_lost_the_pair_to_a_key_replacement_keeps_the_new_key(
    legacy,
) -> None:
    h = legacy
    h.seed_profile()
    use_intruding_tokens(h, "fresh-tok", a_key_replacement(h))

    resp = h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == {
        "code": "profile_conflict",
        "provider": PROVIDER,
        "profile": "default",
    }
    blob = blob_at_profile_address(h)
    assert blob is not None and json.loads(blob)["api_key"] == KEY
    doc = document(h)
    assert doc is not None
    assert (doc.auth_type, doc.state) == ("api_key", ProfileState.AUTHENTICATED)
    # INVARIANT: only the key replacement moved the pair; the refresh did not.
    assert marker(h).generation == 1


def test_a_legacy_refresh_of_a_marked_pair_publishes_without_moving_it(legacy) -> None:
    h = legacy
    h.seed_profile()
    h.call(an_ownership_claim(h))
    use_intruding_tokens(h, "fresh-tok", nothing())

    resp = h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh")

    assert resp.status_code == 200, resp.text
    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
    pair = marker(h)
    assert (pair.migration_state, pair.generation) == ("none", 1)


# --- the native Connection refresh route and token endpoint -----------------------------------


def a_rewrite_of(h: Any, service: str) -> Intrusion:
    """Another writer replaced the refreshed blob's credential (its revision moves)."""

    async def intrude() -> None:
        await h.client.app.state.credential_store.write(service, "default", expired_blob("new"))

    return intrude


def test_a_native_refresh_that_lost_its_credential_writes_nothing_and_marks_nothing(
    legacy,
) -> None:
    h = legacy
    connection_id = h.seed_connection(label="work")
    before = marker(h)
    use_intruding_tokens(h, "fresh-tok", a_rewrite_of(h, connection_service(h, connection_id)))

    resp = h.client.post(f"/v1/oauth/connections/{connection_id}/refresh")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "new"
    assert connection(h, connection_id).status == "active"
    assert marker(h) == before


def test_a_native_token_refresh_that_lost_its_credential_writes_nothing_and_marks_nothing(
    legacy,
) -> None:
    h = legacy
    connection_id = h.seed_connection(label="work")
    service = connection_service(h, connection_id)
    h.blobs.write(service, "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", a_rewrite_of(h, service))

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "new"
    assert connection(h, connection_id).status == "active"


def test_a_cached_strategy_refreshes_again_after_an_unrelated_generation_change(legacy) -> None:
    # WHY: the capture happens per refresh, never when the strategy is built — a shared cached
    # strategy must not be stuck on the generation it first saw (§5.3 falsifier).
    h = legacy
    connection_id = h.seed_connection(label="work")
    h.blobs.write(connection_service(h, connection_id), "default", expired_blob())
    use_intruding_tokens(h, ["first", "second"], nothing(), expires_in=1)
    assert h.client.get(f"/v1/oauth/connections/{connection_id}/token").status_code == 200
    h.call(an_ownership_claim(h))

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 200, resp.text
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "second"
    assert marker(h).generation == 1


# --- dispatch (authorize-triggered refresh) ----------------------------------------------------


def test_a_dispatch_refresh_on_a_profile_that_lost_the_pair_keeps_the_new_key(legacy) -> None:
    h = legacy
    h.seed_profile()
    h.blobs.write(profile_service(h), "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", a_key_replacement(h))

    with pytest.raises(WriteConflict) as lost:
        resolve_and_authorize(h)

    assert (lost.value.kind, lost.value.subject) == ("superseded", "profile")
    blob = blob_at_profile_address(h)
    assert blob is not None and json.loads(blob)["api_key"] == KEY
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
    assert credential_name_for(h.account_id, "default") in h.evicted()


def test_a_dispatch_refresh_on_a_migrated_pair_deleted_in_its_window_resurrects_nothing(
    migrated,
) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    h.blobs.write(profile_service(h), "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", a_delete(h))

    with pytest.raises(WriteConflict) as lost:
        resolve_and_authorize(h)

    assert lost.value.kind == "superseded"
    assert blob_at_profile_address(h) is None
    assert connection(h, effective).status == "revoked"


# --- the migrated facade refresh ---------------------------------------------------------------


def test_a_facade_refresh_whose_window_saw_the_pair_deleted_writes_no_blob(migrated) -> None:
    h = migrated
    h.seed_profile()
    use_intruding_tokens(h, "fresh-tok", a_delete(h))

    resp = h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh")

    assert resp.status_code == 409, resp.text
    # INVARIANT (H-1, now at the first persistence): the delete removed the blob; the refresh
    # must not write the old credential's tokens back.
    assert blob_at_profile_address(h) is None


def test_a_reauth_in_flight_survives_an_ordinary_refresh(migrated) -> None:
    # INVARIANT (§5.3): refresh never advances, so a callback holding the generation its start
    # captured still completes after a refresh published in between.
    h = migrated
    h.seed_profile()
    started = start(h)
    assert started.status_code in (200, 201), started.text
    before = marker(h).generation
    use_tokens(h, "refreshed")
    assert h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh").status_code == 200
    assert marker(h).generation == before
    use_tokens(h, "reauthed")

    resp = callback(h, started.json()["state"])

    assert resp.status_code < 400, resp.text
    assert access_token_of(blob_at_profile_address(h)) == "reauthed"


# --- a strategy outside the app ---------------------------------------------------------------


def test_an_unbound_strategy_still_writes_its_refresh(legacy) -> None:
    # WHY: a strategy built outside the app's guarded sites (tooling, plugin tests) keeps today's
    # direct write; the guard is bound by the app, not imposed on the plugin.
    h = legacy
    name = credential_name_for(h.account_id, "tool")
    h.blobs.write(credential_service_for(name), "default", expired_blob())
    use_tokens(h, "direct")
    strategy = AnthropicOAuth(
        name,
        credential_store=h.blobs.store,
        http_client_factory=h.client.app.state.anthropic_http_factory,
    )

    h.call(strategy.refresh)

    assert access_token_of(h.blobs.read(credential_service_for(name), "default")) == "direct"


# --- the owner left its address during the window ---------------------------------------------


def test_a_legacy_refresh_whose_window_saw_the_profile_deleted_writes_no_blob(legacy) -> None:
    h = legacy
    h.seed_profile()
    use_intruding_tokens(h, "fresh-tok", a_delete(h))

    resp = h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "profile_conflict"
    assert blob_at_profile_address(h) is None
    assert document(h) is None


def test_a_native_refresh_whose_row_was_revoked_in_its_window_writes_nothing(legacy) -> None:
    # WHY no marker change: isolates the owner check — a revoked row has left its address even
    # when nothing claimed the pair.
    h = legacy
    connection_id = h.seed_connection(label="work")

    async def revoke() -> None:
        await OAuthConnection.filter(id=connection_id).update(status="revoked")

    use_intruding_tokens(h, "fresh-tok", revoke)

    resp = h.client.post(f"/v1/oauth/connections/{connection_id}/refresh")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "ctok"
    assert marker(h).generation == 0


def test_a_guarded_publication_refuses_a_capture_it_did_not_take(legacy) -> None:
    h = legacy
    guard = GuardedRefreshPublication(
        ConnectionRefreshOwner(h.account_id, PROVIDER, uuid4()), service="s", account="a"
    )

    async def write() -> None:
        raise AssertionError("must not write")

    with pytest.raises(TypeError):
        h.call(guard.publish, "a foreign capture", write)


# --- a marked pair: the path every pair takes once a G0 writer touched it ----------------------


def test_a_legacy_refresh_of_a_marked_pair_loses_to_a_key_replacement(legacy) -> None:
    # INVARIANT: on a marked pair the key replacement rewrites this blob, so its revision is the
    # fence — without it the refresh would write the old credential's tokens over the new key.
    h = legacy
    h.seed_profile()
    h.call(an_ownership_claim(h))
    use_intruding_tokens(h, "fresh-tok", a_key_replacement(h))

    resp = h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh")

    assert resp.status_code == 409, resp.text
    blob = blob_at_profile_address(h)
    assert blob is not None and json.loads(blob)["api_key"] == KEY
    assert marker(h).generation == 2


def test_a_dispatch_refresh_of_a_marked_pair_loses_to_a_key_replacement(legacy) -> None:
    h = legacy
    h.seed_profile()
    h.call(an_ownership_claim(h))
    h.blobs.write(profile_service(h), "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", a_key_replacement(h))

    with pytest.raises(WriteConflict):
        resolve_and_authorize(h)

    blob = blob_at_profile_address(h)
    assert blob is not None and json.loads(blob)["api_key"] == KEY


def test_a_token_refresh_of_a_revoked_non_effective_row_on_a_migrated_pair_writes_nothing(
    migrated,
) -> None:
    # WHY this shape: deleting a non-effective row of a migrated pair does not move the marker,
    # so the owner row lock is the only fence on the marked branch.
    h = migrated
    h.seed_profile()
    connection_id = h.seed_connection(label="work")
    h.blobs.write(connection_service(h, connection_id), "default", expired_blob())
    before = marker(h).generation

    async def revoke() -> None:
        await OAuthConnection.filter(id=connection_id).update(status="revoked")

    use_intruding_tokens(h, "fresh-tok", revoke)

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 409, resp.text
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "stale"
    assert marker(h).generation == before


# --- metadata publishes with the token, never from a pre-fetch snapshot ------------------------


def test_a_key_replacement_right_after_a_refresh_publication_is_not_reverted(
    legacy, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (§5.3): tokens and `last_refreshed_at` publish in one transaction; nothing after it
    # rewrites the document from the snapshot read before the fetch.
    h = legacy
    h.seed_profile()
    use_tokens(h, "fresh-tok")
    real_publish = GuardedRefreshPublication.publish

    async def publish_then_replace(self: Any, captured: object, write: Any) -> None:
        await real_publish(self, captured, write)
        await a_key_replacement(h)()

    monkeypatch.setattr(GuardedRefreshPublication, "publish", publish_then_replace)

    resp = h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh")

    assert resp.status_code == 200, resp.text
    doc = document(h)
    assert doc is not None and doc.auth_type == "api_key"
    blob = blob_at_profile_address(h)
    assert blob is not None and json.loads(blob)["api_key"] == KEY


def test_a_dispatch_refresh_stamps_the_profile_in_its_publication(legacy) -> None:
    h = legacy
    h.seed_profile()
    h.blobs.write(profile_service(h), "default", expired_blob())
    use_tokens(h, "fresh-tok")

    resolve_and_authorize(h)

    doc = document(h)
    assert doc is not None and doc.last_refreshed_at is not None
    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
