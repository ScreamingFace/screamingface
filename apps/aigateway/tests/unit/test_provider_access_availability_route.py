"""`GET /v1/provider-access` — the caller-scoped availability listing (OME-1244, Stage A4).

# FEATURE: the backing-neutral successor to aggregating `GET /v1/auth/profiles` client-side,
# so the Hosted Engine (OME-1245) reads one caller-scoped listing that names no Profile.
# INVARIANT (D17, spec §3.3 op 6): rows carry `provider` and `status` ONLY, the status family is
# `AvailabilityStatus`, every success is `Cache-Control: private, no-store`, inbound `X-Profile`
# is non-selecting, and the route delegates to `app.state.provider_access.availability` — no
# secret read, no credential strategy, no write.
# INVARIANT (edge): an internal status outside the public family never reaches the wire.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any, cast, get_args

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import aigateway.main as main_module
from aigateway.core.profile_index import INDEX_CREDENTIAL_SERVICE, ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileDefaults, ProfileState, profile_id_for
from aigateway.core.provider_access import AvailabilityRow, AvailabilityStatus
from aigateway.core.provider_access import profile_authorize as authorize_module

ROUTE = "/v1/provider-access"
STATUSES: frozenset[str] = frozenset(get_args(AvailabilityStatus))
ROW_KEYS = frozenset({"provider", "status"})
PRIVATE = "private, no-store"


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


class _Edge:
    """The HTTP edge of the availability listing for one signed-in caller."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.app = _app(client)
        self.account_id: str = client.get("/v1/auth/me").json()["id"]
        self.index: ProfileIndexStore = self.app.state.profile_index
        self.registered: set[str] = {
            plugin.custom_llm_provider for plugin in self.app.state.providers.all()
        }

    def call(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        portal = self.client.portal
        assert portal is not None
        return portal.call(partial(fn, *args, **kwargs))

    def seed(self, provider: str, state: str, name: str, **fields: Any) -> Profile:
        profile = Profile(
            id=profile_id_for(self.account_id, provider, name),
            account_id=self.account_id,
            provider=provider,
            name=name,
            state=ProfileState(state),
            **fields,
        )
        self.call(self.index.upsert, profile)
        return profile

    def get(self, headers: dict[str, str] | None = None) -> Any:
        response = self.client.get(ROUTE, headers=headers)
        if response.status_code == 200:
            # INVARIANT: every success is per-caller and unstorable; `Vary` never names the
            # non-selecting `X-Profile`.
            assert response.headers["cache-control"] == PRIVATE
            assert "x-profile" not in response.headers.get("vary", "").lower()
        return response

    def statuses(self, body: dict[str, Any]) -> dict[str, str]:
        return {row["provider"]: row["status"] for row in body["providers"]}


class _RecordingPort:
    """A stand-in for `app.state.provider_access` that records the delegation."""

    def __init__(self, rows: tuple[AvailabilityRow, ...]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    async def availability(self, account_id: str) -> tuple[AvailabilityRow, ...]:
        self.calls.append(account_id)
        return self.rows


@pytest.fixture
def edge(authenticated_client: TestClient, credential_blobs) -> _Edge:
    return _Edge(authenticated_client)


# --- the contract: provider + status only, caller-scoped, private -------------------------


def test_route_refuses_an_anonymous_caller(client: TestClient) -> None:
    assert client.get(ROUTE).status_code == 401


def test_rows_carry_provider_and_status_only_from_the_closed_family(edge: _Edge) -> None:
    edge.seed("anthropic", "authenticated", "a")
    edge.seed("anthropic", "error", "b")
    edge.seed("gemini", "pending", "c")
    edge.seed("codex", "error", "d")

    response = edge.get()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"providers"}
    assert all(set(row) == ROW_KEYS for row in body["providers"])
    assert {row["status"] for row in body["providers"]} <= STATUSES
    assert [row["provider"] for row in body["providers"]] == sorted(edge.registered | {"gemini"})
    statuses = edge.statuses(body)
    assert statuses["anthropic"] == "connected"
    assert statuses["gemini"] == "pending"
    assert statuses["codex"] == "error"
    assert all(statuses[p] == "not_connected" for p in edge.registered - {"anthropic", "codex"})
    # STORY: as the Hosted Engine, I never see `needs_reauth` while Profiles back the listing.
    assert "needs_reauth" not in statuses.values()


def test_listing_is_scoped_to_the_caller(
    edge: _Edge, client: TestClient, provisioned_user_factory
) -> None:
    edge.seed("anthropic", "authenticated", "mine")
    provisioned_user_factory("bob")
    login = client.post(
        "/v1/auth/login", json={"username": "bob", "password": "test-user-password"}
    )
    assert login.status_code == 200, login.text

    mine = edge.get().json()
    theirs = edge.get(headers={"Authorization": f"Bearer {login.json()['token']}"}).json()

    assert edge.statuses(mine)["anthropic"] == "connected"
    # STORY: as a caller with nothing connected, I still see every registered provider, all
    # `not_connected` — the Engine's "none" case, never an empty list.
    assert set(edge.statuses(theirs)) == edge.registered
    assert set(edge.statuses(theirs).values()) == {"not_connected"}
    assert mine != theirs


@pytest.mark.parametrize("selector", ["default", "broken", "no-such-profile", ""])
def test_inbound_x_profile_is_non_selecting(edge: _Edge, selector: str) -> None:
    edge.seed("anthropic", "authenticated", "good")
    edge.seed("anthropic", "error", "broken")
    baseline = edge.get()

    selected = edge.get(headers={"X-Profile": selector})

    assert baseline.status_code == selected.status_code == 200
    assert selected.json() == baseline.json()
    assert edge.statuses(selected.json())["anthropic"] == "connected"


def test_local_auth_disabled_serves_the_shared_anonymous_principal(client: TestClient) -> None:
    _app(client).state.settings.auth_mode = "disabled"

    response = client.get(ROUTE)

    assert response.status_code == 200
    assert response.headers["cache-control"] == PRIVATE
    assert {row["status"] for row in response.json()["providers"]} == {"not_connected"}


# --- delegation: the port answers, the edge adds no policy and touches no secret -----------


def test_route_delegates_to_the_wired_port_verbatim(edge: _Edge, monkeypatch) -> None:
    port = _RecordingPort(
        (AvailabilityRow("zeta", "connected"), AvailabilityRow("alpha", "needs_reauth"))
    )
    monkeypatch.setattr(edge.app.state, "provider_access", port)

    body = edge.get().json()

    # INVARIANT (review F2): whatever `app.state.provider_access` holds IS the port — the route
    # neither re-sorts nor filters its rows, and asks once, for the caller only.
    assert port.calls == [edge.account_id]
    assert body == {
        "providers": [
            {"provider": "zeta", "status": "connected"},
            {"provider": "alpha", "status": "needs_reauth"},
        ]
    }


def test_route_reads_only_the_index_builds_no_strategy_and_writes_nothing(
    edge: _Edge, monkeypatch
) -> None:
    edge.seed("anthropic", "authenticated", "a", auth_type="api_key")
    edge.seed("codex", "authenticated", "b")
    store = edge.app.state.credential_store
    real_read = store.read
    services_read: list[str] = []

    async def _spy_read(service: str, account: str) -> str | None:
        services_read.append(service)
        return await real_read(service, account)

    def _no_strategy(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the availability route must not build a credential strategy")

    async def _no_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the availability route must not write")

    monkeypatch.setattr(store, "read", _spy_read)
    monkeypatch.setattr(authorize_module, "credential_strategy_from", _no_strategy)
    for name in ("write", "mutate", "delete"):
        monkeypatch.setattr(store, name, _no_write)
    for name in (
        "upsert",
        "remove",
        "mark_authenticated_error",
        "mark_pending_error",
        "update_metadata",
    ):
        monkeypatch.setattr(edge.index, name, _no_write)

    statuses = edge.statuses(edge.get().json())

    assert statuses["anthropic"] == statuses["codex"] == "connected"
    assert services_read and set(services_read) == {INDEX_CREDENTIAL_SERVICE}


def test_body_carries_no_name_id_label_default_auth_method_or_locator(edge: _Edge) -> None:
    oauth = edge.seed(
        "anthropic",
        "authenticated",
        "work-oauth",
        account_label="alice@example.com",
        scopes=["user:inference"],
        defaults=ProfileDefaults(
            model="anthropic/claude-x", system_prompt="be terse", max_tokens=99
        ),
    )
    key = edge.seed(
        "openai",
        "authenticated",
        "team-key",
        auth_type="api_key",
        defaults=ProfileDefaults(model="openai/gpt-x", temperature=0.25),
    )
    broken = edge.seed("codex", "error", "broken-oauth")

    body = edge.get().json()

    # Structural: the only keys are the three the contract names, and the only leaf values are
    # provider names and statuses — so no id, name, label, default, auth method or URL can hide.
    assert set(body) == {"providers"}
    assert all(set(row) == ROW_KEYS for row in body["providers"])
    leaves = {value for row in body["providers"] for value in row.values()}
    assert all(isinstance(leaf, str) for leaf in leaves)
    assert leaves <= edge.registered | STATUSES
    # Explicit: none of the seeded identifying values leaks in any form.
    text = json.dumps(body)
    for forbidden in (
        edge.account_id,
        oauth.id,
        oauth.name,
        "alice@example.com",
        "user:inference",
        "claude-x",
        "be terse",
        "99",
        key.id,
        key.name,
        "api_key",
        "gpt-x",
        "0.25",
        broken.id,
        broken.name,
        "/v1/auth/",
        "reauth_url",
    ):
        assert forbidden not in text, forbidden


# --- the edge fails closed on a status outside the public family --------------------------


def test_unknown_internal_status_fails_closed_without_leaking_it(
    client: TestClient, monkeypatch
) -> None:
    app = _app(client)
    app.state.settings.auth_mode = "disabled"
    bogus = cast(AvailabilityStatus, "totally-bogus")
    monkeypatch.setattr(
        app.state, "provider_access", _RecordingPort((AvailabilityRow("anthropic", bogus),))
    )
    # WHY a second client: the fixture's client re-raises server exceptions into the test; this
    # one renders them, so the assertion is on what a caller would actually receive.
    edge = TestClient(app, raise_server_exceptions=False)

    response = edge.get(ROUTE)

    assert response.status_code == 500
    assert "totally-bogus" not in response.text
    assert "providers" not in response.text


# --- OpenAPI: exactly one new operation, nothing else moves --------------------------------


def test_openapi_publishes_exactly_one_new_operation(edge: _Edge, monkeypatch) -> None:
    published = edge.app.openapi()

    assert set(published["paths"][ROUTE]) == {"get"}
    operation = published["paths"][ROUTE]["get"]
    # Nothing selects on the way in: no parameters, so no 422 either.
    assert "parameters" not in operation
    assert set(operation["responses"]) == {"200"}
    listing_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    listing_name = listing_ref.rsplit("/", 1)[1]
    listing = published["components"]["schemas"][listing_name]
    assert set(listing["properties"]) == {"providers"} and listing["additionalProperties"] is False
    row_name = listing["properties"]["providers"]["items"]["$ref"].rsplit("/", 1)[1]
    row = published["components"]["schemas"][row_name]
    assert set(row["properties"]) == ROW_KEYS and set(row["required"]) == ROW_KEYS
    assert row["additionalProperties"] is False
    assert set(row["properties"]["status"]["enum"]) == STATUSES

    # Everything else is untouched: the real factory, with this one router emptied, publishes
    # the same document minus the new path and the two schemas only it references.
    monkeypatch.setattr(main_module.provider_access_availability, "router", APIRouter())
    without = main_module.create_app()
    reduced = json.loads(json.dumps(published))
    del reduced["paths"][ROUTE]
    del reduced["components"]["schemas"][listing_name]
    del reduced["components"]["schemas"][row_name]
    assert reduced == without.openapi()
