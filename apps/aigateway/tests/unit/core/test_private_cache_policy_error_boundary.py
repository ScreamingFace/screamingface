"""OME-1026 adversarial B1 — the private cache policy must cover the ERROR boundary too.

FEATURE: an unshareable private response, on every response the route can produce —
not only the ones the route class itself renders.

STORY: as an account owner behind a CDN, no response my request produces may be
replayed to another account: not the 200, not the 401 my missing token earns, not the
422 my malformed query earns, and not the 500 a bug in the gateway earns.

INVARIANT (defect 1 — the responses the route class cannot see): a route-class wrapper
observes what ``original(request)`` RETURNS and what it RAISES. A
``RequestValidationError`` and an unexpected exception are rendered LATER, by the
application's own exception handlers — the 500 by ``ServerErrorMiddleware``, which sits
OUTSIDE every user middleware and uses the original ``send``. Both were therefore
emitted with no cache directives at all. The policy has to be installed where the
final response is actually rendered, and the route class marks the request scope so
those handlers know the route was private.

INVARIANT (defect 2 — merge, never replace): ``headers.update()`` and
``MutableHeaders.__setitem__`` REPLACE every existing value of a key. A response that
already varied on ``Cookie``, or an ``HTTPException`` raised with
``Vary: Accept-Encoding``, silently lost that token — turning a correct cache key into
a WRONG one, which is worse than the missing policy: it invites a cache to share a
response the origin said varies. ``Vary`` is a set, so the policy adds to it and dedups
case-insensitively (HTTP field names are case-insensitive).

AIDEV-NOTE: deterministic header assertions. No upstream, no discovery, no timing.
"""

from __future__ import annotations

from ipaddress import IPv4Network
from typing import Annotated, Any, cast

import pytest
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.testclient import TestClient

from aigateway.core.auth.middleware import current_account
from aigateway.routes.private_cache import merge_vary, private_cache_route

_PROFILE_URL = "/v1/auth/anthropic/profiles/work/models"
_PARAMS_URL = "/v1/model-parameters"
_PROBE_PREFIX = "/v1/test-private-probe"
_IDENTITY_EMAIL = "boundary-probe@openmined.org"

# The identity/profile inputs the policy must ALWAYS name. Lower-cased because HTTP
# field names are case-insensitive and the assertions compare token sets.
_PROFILE_TOKENS = ("authorization", "x-user-email")
_PARAM_TOKENS = ("authorization", "x-user-email", "x-profile")


def _vary_tokens(response: Any) -> set[str]:
    raw = response.headers.get("vary") or ""
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


def _assert_policy(response: Any, expected: tuple[str, ...]) -> None:
    assert response.headers.get("cache-control") == "private, no-store", (
        response.status_code,
        dict(response.headers),
    )
    tokens = _vary_tokens(response)
    assert set(expected) <= tokens, (response.status_code, tokens, dict(response.headers))


def _header_mode(client: TestClient) -> dict[str, str]:
    """Switch the live app to ``cloudflare_headers`` identity; return the identity.

    # WHY mutate live settings: ``current_account`` reads ``request.app.state.settings``
    # on every request, so this drives the real production branch rather than a second
    # app. An unknown ``X-User-Email`` is JIT-provisioned, so one call authenticates.
    """
    settings = cast(FastAPI, client.app).state.settings
    settings.auth_mode = "cloudflare_headers"
    settings.allowed_networks = (IPv4Network("10.0.0.0/8"),)
    return {"X-User-Email": _IDENTITY_EMAIL}


def _error_probe_client(client: TestClient) -> TestClient:
    """The same app, same event loop, but observing 500s instead of re-raising them.

    # AIDEV-NOTE: ``portal`` is reused deliberately. A second TestClient would other-
    # wise start its OWN blocking portal per request, and a DB read issued from that
    # loop against the app's SQLite connection blocks on the writer lock — the test
    # would hang forever instead of failing. Borrowing the app's portal keeps every
    # request on the loop that owns the connection.
    # WHY a second client at all: ``ServerErrorMiddleware`` re-raises after sending, so
    # ``raise_server_exceptions=True`` (the default, correct for every other test) makes
    # the rendered 500 unobservable.
    """
    probe = TestClient(
        cast(FastAPI, client.app), client=("10.1.2.3", 50000), raise_server_exceptions=False
    )
    probe.portal = client.portal
    probe.headers.update(client.headers)
    return probe


# ── 422: rendered by the app's validation handler, not by the route class ──────


def test_a_missing_required_query_parameter_is_422_with_the_policy(
    authenticated_client: TestClient,
) -> None:
    """``/v1/model-parameters`` with no ``model``: a real framework-generated 422."""
    response = authenticated_client.get(_PARAMS_URL)

    assert response.status_code == 422, response.text
    _assert_policy(response, _PARAM_TOKENS)


