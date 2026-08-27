"""Browser clients are first-class callers (spec §2.1), so the preflight has to succeed.

A JSON body with an `Idempotency-Key` is a preflighted request in every browser, so a portal that
cannot preflight cannot file a report at all — and the failure surfaces as an opaque CORS error
rather than as anything in this service's logs.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from report_intake.config import Settings
from report_intake.identity.turnstile import TURNSTILE_RESPONSE_HEADER
from report_intake.main import create_app

from .test_report_schema import a_report

_ORIGIN = "https://portal.example.test"


@pytest.fixture
def browser_client(database_url: str) -> Generator[TestClient, None, None]:
    app = create_app(
        Settings.model_validate({"database_url": database_url, "cors_origins": _ORIGIN})
    )
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client


def _preflight(client: TestClient, origin: str, headers: str) -> Any:
    return client.options(
        "/v1/reports",
        headers={
            "origin": origin,
            "access-control-request-method": "POST",
            "access-control-request-headers": headers,
        },
    )


def test_a_preflight_from_an_allowed_origin_admits_the_headers_a_report_needs(
    browser_client: TestClient,
) -> None:
    response = _preflight(
        browser_client, _ORIGIN, f"content-type, idempotency-key, {TURNSTILE_RESPONSE_HEADER}"
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ORIGIN


def test_an_anonymous_browser_may_send_its_bot_token(browser_client: TestClient) -> None:
    """The Turnstile header is the one a browser client cannot do without: it is the only way an
    anonymous caller clears the gate, and an unlisted request header fails the preflight."""
    response = _preflight(browser_client, _ORIGIN, TURNSTILE_RESPONSE_HEADER)

    assert response.status_code == 200


def test_an_unlisted_origin_is_not_given_permission(browser_client: TestClient) -> None:
    response = _preflight(browser_client, "https://elsewhere.example.test", "content-type")

    assert "access-control-allow-origin" not in response.headers


def test_credentials_are_never_allowed(browser_client: TestClient) -> None:
    """This endpoint authenticates on a header the mesh injects, never on a cookie. Allowing
    credentials would hand browsers an ambient authority nothing here uses — and it is what makes
    a cross-site POST able to file a report as whoever is logged in."""
    response = browser_client.post(
        "/v1/reports",
        json=a_report(),
        headers={"content-type": "application/json", "origin": _ORIGIN},
    )

    assert response.status_code == 202
    assert "access-control-allow-credentials" not in response.headers


def test_a_refusal_still_carries_the_allow_origin_header(browser_client: TestClient) -> None:
    """CORS is outermost for this reason: without the header the browser reports a CORS failure
    and the client never sees the status that told it what to do — which is the whole point of
    spec §2.3's table."""
    response = browser_client.post(
        "/v1/reports", content=b"{}", headers={"content-type": "text/plain", "origin": _ORIGIN}
    )

    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == _ORIGIN


def test_configuring_no_origins_leaves_the_service_without_a_cors_policy(
    client: TestClient,
) -> None:
    """The default. A service nothing browser-side calls should not be announcing a policy, and
    an empty allowlist is not the same thing as an allowlist of everything."""
    response = _preflight(client, _ORIGIN, "content-type")

    assert "access-control-allow-origin" not in response.headers
