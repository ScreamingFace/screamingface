"""Every re-auth pointer names a live Connection route (OME-1209 Stage E, spec R2).

# FEATURE: Stage E "successor pointers" — a refusal for an unusable stored credential sends the
# caller to the Connection API, never to a Profile route that Stage E retires.
# INVARIANT: each URL `reauth_url_for` can produce matches a route the Connection router serves,
# with the method a caller uses to fix the credential, so retiring a route cannot strand a pointer.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.routing import APIRoute

from aigateway.core.provider_access import reauth_url_for
from aigateway.routes import oauth_connections


@pytest.mark.parametrize(
    ("auth_type", "connection_id", "expected"),
    [
        (None, None, "/v1/oauth/connections"),
        ("oauth", None, "/v1/oauth/connections"),
        ("oauth", "c-1", "/v1/oauth/connections"),
        ("api_key", None, "/v1/oauth/connections/api-key"),
        ("api_key", "c-1", "/v1/oauth/connections/c-1/api-key"),
    ],
)
def test_the_pointer_names_the_connection_successor(
    auth_type: str | None, connection_id: str | None, expected: str
) -> None:
    url = reauth_url_for(cast(Any, auth_type), connection_id=connection_id)

    assert url == expected
    assert "/profiles" not in url


@pytest.mark.parametrize(
    ("auth_type", "connection_id", "method"),
    [
        (None, None, "POST"),
        ("oauth", None, "POST"),
        ("api_key", None, "POST"),
        ("api_key", "3f1c2a4e-0000-4000-8000-000000000001", "PUT"),
    ],
)
def test_every_pointer_resolves_to_a_live_connection_route(
    auth_type: str | None, connection_id: str | None, method: str
) -> None:
    url = reauth_url_for(cast(Any, auth_type), connection_id=connection_id)

    served = [
        route
        for route in oauth_connections.router.routes
        if isinstance(route, APIRoute)
        and route.path_regex.match(url)
        and method in (route.methods or set())
    ]
    assert served, f"{method} {url} is served by no Connection route"
