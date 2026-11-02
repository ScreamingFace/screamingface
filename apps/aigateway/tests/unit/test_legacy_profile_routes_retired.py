"""The 13 legacy Profile routes answer 410 with their successor (OME-1209 Stage E, E3, spec R1).

# FEATURE: Stage E route retirement — a caller still on the Profile API gets a coded refusal that
# names the Connection-era route to use instead, never an empty list and never the old operation.
# INVARIANT: a retired route answers from a static table — before authentication, before reading
# the body and before any storage or audit I/O — so it cannot fail differently for a malformed
# body, a missing token or an unknown caller.
# WHY the `detail` envelope: every gateway refusal is `{"detail": {"code": ...}}`, and the SDK
# (`_engine/catalog.py`) and the Admin UI (`errors.ts`) decode `detail.code`. Owner decision
# 2026-10-18; spec R1 names the members of that object.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tortoise.backends.sqlite.client import SqliteClient

# (method, concrete path, expected successor) — one row per (path template, method) of spec §2.1.
RETIRED: list[tuple[str, str, str | None]] = [
    ("GET", "/v1/auth/profiles", "GET /v1/provider-access"),
    ("GET", "/v1/auth/openai/profiles", "GET /v1/provider-access"),
    ("POST", "/v1/auth/openai/profiles", "POST /v1/oauth/connections"),
    ("GET", "/v1/auth/openai/profiles/work", "GET /v1/oauth/connections/{connection_id}"),
    ("GET", "/v1/auth/openai/profiles/work/status", "GET /v1/oauth/connections/{connection_id}"),
    ("PATCH", "/v1/auth/openai/profiles/work", "PATCH /v1/oauth/connections/{connection_id}"),
    ("PUT", "/v1/auth/openai/profiles/work/api-key", "POST /v1/oauth/connections/api-key"),
    ("DELETE", "/v1/auth/openai/profiles/work", "DELETE /v1/oauth/connections/{connection_id}"),
    (
        "POST",
        "/v1/auth/openai/profiles/work/refresh",
        "POST /v1/oauth/connections/{connection_id}/refresh",
    ),
    ("GET", "/v1/admin/accounts/a-1/profiles", "GET /v1/admin/accounts/{account_id}/connections"),
    # WHY: a D18 pair has no name or label to edit, so this one has no successor (spec §2.1).
    ("PATCH", "/v1/admin/accounts/a-1/profiles/openai/work", None),
    (
        "PUT",
        "/v1/admin/accounts/a-1/profiles/openai/work/api-key",
        "PUT /v1/admin/accounts/{account_id}/connections/{provider}/api-key",
    ),
    (
        "DELETE",
        "/v1/admin/accounts/a-1/profiles/openai/work",
        "DELETE /v1/admin/accounts/{account_id}/connections/{provider}",
    ),
]

RETIRED_SCHEMAS = (
    "AdminProfileOut",
    "AdminProfileList",
    "PatchAdminProfileRequest",
    "SetAdminApiKeyRequest",
    "PatchProfileRequest",
    "SetApiKeyRequest",
    "StartAuthRequest",
)

_IDS = [f"{method} {path}" for method, path, _ in RETIRED]


@pytest.fixture
def storage_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Record every SQL statement issued while the test body runs."""
    calls: list[str] = []
    for name in (
        "execute_insert",
        "execute_many",
        "execute_query",
        "execute_query_dict",
        "execute_query_dict_with_affected",
        "execute_script",
    ):
        original = getattr(SqliteClient, name)

        def spy(self: Any, *args: Any, _original: Any = original, **kwargs: Any) -> Any:
            calls.append(str(args[0]) if args else "")
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(SqliteClient, name, spy)
    yield calls


def _assert_retired(response: Any, successor: str | None) -> None:
    assert response.status_code == 410, response.text
    assert response.headers["cache-control"] == "private, no-store"
    detail = response.json()["detail"]
    assert detail["code"] == "legacy_profile_api_retired"
    assert isinstance(detail["message"], str) and detail["message"]
    assert detail["successor"] == successor


@pytest.mark.parametrize(("method", "path", "successor"), RETIRED, ids=_IDS)
def test_a_retired_route_answers_410_with_its_successor_without_a_token(
    client: TestClient, method: str, path: str, successor: str | None
) -> None:
    _assert_retired(client.request(method, path), successor)


@pytest.mark.parametrize(("method", "path", "successor"), RETIRED, ids=_IDS)
def test_a_body_does_not_change_the_answer(
    authenticated_client: TestClient, method: str, path: str, successor: str | None
) -> None:
    _assert_retired(
        authenticated_client.request(method, path, json={"api_key": "sk-x", "name": "w"}),
        successor,
    )


@pytest.mark.parametrize(("method", "path", "successor"), RETIRED, ids=_IDS)
def test_a_malformed_body_still_gets_410_not_422(
    client: TestClient, method: str, path: str, successor: str | None
) -> None:
    response = client.request(
        method, path, content=b"{not json", headers={"content-type": "application/json"}
    )
    _assert_retired(response, successor)


@pytest.mark.parametrize(("method", "path", "successor"), RETIRED, ids=_IDS)
def test_a_retired_route_touches_no_storage_and_writes_no_audit(
    authenticated_client: TestClient,
    storage_calls: list[str],
    caplog: pytest.LogCaptureFixture,
    method: str,
    path: str,
    successor: str | None,
) -> None:
    # INVARIANT: even a caller with a valid token costs no session lookup — the answer is static.
    with caplog.at_level(logging.INFO):
        _assert_retired(
            authenticated_client.request(method, path, json={"api_key": "sk-x"}), successor
        )

    assert storage_calls == []
    assert not [r for r in caplog.records if "admin_action" in r.getMessage()]


def test_every_successor_is_a_documented_live_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for _, _, successor in RETIRED:
        if successor is None:
            continue
        method, template = successor.split(" ", 1)
        assert method.lower() in paths.get(template, {}), f"{successor} is served by no route"


def test_openapi_names_no_profile_route_or_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert [path for path in schema["paths"] if "/profiles" in path] == []
    components = schema.get("components", {}).get("schemas", {})
    assert [name for name in RETIRED_SCHEMAS if name in components] == []


@pytest.mark.parametrize(
    "path", ["/callback", "/auth/callback", "/oauth2callback", "/v1/auth/openai/callback"]
)
def test_the_oauth_callbacks_are_not_retired(client: TestClient, path: str) -> None:
    assert client.get(path).status_code != 410


def test_only_the_listed_methods_are_retired(authenticated_client: TestClient) -> None:
    """A path the Profile API never served keeps the router's ordinary answer."""
    response = authenticated_client.post("/v1/auth/codex/profiles/import", json={})

    assert response.status_code == 405
