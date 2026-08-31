"""OME-1026 final pass F1 — the cache policy must outrank authentication.

FEATURE: an unshareable private response. Both endpoints whose bodies are scoped to
one account — the private model listing and the profile-bound detailed contract —
must be uncacheable by any intermediary on EVERY response they can emit.

STORY: as an account owner behind a CDN or service mesh, no response my request
produces can be replayed to another account — including the responses I get when my
token is missing, expired, or refused.

INVARIANT (the defect this closes): the policy was applied INSIDE the endpoint
function, so it covered only the exits the endpoint reaches. ``CurrentAccount`` is a
FastAPI dependency, and a dependency that raises does so while the framework is
SOLVING dependencies — before the endpoint body runs at all. Every 401/403 from
``current_account`` was therefore emitted with no cache directives whatsoever, and a
401 body is exactly what a shared cache is most likely to key on the URL alone.

INVARIANT (both identity modes): ``jwt`` mode identifies the caller by
``Authorization``; ``cloudflare_headers`` mode by ``X-User-Email``. A pre-handler
refusal in header mode is reachable without any ``Authorization`` at all, so a
``Vary`` naming only ``Authorization`` would leave those refusals interchangeable.

AIDEV-NOTE: these are DETERMINISTIC header assertions — no upstream, no discovery, no
timing. If one fails, the boundary moved.
"""

from __future__ import annotations

from ipaddress import IPv4Network
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.auth.jwt import encode_token
from aigateway.core.auth.models import Account
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    AuthType,
    Profile,
    ProfileState,
    profile_id_for,
)

_MODEL = "anthropic/claude-opus-4-8"
_PROFILE_URL = "/v1/auth/anthropic/profiles/work/models"
_PARAMS_URL = "/v1/model-parameters"
_DEACTIVATED_EMAIL = "locked-out@openmined.org"

# Each private route, the query it needs to MATCH, and the identity inputs its
# ``Vary`` must name. Matching matters: an unmatched path never reaches the route at
# all, so a test that forgot the query would assert nothing about this boundary.
_ROUTES = (
    pytest.param(_PROFILE_URL, {}, ("Authorization", "X-User-Email"), id="profile-models"),
    pytest.param(
        _PARAMS_URL,
        {"model": _MODEL},
        ("Authorization", "X-User-Email", "X-Profile"),
        id="model-parameters",
    ),
)


def _assert_private_policy(response: Any, vary_tokens: tuple[str, ...]) -> None:
    assert response.headers.get("cache-control") == "private, no-store", (
        response.status_code,
        dict(response.headers),
    )
    vary = response.headers.get("vary") or ""
    for token in vary_tokens:
        assert token in vary, (token, response.status_code, dict(response.headers))


def _header_mode(client: TestClient, *, trusted_peer: bool = True) -> None:
    """Switch the running app to ``cloudflare_headers`` identity.

    # WHY mutating live settings is legitimate here: ``current_account`` reads
    # ``request.app.state.settings`` on EVERY request, so this exercises the real
    # production branch rather than a second app built for the test.
    """
    settings = cast(FastAPI, client.app).state.settings
    settings.auth_mode = "cloudflare_headers"
    if not trusted_peer:
        # The suite's peer is 10.1.2.3; trust a range that cannot contain it.
        settings.allowed_networks = (IPv4Network("192.168.5.0/24"),)


