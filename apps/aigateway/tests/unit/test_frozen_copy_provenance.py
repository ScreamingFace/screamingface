"""Seal provenance `routers` and the provenance read route (contract C9, test-plan §4 item 10).

# FEATURE: Router Recipe extension Unit 5.1 — the Engine seals a Router capture with its run
# manifest, the sorted `{binding, revision}` list of every Router in the expression, and a replay
# run reads it back once before `url4_run` to refuse a changed definition.
# INVARIANT: the Gateway reader deploys before any writer: it accepts 1-256 strict entries and
# still refuses every seal body it refused before (`test_frozen_copy_routes.py`).
# INVARIANT: the read route answers a sealed copy only, with the replay route's caller auth, and
# returns the provenance alone, never a stored request (design F2).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import FrozenCopy
from tests.unit.test_frozen_copy_support import run_async

_COPIES = "/v1/frozen-copies"
_REVISION = "sha256:" + "0123456789abcdef" * 4


def _entry(n: int, revision: str = _REVISION) -> dict[str, str]:
    return {"binding": f"router_{n}", "revision": revision}


def _open(client: TestClient) -> str:
    response = client.post(_COPIES)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seal(client: TestClient, copy_id: str, body: Any = None):
    return client.post(f"{_COPIES}/{copy_id}/seal", json=body)


def _read(client: TestClient, copy_id: str):
    return client.get(f"{_COPIES}/{copy_id}/provenance")


def _stored(client: TestClient, copy_id: str) -> FrozenCopy:
    async def _get() -> FrozenCopy:
        return await FrozenCopy.get(id=UUID(copy_id))

    return run_async(client, _get)


# --- seal accepts `routers` -----------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 2, 256])
def test_a_seal_stores_the_manifest_and_the_read_returns_it(
    authenticated_client: TestClient, count: int
) -> None:
    client = authenticated_client
    copy_id = _open(client)
    routers = [_entry(n) for n in range(count)]
    provenance = {"engine_version": "4.2.0", "routers": routers}

    sealed = _seal(client, copy_id, {"provenance": provenance})

    assert sealed.status_code == 200, sealed.text
    assert _stored(client, copy_id).provenance == provenance
    read = _read(client, copy_id)
    assert read.status_code == 200, read.text
    assert read.json() == provenance


def test_the_manifest_is_kept_in_the_order_sent(authenticated_client: TestClient) -> None:
    # WHY: the Engine sends a sorted list and compares lists exactly; the Gateway stores, it
    # never sorts, so the read returns the bytes the capture sealed.
    client = authenticated_client
    copy_id = _open(client)
    routers = [_entry(10), _entry(2, "sha256:" + "f" * 64)]

    _seal(client, copy_id, {"provenance": {"engine_version": "4.2.0", "routers": routers}})

    assert _read(client, copy_id).json()["routers"] == routers


def test_a_repeat_seal_keeps_the_first_manifest(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _open(client)
    first = {"engine_version": "4.2.0", "routers": [_entry(1)]}

    _seal(client, copy_id, {"provenance": first})
    again = _seal(client, copy_id, {"provenance": {"engine_version": "9", "routers": [_entry(2)]}})

    assert again.status_code == 200, again.text
    assert _read(client, copy_id).json() == first


@pytest.mark.parametrize(
    "provenance",
    [
        pytest.param({"engine_version": "4.2.0"}, id="routers-absent"),
        pytest.param({"engine_version": "4.2.0", "routers": None}, id="routers-null"),
    ],
)
def test_a_seal_without_routers_reads_an_empty_list(
    authenticated_client: TestClient, provenance: dict[str, Any]
) -> None:
    client = authenticated_client
    copy_id = _open(client)

    assert _seal(client, copy_id, {"provenance": provenance}).status_code == 200

    assert _stored(client, copy_id).provenance == {"engine_version": "4.2.0"}
    assert _read(client, copy_id).json() == {"engine_version": "4.2.0", "routers": []}


@pytest.mark.parametrize("body", [None, {}, {"provenance": None}])
def test_a_seal_without_provenance_reads_null_and_an_empty_list(
    authenticated_client: TestClient, body: Any
) -> None:
    client = authenticated_client
    copy_id = _open(client)

    assert _seal(client, copy_id, body).status_code == 200

    assert _read(client, copy_id).json() == {"engine_version": None, "routers": []}


# --- seal refuses a bad manifest ----------------------------------------------------------


def _bad(field: str, value: Any, case: str, error: str = "string_pattern_mismatch") -> Any:
    entry = {**_entry(1), field: value}
    return pytest.param([entry], error, [0, field], id=f"{field}-{case}")


# (routers, the error type, where it points below `routers`)
_BAD_ROUTERS = [
    pytest.param([], "too_short", [], id="empty"),
    pytest.param([_entry(n) for n in range(257)], "too_long", [], id="257-entries"),
    pytest.param(_entry(1), "list_type", [], id="an-object-not-a-list"),
    pytest.param(["router_1"], "model_attributes_type", [0], id="entry-not-an-object"),
    pytest.param([{"binding": "router_1"}], "missing", [0, "revision"], id="revision-missing"),
    pytest.param([{"revision": _REVISION}], "missing", [0, "binding"], id="binding-missing"),
    pytest.param([{**_entry(1), "label": "x"}], "extra_forbidden", [0, "label"], id="extra-key"),
    _bad("binding", 1, "not-a-string", "string_type"),
    _bad("binding", "router_", "no-digits"),
    _bad("binding", "router_x", "not-digits"),
    _bad("binding", "Router_1", "case"),
    _bad("binding", "my_router_1", "prefixed"),
    _bad("binding", "router_1\n", "newline"),
    _bad("binding", "router_\u0661", "non-ascii-digit"),
    _bad("revision", 7, "not-a-string", "string_type"),
    _bad("revision", "sha256:" + "0" * 63, "short"),
    _bad("revision", "sha256:" + "0" * 65, "long"),
    _bad("revision", "sha256:" + "A" * 64, "uppercase"),
    _bad("revision", "sha1:" + "0" * 64, "scheme"),
    _bad("revision", "0" * 64, "unprefixed"),
]


@pytest.mark.parametrize(("routers", "error_type", "where"), _BAD_ROUTERS)
def test_a_seal_with_a_bad_manifest_is_422_and_leaves_the_copy_open(
    authenticated_client: TestClient, routers: Any, error_type: str, where: list[Any]
) -> None:
    client = authenticated_client
    copy_id = _open(client)

    response = _seal(
        client, copy_id, {"provenance": {"engine_version": "4.2.0", "routers": routers}}
    )

    assert response.status_code == 422, response.text
    # WHY the exact error: a reader without `routers` also answers 422 (an unknown key), so only
    # the type and place prove the manifest itself was checked.
    error = response.json()["detail"][0]
    assert (error["type"], error["loc"]) == (error_type, ["body", "provenance", "routers", *where])
    assert _stored(client, copy_id).status == "open"


def test_routers_never_stand_in_for_the_engine_version(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _open(client)

    response = _seal(client, copy_id, {"provenance": {"routers": [_entry(1)]}})

    assert response.status_code == 422, response.text


# --- the read route -----------------------------------------------------------------------


@pytest.mark.parametrize("copy", ["open", "unknown", "malformed"])
def test_a_copy_that_is_not_sealed_here_is_unavailable(
    authenticated_client: TestClient, copy: str
) -> None:
    client = authenticated_client
    if copy == "open":
        copy_id = _open(client)
    else:
        copy_id = str(uuid4()) if copy == "unknown" else "not-a-copy-id"

    response = _read(client, copy_id)

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "frozen_copy_unavailable"


def test_any_authenticated_account_reads_a_sealed_copy_it_may_replay(
    authenticated_client: TestClient, provisioned_user_factory
) -> None:
    # WHY: the read uses the chat replay route's caller auth (C9), and any authenticated account
    # holding a copy id may replay that copy (design Q16).
    client = authenticated_client
    copy_id = _open(client)
    provenance = {"engine_version": "4.2.0", "routers": [_entry(1)]}
    _seal(client, copy_id, {"provenance": provenance})
    provisioned_user_factory("reader")
    login = client.post(
        "/v1/auth/login", json={"username": "reader", "password": "test-user-password"}
    )
    other = {"Authorization": f"Bearer {login.json()['token']}"}

    response = client.get(f"{_COPIES}/{copy_id}/provenance", headers=other)

    assert response.status_code == 200, response.text
    assert response.json() == provenance


def test_the_read_requires_authentication(client: TestClient) -> None:
    assert client.get(f"{_COPIES}/{uuid4()}/provenance").status_code in (401, 403)


# --- the read route never trusts a stored row ----------------------------------------------


def _store(client: TestClient, copy_id: str, provenance: Any) -> None:
    async def _set() -> None:
        await FrozenCopy.filter(id=UUID(copy_id)).update(provenance=provenance)

    run_async(client, _set)


_VERSION = "4.2.0"
_NONE = {"engine_version": None, "routers": []}

# (the stored row, the read): rows no seal writes today, from an older writer or a bad migration.
_HISTORICAL_ROWS = [
    pytest.param([_entry(1)], _NONE, id="a-list"),
    # WHY quoted: the JSON field takes a Python string as JSON text, so this stores the string.
    pytest.param(f'"{_VERSION}"', _NONE, id="a-string"),
    pytest.param(7, _NONE, id="a-number"),
    pytest.param(
        {"engine_version": _VERSION, "routers": None},
        {"engine_version": _VERSION, "routers": []},
        id="null-routers",
    ),
    pytest.param(
        {"engine_version": 4, "routers": [_entry(1)]},
        {"engine_version": None, "routers": [_entry(1)]},
        id="numeric-engine-version",
    ),
    pytest.param({"engine_version": ""}, _NONE, id="empty-engine-version"),
    pytest.param({"engine_version": "4" * 65}, _NONE, id="long-engine-version"),
    pytest.param(
        {"engine_version": _VERSION, "routers": _entry(1)},
        {"engine_version": _VERSION, "routers": []},
        id="object-routers",
    ),
    pytest.param(
        {"engine_version": _VERSION, "routers": []},
        {"engine_version": _VERSION, "routers": []},
        id="empty-routers",
    ),
    pytest.param(
        {"engine_version": _VERSION, "routers": [_entry(1), {**_entry(2), "binding": "router_x"}]},
        {"engine_version": _VERSION, "routers": []},
        id="one-bad-entry",
    ),
    pytest.param(
        {"engine_version": _VERSION, "routers": [{**_entry(1), "binding": 1}]},
        {"engine_version": _VERSION, "routers": []},
        id="numeric-binding",
    ),
    pytest.param(
        {"engine_version": _VERSION, "routers": [{**_entry(1), "label": "x"}]},
        {"engine_version": _VERSION, "routers": []},
        id="entry-extra-key",
    ),
    pytest.param(
        {"engine_version": _VERSION, "routers": [_entry(n) for n in range(257)]},
        {"engine_version": _VERSION, "routers": []},
        id="257-entries",
    ),
    pytest.param(
        {"engine_version": _VERSION, "routers": [_entry(1)], "note": "kept private"},
        {"engine_version": _VERSION, "routers": [_entry(1)]},
        id="extra-key-not-leaked",
    ),
]


@pytest.mark.parametrize(("stored", "read"), _HISTORICAL_ROWS)
def test_a_malformed_stored_row_reads_as_the_c9_shape(
    authenticated_client: TestClient, stored: Any, read: dict[str, Any]
) -> None:
    # WHY an empty list for any bad manifest: the Engine compares the list exactly, so a replay
    # run with a Router then refuses on a manifest mismatch instead of trusting a broken row.
    client = authenticated_client
    copy_id = _open(client)
    assert _seal(client, copy_id).status_code == 200
    _store(client, copy_id, stored)

    response = _read(client, copy_id)

    assert response.status_code == 200, response.text
    assert response.json() == read


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    return schema["components"]["schemas"][ref.rsplit("/", 1)[1]] if ref else node


def test_the_read_publishes_the_c9_response_schema(client: TestClient) -> None:
    schema = client.app.openapi()  # type: ignore[attr-defined]
    answer = schema["paths"][f"{_COPIES}/{{copy_id}}/provenance"]["get"]["responses"]["200"]

    read = _resolve(schema, answer["content"]["application/json"]["schema"])

    assert set(read["properties"]) == {"engine_version", "routers"}
    assert set(read["required"]) == {"engine_version", "routers"}
    entry = _resolve(schema, read["properties"]["routers"]["items"])
    assert entry["properties"]["binding"]["pattern"] == r"^router_[0-9]+$"
    assert entry["properties"]["revision"]["pattern"] == r"^sha256:[0-9a-f]{64}$"
