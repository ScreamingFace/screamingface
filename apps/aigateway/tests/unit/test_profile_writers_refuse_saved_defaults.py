"""OME-1323 Stage C (D2): no writer accepts saved Profile defaults any more.

FEATURE: the Profile write surface — tenant/admin API-key PUT, OAuth start, tenant/admin PATCH.

STORY: as an old client that still sends `defaults`, I get an explicit `422` naming the field —
not a silent accept, not a silent ignore — before anything is validated, stored or published.
As a current client that omits it, nothing changes; and the historical defaults a Profile still
carries for the compatibility window survive every write untouched.

INVARIANT: a PRESENT `defaults` member — even `null` — is refused with
`defaults_not_accepted` before any side effect, and the refusal echoes no key, prompt or value.
An OMITTED member is accepted exactly as before.

AIDEV-NOTE: N5 is RED on the pre-change code (every writer accepted `defaults`); N5o, N6 and N7
are baselines that passed before and after.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from ipaddress import ip_network
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_ADMIN = "admin@openmined.org"
_OLD_KEY = "sk-ant-api03-historical-profile-secret"
_KEY = "sk-ant-api03-submitted-profile-secret"
_HISTORICAL = ProfileDefaults(system_prompt="the historical house style", temperature=0.3)
_SUBMITTED_PROMPT = "a submitted secret system prompt"
_SUBMITTED = {"system_prompt": _SUBMITTED_PROMPT, "temperature": 0.7}
_NEVER_ECHOED = (_OLD_KEY, _KEY, _SUBMITTED_PROMPT, "the historical house style")


@dataclass(frozen=True)
class _Writer:
    """One HTTP boundary that could once write saved defaults; `{account}` fills in per test."""

    method: str
    path: str
    body: dict[str, Any]
    ok: int
    admin: bool = False


_WRITERS = {
    "tenant-api-key-put": _Writer(
        "PUT", "/v1/auth/anthropic/profiles/work/api-key", {"api_key": _KEY}, 200
    ),
    "admin-api-key-put": _Writer(
        "PUT",
        "/v1/admin/accounts/{account}/profiles/anthropic/work/api-key",
        {"api_key": _KEY},
        200,
        admin=True,
    ),
    "oauth-start": _Writer("POST", "/v1/auth/anthropic/profiles", {"name": "work"}, 201),
    "tenant-patch": _Writer(
        "PATCH", "/v1/auth/anthropic/profiles/work", {"account_label": "renamed"}, 200
    ),
    "admin-patch": _Writer(
        "PATCH",
        "/v1/admin/accounts/{account}/profiles/anthropic/work",
        {"account_label": "renamed"},
        200,
        admin=True,
    ),
}
_PATCHES = ["tenant-patch", "admin-patch"]
_KEY_PUTS = ["tenant-api-key-put", "admin-api-key-put"]


# --- arrangement --------------------------------------------------------------


class _Validation:
    """Accepts any key without calling the provider — or, when forbidden, refuses to be asked."""

    def __init__(self, *, forbidden: bool = False) -> None:
        self.forbidden = forbidden

    async def validate(self, _plugin, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        if self.forbidden:
            raise AssertionError("the key was validated before the refusal")
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


@dataclass
class _Arranged:
    http: TestClient
    path: str
    headers: dict[str, str]
    account_id: str


def _arrange(client: TestClient, writer: _Writer) -> _Arranged:
    """The caller for `writer`: a logged-in tenant, or an allowlisted admin acting on a tenant."""
    app: Any = client.app
    if writer.admin:
        app.state.settings.auth_mode = "cloudflare_headers"
        app.state.settings.allowed_networks = (ip_network("10.0.0.0/8"),)
        app.state.settings.admin_emails = frozenset({_ADMIN})
        http = TestClient(app, client=("10.1.2.3", 50000))
        headers = {"X-User-Email": _ADMIN}
        created = http.post(
            "/v1/admin/accounts", json={"email": "tenant@openmined.org"}, headers=headers
        )
        assert created.status_code == 201, created.text
        account_id = created.json()["id"]
    else:
        login = client.post(
            "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
        )
        assert login.status_code == 200, login.text
        client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})
        http, headers = client, {}
        account_id = client.get("/v1/auth/me").json()["id"]
    app.state.api_key_validation_service = _Validation()
    return _Arranged(http, writer.path.format(account=account_id), headers, account_id)


def _send(arranged: _Arranged, writer: _Writer, body: dict[str, Any]):
    return arranged.http.request(writer.method, arranged.path, json=body, headers=arranged.headers)


def _index(credential_blobs) -> ProfileIndexStore:
    return ProfileIndexStore(credential_store=credential_blobs.store)


def _stored(credential_blobs, account_id: str) -> Profile | None:
    return asyncio.run(_index(credential_blobs).get(account_id, "anthropic", "work"))


def _seed_historical(credential_blobs, account_id: str) -> None:
    """Give Profile `work` HISTORICAL defaults, written straight into the index.

    WHY directly: after Stage C no writer can put them there; documents written before it can.
    """
    current = _stored(credential_blobs, account_id)
    profile = (
        current.model_copy(update={"defaults": _HISTORICAL})
        if current is not None
        else Profile(
            id=profile_id_for(account_id, "anthropic", "work"),
            account_id=account_id,
            provider="anthropic",
            name="work",
            state=ProfileState.AUTHENTICATED,
            defaults=_HISTORICAL,
        )
    )
    asyncio.run(_index(credential_blobs).upsert(profile))


def _forbid_side_effects(monkeypatch, app: Any) -> None:
    """Every write a writer could perform raises; so does the provider validation call."""

    def _sync(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a side effect ran before the refusal")

    async def _async(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a side effect ran before the refusal")

    state = app.state
    state.api_key_validation_service = _Validation(forbidden=True)
    for name in ("upsert", "begin_pending", "update_metadata"):
        monkeypatch.setattr(state.profile_index, name, _async)
    monkeypatch.setattr(state.credential_store, "write", _async)
    monkeypatch.setattr(state.pending_auth, "put", _sync)
    monkeypatch.setattr(state.pending_auth, "pop_for_profile", _sync)
    # WHY the route module: OAuth start binds a loopback listener and publishes a Connection-side
    # flow through these two names before it touches the index.
    monkeypatch.setattr("aigateway.routes.auth._redirect_uri_for", _async)
    monkeypatch.setattr("aigateway.routes.auth.begin_connection_oauth", _async)


# --- N5 (RED): a present `defaults` member is refused before any side effect -


@pytest.mark.parametrize("submitted", [_SUBMITTED, None], ids=["a-value", "null"])
@pytest.mark.parametrize("writer_id", list(_WRITERS))
def test_a_present_defaults_member_is_refused_before_any_side_effect(
    client, credential_blobs, monkeypatch, caplog, writer_id: str, submitted: Any
) -> None:
    """RED before Stage C: every writer accepted `defaults` and went on to write."""
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    # WHY a Profile for every writer: the PATCHes need one to reach their write, and a PUT or an
    # OAuth start over a Profile with historical defaults is the case the refusal must not touch.
    _seed_historical(credential_blobs, arranged.account_id)
    before = _stored(credential_blobs, arranged.account_id)
    _forbid_side_effects(monkeypatch, client.app)
    caplog.set_level(logging.DEBUG)

    response = _send(arranged, writer, {**writer.body, "defaults": submitted})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert set(detail) == {"code", "field", "message"}
    assert (detail["code"], detail["field"]) == ("defaults_not_accepted", "defaults")
    # INVARIANT: the refusal names the field and nothing else — no key, prompt or value.
    for secret in _NEVER_ECHOED:
        assert secret not in response.text
        assert secret not in caplog.text
    assert "temperature" not in response.text
    assert _stored(credential_blobs, arranged.account_id) == before


# --- N5o (baseline): an omitted `defaults` member is accepted as before -------


@pytest.mark.parametrize("writer_id", list(_WRITERS))
def test_a_request_that_omits_defaults_is_accepted_and_keeps_the_historical_ones(
    client, credential_blobs, writer_id: str
) -> None:
    """GREEN before and after: omitting `defaults` never changed what a Profile holds."""
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    _seed_historical(credential_blobs, arranged.account_id)

    response = _send(arranged, writer, writer.body)

    assert response.status_code == writer.ok, response.text
    assert "defaults_not_accepted" not in response.text
    stored = _stored(credential_blobs, arranged.account_id)
    assert stored is not None
    assert stored.defaults.model_dump_json() == _HISTORICAL.model_dump_json()


# --- N6 (baseline): a label-only PATCH keeps historical defaults --------------


@pytest.mark.parametrize("writer_id", _PATCHES)
def test_a_label_only_patch_keeps_the_historical_defaults(
    client, credential_blobs, writer_id: str
) -> None:
    """GREEN before and after; the response DTO still renders the stored defaults (D16)."""
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    _seed_historical(credential_blobs, arranged.account_id)

    response = _send(arranged, writer, {"account_label": "renamed"})

    assert response.status_code == 200, response.text
    assert response.json()["account_label"] == "renamed"
    assert response.json()["defaults"] == _HISTORICAL.model_dump(mode="json")
    stored = _stored(credential_blobs, arranged.account_id)
    assert stored is not None
    assert stored.account_label == "renamed"
    assert stored.defaults.model_dump_json() == _HISTORICAL.model_dump_json()


# --- N7 (baseline): a key rotation keeps historical defaults byte-identical ---


@pytest.mark.parametrize("writer_id", _KEY_PUTS)
def test_a_key_rotation_keeps_the_historical_defaults_byte_identical(
    client, credential_blobs, writer_id: str
) -> None:
    """GREEN before and after: rotating the key is not a defaults write."""
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    created = _send(arranged, writer, {"api_key": _OLD_KEY})
    assert created.status_code == 200, created.text
    _seed_historical(credential_blobs, arranged.account_id)
    service = credential_service_for(credential_name_for(arranged.account_id, "work"))

    rotated = _send(arranged, writer, {"api_key": _KEY})

    assert rotated.status_code == 200, rotated.text
    assert _KEY not in rotated.text
    assert rotated.json()["defaults"] == _HISTORICAL.model_dump(mode="json")
    stored = _stored(credential_blobs, arranged.account_id)
    assert stored is not None
    assert stored.defaults.model_dump_json() == _HISTORICAL.model_dump_json()
    assert json.loads(credential_blobs.read(service, "default") or "{}")["api_key"] == _KEY


# --- N8 (RED): the refusal precedes body validation ---------------------------

# WHY these bodies: each is what an old client could send and each fails the writer's request
# model on its own — the PUTs and the OAuth start lack their required member, and the PATCHes
# carry a label of the wrong type (they have no required member).
_INVALID_REST: dict[str, dict[str, Any]] = {
    "tenant-api-key-put": {},
    "admin-api-key-put": {},
    "oauth-start": {},
    "tenant-patch": {"account_label": 42},
    "admin-patch": {"account_label": 42},
}


@pytest.mark.parametrize("submitted", [_SUBMITTED, None], ids=["a-value", "null"])
@pytest.mark.parametrize("writer_id", list(_WRITERS))
def test_a_present_defaults_member_is_refused_even_when_the_rest_of_the_body_is_invalid(
    client, credential_blobs, monkeypatch, caplog, writer_id: str, submitted: Any
) -> None:
    """RED before the fix: FastAPI validated the body first and answered with its generic 422.

    INVARIANT: the refusal holds for ANY body that carries `defaults`, an incomplete one included,
    so the generic validation answer (which echoes submitted values unless redacted) never runs
    for it. Authentication still comes first (N9), and an admin refusal is still audited with its
    actor even though the handler never ran.
    """
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    _seed_historical(credential_blobs, arranged.account_id)
    before = _stored(credential_blobs, arranged.account_id)
    _forbid_side_effects(monkeypatch, client.app)
    caplog.set_level(logging.DEBUG)

    response = _send(arranged, writer, {**_INVALID_REST[writer_id], "defaults": submitted})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), response.text
    assert set(detail) == {"code", "field", "message"}
    assert (detail["code"], detail["field"]) == ("defaults_not_accepted", "defaults")
    for secret in _NEVER_ECHOED:
        assert secret not in response.text
        assert secret not in caplog.text
    assert "temperature" not in response.text
    assert _stored(credential_blobs, arranged.account_id) == before
    if writer.admin:
        audit = f"admin_action actor={_ADMIN} method={writer.method} path={arranged.path}"
        assert f"{audit} status_code=422" in caplog.text, caplog.text


# --- N9 (baseline): authentication still precedes the refusal -----------------


@pytest.mark.parametrize("writer_id", list(_WRITERS))
def test_an_unauthenticated_request_carrying_defaults_is_answered_by_authentication(
    client, credential_blobs, writer_id: str
) -> None:
    """GREEN before and after: refusing ahead of body validation must not refuse ahead of auth.

    WHY it matters: a refusal that answered first would tell an anonymous caller which routes
    exist and what they accept.
    """
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    # WHY a fresh client for the tenant: `_arrange` logged the fixture's client in.
    http = arranged.http if writer.admin else TestClient(client.app)
    body = {**_INVALID_REST[writer_id], "defaults": _SUBMITTED}

    response = http.request(writer.method, arranged.path, json=body)

    assert response.status_code == 401, response.text
    assert "defaults_not_accepted" not in response.text
    assert _SUBMITTED_PROMPT not in response.text


# --- N10 (baseline): a body that is not JSON keeps its ordinary answer --------


@pytest.mark.parametrize("writer_id", list(_WRITERS))
def test_a_body_that_is_not_json_still_gets_the_ordinary_validation_answer(
    client, credential_blobs, writer_id: str
) -> None:
    """GREEN before and after: the refusal reads the body as JSON, and must not turn a body it
    cannot parse into a 500 — FastAPI's own (redacted) validation answer stays in charge."""
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    headers = {**arranged.headers, "Content-Type": "text/plain"}

    response = arranged.http.request(
        writer.method, arranged.path, content=b"not json", headers=headers
    )

    assert response.status_code == 422, response.text
    assert "defaults_not_accepted" not in response.text


# --- N11 (RED, review 2026-09-24): a body too deep to parse is no 500 either ----------

# WHY: `json.loads` raises `RecursionError`, not `ValueError`, on deeply nested input, and
# FastAPI leaves a non-JSON content type unparsed — so this body reaches the refusal first.
_TOO_DEEP = b"[" * 100_000 + b"]" * 100_000


@pytest.mark.parametrize("content_type", ["text/plain", None])
@pytest.mark.parametrize("writer_id", list(_WRITERS))
def test_a_body_too_deeply_nested_to_parse_still_gets_the_ordinary_validation_answer(
    client, credential_blobs, writer_id: str, content_type: str | None
) -> None:
    writer = _WRITERS[writer_id]
    arranged = _arrange(client, writer)
    headers = {k: v for k, v in arranged.headers.items() if k.lower() != "content-type"}
    if content_type is not None:
        headers["Content-Type"] = content_type

    response = arranged.http.request(
        writer.method, arranged.path, content=_TOO_DEEP, headers=headers
    )

    assert response.status_code == 422, response.text
    assert "defaults_not_accepted" not in response.text
