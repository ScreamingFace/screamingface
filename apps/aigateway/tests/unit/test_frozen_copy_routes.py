"""Open, seal, tool-results and tool lookup (OME-1307, design §4.3)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import FrozenCopy
from aigateway.core.frozen_copy.store import FrozenCopySealed, FrozenCopyStore, request_digest
from aigateway.core.request_cache.canonical import canonical_digest
from tests.unit.test_frozen_copy_support import (
    CAPTURE_HEADER,
    CHAT_PATH,
    COPY_HEADER,
    PATCH_TARGET,
    DispatchCounter,
    account_id_of,
    arrange_provider,
    chat_body,
    run_async,
    seal_copy,
    seed_copy,
    store,
    stored_entries,
)

_COPIES = "/v1/frozen-copies"
_DESCRIPTION = {"tool": "web_search", "query": "primes below one hundred"}
_OCCURRENCE = "X-AIGW-Replay-Occurrence"


def _tool_results(copy_id: str) -> str:
    return f"{_COPIES}/{copy_id}/tool-results"


def _lookup(copy_id: str) -> str:
    return f"{_COPIES}/{copy_id}/tool-results/lookup"


def _store_tool(client: TestClient, copy_id: str, result: str, description=None):
    return client.post(
        _tool_results(copy_id),
        json={
            "description": _DESCRIPTION if description is None else description,
            "result": result,
        },
    )


def _other_account_headers(client: TestClient, factory, name: str) -> tuple[dict[str, str], UUID]:
    user = factory(name)
    login = client.post("/v1/auth/login", json={"username": name, "password": "test-user-password"})
    return {"Authorization": f"Bearer {login.json()['token']}"}, UUID(user["id"])


def _read_copy(client: TestClient, copy_id: str) -> FrozenCopy:
    async def _read() -> FrozenCopy:
        return await FrozenCopy.get(id=UUID(copy_id))

    return run_async(client, _read)


# --- open ----------------------------------------------------------------------------------


def test_open_creates_an_open_copy_owned_by_the_caller(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(_COPIES)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "status"}
    assert body["status"] == "open"
    copy = _read_copy(authenticated_client, body["id"])
    assert copy.account_id == account_id_of(authenticated_client)
    assert (copy.status, copy.entries, copy.sealed_at) == ("open", 0, None)


def test_open_requires_authentication(client: TestClient) -> None:
    assert client.post(_COPIES).status_code in (401, 403)


@pytest.mark.parametrize("path", [_COPIES, f"{_COPIES}/{uuid4()}"])
def test_there_is_no_list_or_read_back_endpoint(authenticated_client: TestClient, path) -> None:
    """Design F2: no endpoint returns stored requests."""
    copy_id = authenticated_client.post(_COPIES).json()["id"]

    for target in (path, f"{_COPIES}/{copy_id}", _tool_results(copy_id)):
        assert authenticated_client.get(target).status_code in (404, 405), target


# --- 10. seal -------------------------------------------------------------------------------


def test_seal_is_owner_only_idempotent_and_counts_entries(
    authenticated_client: TestClient, provisioned_user_factory
) -> None:
    client = authenticated_client
    copy_id = seed_copy(
        client,
        account_id_of(client),
        [("chat", {"a": 1}, {"r": 1}, 200), ("chat", {"a": 2}, {"r": 2}, 200)],
        seal=False,
    )
    assert _store_tool(client, copy_id, "tool text").status_code == 200

    sealed = client.post(f"{_COPIES}/{copy_id}/seal")
    first_sealed_at = _read_copy(client, copy_id).sealed_at
    again = client.post(f"{_COPIES}/{copy_id}/seal")

    assert sealed.status_code == 200, sealed.text
    assert sealed.json() == {"id": copy_id, "status": "sealed", "entries": 3}
    assert again.status_code == 200
    assert again.json() == sealed.json()
    assert first_sealed_at is not None
    assert _read_copy(client, copy_id).sealed_at == first_sealed_at


def test_seal_by_a_non_owner_or_of_an_unknown_copy_is_the_same_404(
    authenticated_client: TestClient, provisioned_user_factory
) -> None:
    client = authenticated_client
    other_headers, _ = _other_account_headers(client, provisioned_user_factory, "intruder")
    copy_id = client.post(_COPIES).json()["id"]

    foreign = client.post(f"{_COPIES}/{copy_id}/seal", headers=other_headers)
    unknown = client.post(f"{_COPIES}/{uuid4()}/seal")

    assert foreign.status_code == 404
    assert unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert _read_copy(client, copy_id).status == "open"


def test_capture_after_seal_is_refused(
    authenticated_client: TestClient, credential_blobs, monkeypatch
) -> None:
    client = authenticated_client
    arrange_provider(client, credential_blobs)
    monkeypatch.setattr(PATCH_TARGET, DispatchCounter())
    copy_id = client.post(_COPIES).json()["id"]
    headers = {COPY_HEADER: copy_id}
    assert client.post(CHAT_PATH, json=chat_body(), headers=headers).headers[CAPTURE_HEADER] == (
        "stored"
    )
    client.post(f"{_COPIES}/{copy_id}/seal")

    late = client.post(CHAT_PATH, json=chat_body(temperature=0.1), headers=headers)

    assert late.status_code == 200
    assert late.headers[CAPTURE_HEADER] == "refused"
    assert len(stored_entries(client, copy_id)) == 1
    assert client.post(f"{_COPIES}/{copy_id}/seal").json()["entries"] == 1


def test_the_store_itself_refuses_an_insert_into_a_sealed_copy(
    authenticated_client: TestClient,
) -> None:
    """F1 holds in the store, not only in the route's earlier check (a seal can land between)."""
    client = authenticated_client
    owner = account_id_of(client)
    copy_id = seed_copy(client, owner, [], seal=False)
    stale_view = _read_copy(client, copy_id)  # read while still open
    seal_copy(client, copy_id)

    async def _late_insert() -> None:
        with pytest.raises(FrozenCopySealed):
            await store().capture(stale_view, "chat", {"a": 1}, {"r": 1}, 200)

    run_async(client, _late_insert)
    assert stored_entries(client, copy_id) == []