# ── jwt mode: every way ``_account_from_bearer_token`` refuses ─────────────────


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_a_missing_bearer_token_is_refused_with_the_policy(
    client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    response = client.get(url, params=params)

    assert response.status_code == 401, response.text
    _assert_private_policy(response, vary)


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_a_malformed_token_is_refused_with_the_policy(
    client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    response = client.get(url, params=params, headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401, response.text
    _assert_private_policy(response, vary)


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_an_expired_token_is_refused_with_the_policy(
    client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    token, _ = encode_token(
        account_id=str(uuid4()),
        username="admin",
        secret=cast(FastAPI, client.app).state.jwt_secret,
        ttl_seconds=-10,
    )

    response = client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401, response.text
    _assert_private_policy(response, vary)


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_a_well_formed_token_for_no_such_account_is_refused_with_the_policy(
    client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    """Signed by this gateway, decodes cleanly, names an account that does not exist.

    # WHY it is worth its own case: this refusal happens AFTER a database read, the
    # deepest pre-handler exit, and it is the one an attacker can reach with a stolen
    # signing key rather than a stolen token.
    """
    token, _ = encode_token(
        account_id=str(uuid4()),
        username="ghost",
        secret=cast(FastAPI, client.app).state.jwt_secret,
        ttl_seconds=300,
    )

    response = client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401, response.text
    _assert_private_policy(response, vary)


# ── cloudflare_headers mode: identity comes from a header, not a token ─────────


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_an_untrusted_peer_is_refused_with_the_policy(
    client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    """403, and still uncacheable. The peer check runs before the identity is read."""
    _header_mode(client, trusted_peer=False)

    response = client.get(url, params=params, headers={"X-User-Email": "a@openmined.org"})

    assert response.status_code == 403, response.text
    _assert_private_policy(response, vary)


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_a_missing_identity_header_is_refused_with_the_policy(
    client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    """The mode's own 401 — reachable with NO ``Authorization`` header in the request.

    # WHY this case names the ``Vary`` requirement: two different accounts produce
    # byte-identical request lines here. Only ``X-User-Email`` distinguishes them, so a
    # ``Vary`` that omitted it would let a shared cache reuse one caller's refusal —
    # and, on the success path at the same URL, one caller's catalog.
    """
    _header_mode(client)

    response = client.get(url, params=params)

    assert response.status_code == 401, response.text
    _assert_private_policy(response, vary)


def _deactivate(client: TestClient, username: str) -> None:
    """Disable an account THROUGH THE APP'S OWN EVENT LOOP.

    # AIDEV-NOTE: this must not be a plain ``await`` in an async test. The app holds its
    # Tortoise connection on the TestClient's loop; a write issued from pytest's loop
    # against the same SQLite file blocks on the writer lock and the test hangs
    # forever rather than failing. The blocking portal is the app's loop, so the update
    # shares its connection.
    """
    portal = client.portal
    assert portal is not None

    async def _update() -> int:
        return await Account.filter(username=username).update(is_active=False)

    assert portal.call(_update) == 1, "the identity must have been provisioned already"


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_a_deactivated_identity_is_refused_with_the_policy(
    client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    """The rejected-identity 401, reached the only way production can reach it.

    # AIDEV-NOTE: an UNKNOWN ``X-User-Email`` is not a rejection — the mesh has already
    # verified it, so ``account_for_identity`` get-or-CREATEs the account (JIT
    # provisioning). The 401 belongs to an account that exists and was DEACTIVATED, so
    # this case provisions first and then disables the row, exactly as an operator
    # locking someone out would.
    """
    _header_mode(client)
    identity = {"X-User-Email": _DEACTIVATED_EMAIL}
    provisioned = client.get(url, params=params, headers=identity)
    assert provisioned.status_code != 401, provisioned.text
    _deactivate(client, _DEACTIVATED_EMAIL)

    response = client.get(url, params=params, headers=identity)

    assert response.status_code == 401, response.text
    _assert_private_policy(response, vary)


# ── the exits the endpoint DOES reach must not have regressed ─────────────────


@pytest.mark.parametrize(("url", "params", "vary"), _ROUTES)
def test_a_handler_raised_refusal_still_carries_the_policy(
    authenticated_client: TestClient, url: str, params: dict[str, str], vary: tuple[str, ...]
) -> None:
    """An authenticated caller asking for something that does not exist.

    Profile route: no such profile → 404. Contract route: unknown model → 400.
    """
    query = dict(params)
    if "model" in query:
        query["model"] = "anthropic/no-such-model-at-all"

    response = authenticated_client.get(url, params=query)

    assert response.status_code in {400, 404}, response.text
    _assert_private_policy(response, vary)


@pytest.mark.asyncio
async def test_the_kill_switch_fallback_carries_the_policy(
    credential_blobs: Any, authenticated_client: TestClient
) -> None:
    """Discovery off is a 200 with seeds — an authenticated SUCCESS, still private."""
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "work"),
            account_id=account_id,
            provider="anthropic",
            name="work",
            state=ProfileState.AUTHENTICATED,
            auth_type=cast(AuthType, "api_key"),
        )
    )
    app = cast(FastAPI, authenticated_client.app)
    app.state.profile_model_catalog = None

    response = authenticated_client.get(_PROFILE_URL)

    assert response.status_code == 200, response.text
    assert response.json()["reason"] == "discovery_disabled", response.json()
    _assert_private_policy(response, ("Authorization", "X-User-Email"))


# ── the boundary itself, not just its symptoms ────────────────────────────────


def test_the_policy_is_installed_where_it_wraps_dependency_resolution() -> None:
    """Structural: the policy is a ROUTE CLASS, so it cannot be bypassed by a raise.

    # WHY assert the wiring and not only the headers: the header cases above pass for
    # today's set of pre-handler failures. A new dependency added to either route —
    # a rate limiter, an entitlement check — introduces a new pre-handler raise that
    # no existing case covers. Pinning the boundary makes the guarantee hold for
    # exits nobody has written yet.
    """
    from aigateway.routes import model_parameters, profile_models
    from aigateway.routes.private_cache import PrivateCacheRoute

    for router in (profile_models.router, model_parameters.router):
        assert issubclass(router.route_class, PrivateCacheRoute), router.route_class
        assert router.routes, "an empty router would make the assertion above vacuous"
        for route in router.routes:
            assert isinstance(route, PrivateCacheRoute), route