def test_the_422_policy_holds_in_cloudflare_header_identity_mode(
    client: TestClient,
) -> None:
    """The same 422, reached with no ``Authorization`` header in the request at all.

    # WHY both modes: in header mode two accounts send byte-identical request lines,
    # so ``X-User-Email`` is the ONLY thing separating their responses. A 422 that
    # named only ``Authorization`` would leave them interchangeable to a shared cache.
    """
    identity = _header_mode(client)

    response = client.get(_PARAMS_URL, headers=identity)

    assert response.status_code == 422, response.text
    _assert_policy(response, _PARAM_TOKENS)


def test_a_dependency_raised_validation_failure_carries_the_policy(
    authenticated_client: TestClient,
) -> None:
    """A 422 produced while SOLVING a dependency, on the listing route.

    The listing route validates nothing of its own, so its only reachable
    ``RequestValidationError`` comes from a dependency. This overrides the identity
    dependency with one that requires a header, which is how FastAPI reports a missing
    dependency input: a real validation error raised before the endpoint body runs.
    """
    app = cast(FastAPI, authenticated_client.app)

    async def _needs_a_header(x_probe_required: Annotated[str, Header()]) -> Any:
        raise AssertionError("unreachable: the header is required and absent")

    app.dependency_overrides[current_account] = _needs_a_header
    try:
        response = authenticated_client.get(_PROFILE_URL)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text
    _assert_policy(response, _PROFILE_TOKENS)


# ── 500: rendered OUTSIDE every user middleware ───────────────────────────────