# --- 11. tool results -----------------------------------------------------------------------


def test_tool_results_capture_and_lookup_round_trip(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = client.post(_COPIES).json()["id"]

    stored = _store_tool(client, copy_id, "25 primes: 2, 3, 5, ...")
    client.post(f"{_COPIES}/{copy_id}/seal")
    found = client.post(_lookup(copy_id), json={"description": _DESCRIPTION})

    assert stored.status_code == 200, stored.text
    assert stored.json() == {"outcome": "stored"}
    assert found.status_code == 200, found.text
    assert found.json() == {"result": "25 primes: 2, 3, 5, ..."}
    (entry,) = stored_entries(client, copy_id)
    assert entry["kind"] == "tool"
    assert entry["request"] == _DESCRIPTION
    assert entry["response"] == {"result": "25 primes: 2, 3, 5, ..."}
    assert entry["status_code"] == 200
    assert entry["digest"] == canonical_digest({"kind": "tool", "request": _DESCRIPTION})
    assert entry["digest"] == request_digest("tool", _DESCRIPTION)


def test_a_tool_result_that_is_an_error_string_is_stored_as_given(
    authenticated_client: TestClient,
) -> None:
    """The copy holds exactly what the model saw, a failure string included."""
    client = authenticated_client
    copy_id = client.post(_COPIES).json()["id"]
    _store_tool(client, copy_id, "Search failed: upstream timeout")
    client.post(f"{_COPIES}/{copy_id}/seal")

    found = client.post(_lookup(copy_id), json={"description": _DESCRIPTION})

    assert found.json() == {"result": "Search failed: upstream timeout"}


def test_tool_lookup_follows_the_occurrence_rule(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = client.post(_COPIES).json()["id"]
    for text in ("first", "second", "third"):
        _store_tool(client, copy_id, text)
    client.post(f"{_COPIES}/{copy_id}/seal")

    def at(occurrence: int | None) -> str:
        headers = {} if occurrence is None else {_OCCURRENCE: str(occurrence)}
        return client.post(
            _lookup(copy_id), json={"description": _DESCRIPTION}, headers=headers
        ).json()["result"]

    assert [at(None), at(0), at(1), at(2), at(9)] == ["first", "first", "second", "third", "third"]


def test_tool_lookup_miss_is_404_and_does_not_match_another_description(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = client.post(_COPIES).json()["id"]
    _store_tool(client, copy_id, "text")
    client.post(f"{_COPIES}/{copy_id}/seal")

    miss = client.post(_lookup(copy_id), json={"description": {**_DESCRIPTION, "query": "other"}})

    assert miss.status_code == 404
    assert miss.json()["detail"]["code"] == "frozen_copy_miss"


def test_tool_lookup_of_an_open_or_unknown_copy_is_404_unavailable(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    open_copy = client.post(_COPIES).json()["id"]
    _store_tool(client, open_copy, "text")

    for copy_id in (open_copy, str(uuid4())):
        response = client.post(_lookup(copy_id), json={"description": _DESCRIPTION})
        assert response.status_code == 404, copy_id
        assert response.json()["detail"]["code"] == "frozen_copy_unavailable"


def test_tool_lookup_rejects_a_malformed_occurrence(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = client.post(_COPIES).json()["id"]
    client.post(f"{_COPIES}/{copy_id}/seal")

    response = client.post(
        _lookup(copy_id), json={"description": _DESCRIPTION}, headers={_OCCURRENCE: "-3"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "malformed_replay_occurrence"


def test_any_account_may_look_up_a_sealed_copys_tool_result(
    authenticated_client: TestClient, provisioned_user_factory
) -> None:
    client = authenticated_client
    other_headers, _ = _other_account_headers(client, provisioned_user_factory, "looker")
    copy_id = client.post(_COPIES).json()["id"]
    _store_tool(client, copy_id, "text")
    client.post(f"{_COPIES}/{copy_id}/seal")

    response = client.post(
        _lookup(copy_id), json={"description": _DESCRIPTION}, headers=other_headers
    )

    assert response.status_code == 200, response.text


def test_tool_result_into_a_sealed_copy_is_409(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = client.post(_COPIES).json()["id"]
    client.post(f"{_COPIES}/{copy_id}/seal")

    response = _store_tool(client, copy_id, "late")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "frozen_copy_sealed"
    assert stored_entries(client, copy_id) == []


def test_tool_result_by_a_non_owner_is_404_even_when_the_copy_is_sealed(
    authenticated_client: TestClient, provisioned_user_factory
) -> None:
    client = authenticated_client
    other_headers, _ = _other_account_headers(client, provisioned_user_factory, "writer")
    open_copy = client.post(_COPIES).json()["id"]
    sealed_copy = client.post(_COPIES).json()["id"]
    client.post(f"{_COPIES}/{sealed_copy}/seal")
    body = {"description": _DESCRIPTION, "result": "x"}

    responses = [
        client.post(_tool_results(copy_id), json=body, headers=other_headers)
        for copy_id in (open_copy, sealed_copy, str(uuid4()))
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert responses[0].json() == responses[1].json() == responses[2].json()
    assert stored_entries(client, open_copy) == []


@pytest.mark.parametrize(
    "body",
    [
        {"result": "x"},
        {"description": _DESCRIPTION},
        {"description": "not an object", "result": "x"},
        {"description": _DESCRIPTION, "result": 5},
        [],
    ],
    ids=[
        "no-description",
        "no-result",
        "description-not-object",
        "result-not-string",
        "not-object",
    ],
)
def test_a_malformed_tool_result_body_is_422(authenticated_client: TestClient, body: Any) -> None:
    copy_id = authenticated_client.post(_COPIES).json()["id"]

    response = authenticated_client.post(_tool_results(copy_id), json=body)

    assert response.status_code == 422
    assert stored_entries(authenticated_client, copy_id) == []


def test_a_failing_store_reports_failed_and_does_not_error(
    authenticated_client: TestClient, monkeypatch
) -> None:
    copy_id = authenticated_client.post(_COPIES).json()["id"]

    async def _boom(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(FrozenCopyStore, "capture", _boom)

    response = _store_tool(authenticated_client, copy_id, "text")

    assert response.status_code == 200
    assert response.json() == {"outcome": "failed"}


def test_a_tool_entry_over_the_size_cap_is_failed_not_stored(
    monkeypatch, authenticated_client_small_cap: TestClient
) -> None:
    client = authenticated_client_small_cap
    copy_id = client.post(_COPIES).json()["id"]

    response = _store_tool(client, copy_id, "x" * 400)

    assert response.status_code == 200
    assert response.json() == {"outcome": "failed"}
    assert stored_entries(client, copy_id) == []


@pytest.fixture
def _small_cap_env(monkeypatch):
    monkeypatch.setenv("AIGW_FROZEN_COPY_MAX_ENTRY_BYTES", "300")


@pytest.fixture
def authenticated_client_small_cap(_small_cap_env, authenticated_client: TestClient):
    return authenticated_client