def test_an_unexpected_exception_is_a_sanitized_500_that_carries_the_policy(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gateway bug on a private route still must not produce a shareable response."""
    app = cast(FastAPI, authenticated_client.app)
    secret = "sk-ant-must-never-reach-a-response-body"

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"index exploded with {secret}")

    monkeypatch.setattr(app.state.profile_index, "get_with_credential_generation", _boom)
    probe = _error_probe_client(authenticated_client)

    response = probe.get(_PROFILE_URL)

    assert response.status_code == 500, response.text
    # INVARIANT: the generic body is preserved exactly — this boundary adds headers, it
    # does not become a second, chattier error renderer.
    assert response.text == "Internal Server Error", response.text
    assert secret not in response.text
    _assert_policy(response, _PROFILE_TOKENS)


def test_the_500_policy_holds_in_cloudflare_header_identity_mode(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same 500, in the identity mode where the URL alone identifies nothing."""
    app = cast(FastAPI, client.app)
    identity = _header_mode(client)

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("index exploded")

    monkeypatch.setattr(app.state.profile_index, "get_with_credential_generation", _boom)
    probe = _error_probe_client(client)

    response = probe.get(_PROFILE_URL, headers=identity)

    assert response.status_code == 500, response.text
    _assert_policy(response, _PROFILE_TOKENS)


def test_an_unexpected_exception_on_a_PUBLIC_route_gains_no_private_policy(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boundary is PATH-AWARE: it must not label every 500 in the app private.

    # WHY this matters: a blanket ``private, no-store`` on all errors would be a
    # different (and unrequested) product decision, and it would hide the fact that the
    # private routes are the ones with an identity-dependent body.
    """
    app = cast(FastAPI, authenticated_client.app)

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(app.state.providers, "all", _boom)
    probe = _error_probe_client(authenticated_client)

    response = probe.get("/v1/providers")

    assert response.status_code == 500, response.text
    assert response.headers.get("cache-control") is None, dict(response.headers)


# ── Vary is a SET: existing tokens survive ────────────────────────────────────


def _install_probe_routes(app: FastAPI) -> None:
    """Routes that already carry a ``Vary`` when the policy is applied.

    # WHY test-local routes: the merge only matters when something else has ALREADY
    # varied the response, and no production endpoint does that today. These use the
    # PRODUCTION route class (``private_cache_route``) and the production app, so what
    # they exercise is the real boundary — the probes that found this defect reached it
    # through exactly such a response.
    """
    router = APIRouter(route_class=private_cache_route("X-Profile"))

    @router.get(f"{_PROBE_PREFIX}/vary-cookie")
    async def _vary_cookie(response: Response) -> dict:
        # A session-dependent body: the response genuinely varies on Cookie, and the
        # cache MUST keep honouring that after the private policy is added.
        response.headers["Vary"] = "Cookie"
        return {"ok": True}

    @router.get(f"{_PROBE_PREFIX}/vary-duplicated")
    async def _vary_duplicated(response: Response) -> dict:
        response.headers["Vary"] = "cookie, AUTHORIZATION"
        return {"ok": True}

    @router.get(f"{_PROBE_PREFIX}/raises-with-vary")
    async def _raises_with_vary() -> dict:
        raise HTTPException(
            status_code=409,
            detail={"code": "probe_conflict"},
            headers={"Vary": "Accept-Encoding", "Retry-After": "7"},
        )

    @router.get(f"{_PROBE_PREFIX}/needs-a-query")
    async def _needs_a_query(required: str, _dep: Annotated[None, Depends(lambda: None)]) -> dict:
        return {"required": required}

    app.include_router(router)


def test_an_existing_vary_token_survives_on_a_success(
    authenticated_client: TestClient,
) -> None:
    """``Vary: Cookie`` set by the response must not be replaced by the policy."""
    _install_probe_routes(cast(FastAPI, authenticated_client.app))

    response = authenticated_client.get(f"{_PROBE_PREFIX}/vary-cookie")

    assert response.status_code == 200, response.text
    tokens = _vary_tokens(response)
    assert "cookie" in tokens, dict(response.headers)
    _assert_policy(response, _PARAM_TOKENS)


def test_an_existing_vary_token_survives_on_an_httpexception(
    authenticated_client: TestClient,
) -> None:
    """``Vary: Accept-Encoding`` on the RAISED exception must survive too.

    A raiser's unrelated headers (``Retry-After``) survive as well: the policy owns the
    keys it names and nothing else.
    """
    _install_probe_routes(cast(FastAPI, authenticated_client.app))

    response = authenticated_client.get(f"{_PROBE_PREFIX}/raises-with-vary")

    assert response.status_code == 409, response.text
    tokens = _vary_tokens(response)
    assert "accept-encoding" in tokens, dict(response.headers)
    assert response.headers.get("retry-after") == "7", dict(response.headers)
    _assert_policy(response, _PARAM_TOKENS)


def test_a_token_the_policy_also_names_is_not_listed_twice(
    authenticated_client: TestClient,
) -> None:
    """Dedup is case-insensitive: ``AUTHORIZATION`` and ``Authorization`` are one token."""
    _install_probe_routes(cast(FastAPI, authenticated_client.app))

    response = authenticated_client.get(f"{_PROBE_PREFIX}/vary-duplicated")

    assert response.status_code == 200, response.text
    raw = [token.strip().lower() for token in response.headers["vary"].split(",")]
    assert len(raw) == len(set(raw)), raw
    assert "cookie" in raw
    _assert_policy(response, _PARAM_TOKENS)


def test_a_422_on_a_route_whose_vary_is_extended_keeps_both(
    authenticated_client: TestClient,
) -> None:
    """The scope marker carries the route's OWN vary tokens, not a global constant."""
    _install_probe_routes(cast(FastAPI, authenticated_client.app))

    response = authenticated_client.get(f"{_PROBE_PREFIX}/needs-a-query")

    assert response.status_code == 422, response.text
    _assert_policy(response, _PARAM_TOKENS)


# ── the merge rule itself ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        (None, "Authorization, X-User-Email"),
        ("", "Authorization, X-User-Email"),
        ("Cookie", "Cookie, Authorization, X-User-Email"),
        ("cookie, AUTHORIZATION", "cookie, AUTHORIZATION, X-User-Email"),
        ("Authorization,X-User-Email", "Authorization, X-User-Email"),
        ("Accept-Encoding, Cookie", "Accept-Encoding, Cookie, Authorization, X-User-Email"),
    ],
)
def test_merge_vary_is_an_order_preserving_case_insensitive_union(
    existing: str | None, expected: str
) -> None:
    """Existing tokens keep their spelling and position; the policy appends what is new.

    # WHY preserve the incoming spelling: the merge must be a pure addition, so a
    # response that already declared a token comes out byte-identical in that token.
    # INVARIANT: idempotent — merging the result again changes nothing.
    """
    tokens = ("Authorization", "X-User-Email")

    merged = merge_vary(existing, tokens)

    assert merged == expected
    assert merge_vary(merged, tokens) == merged


def test_the_app_renders_unexpected_errors_through_its_own_handler(
    client: TestClient,
) -> None:
    """Structural: without a registered ``Exception`` handler the 500 is unreachable.

    # WHY assert the wiring: Starlette renders an unhandled exception in
    # ``ServerErrorMiddleware``, which is installed OUTSIDE every user middleware and
    # writes with the original ``send``. No middleware this app can add will ever see
    # that response, so registering the handler is not a style choice — it is the only
    # way the application observes its own 500 at all.
    """
    app = cast(FastAPI, client.app)

    assert Exception in app.exception_handlers, sorted(map(str, app.exception_handlers))
