"""A seal of a swept frozen copy answers 410 and changes nothing
(OME-1947, spec S19, contracts K2).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import STATUS_ABANDONED, STATUS_EXPIRED, FrozenCopy
from tests.unit.test_frozen_copy_support import account_id_of, run_async, seed_copy, store

_COPIES = "/v1/frozen-copies"


def _set_status(client: TestClient, copy_id: str, status: str) -> None:
    async def _update() -> None:
        await FrozenCopy.filter(id=UUID(copy_id)).update(status=status)

    run_async(client, _update)


def _read_copy(client: TestClient, copy_id: str) -> FrozenCopy:
    async def _read() -> FrozenCopy:
        return await FrozenCopy.get(id=UUID(copy_id))

    return run_async(client, _read)


def _other_account_headers(client: TestClient, factory, name: str) -> dict[str, str]:
    factory(name)
    login = client.post("/v1/auth/login", json={"username": name, "password": "test-user-password"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


@pytest.mark.parametrize("state", [STATUS_ABANDONED, STATUS_EXPIRED])
def test_an_owner_seal_of_a_swept_copy_answers_410_and_changes_nothing(
    authenticated_client: TestClient, state: str
) -> None:
    client = authenticated_client
    copy_id = seed_copy(
        client,
        account_id_of(client),
        [("chat", {"a": 1}, {"r": 1}, 200), ("chat", {"a": 2}, {"r": 2}, 200)],
        seal=False,
    )
    _set_status(client, copy_id, state)
    before = _read_copy(client, copy_id)

    response = client.post(
        f"{_COPIES}/{copy_id}/seal", json={"provenance": {"engine_version": "4.2.0"}}
    )

    assert response.status_code == 410, response.text
    assert response.json()["detail"] == {
        "code": "frozen_copy_expired",
        "state": state,
        "message": "the frozen copy was swept and its entries were deleted",
    }
    after = _read_copy(client, copy_id)
    assert (after.status, after.entries, after.sealed_at, after.provenance) == (
        before.status,
        before.entries,
        before.sealed_at,
        before.provenance,
    )
    assert after.status == state
    assert after.sealed_at is None


@pytest.mark.parametrize("state", [STATUS_ABANDONED, STATUS_EXPIRED])
def test_a_seal_of_a_swept_copy_by_another_account_is_the_404(
    authenticated_client: TestClient, provisioned_user_factory, state: str
) -> None:
    client = authenticated_client
    copy_id = seed_copy(client, account_id_of(client), [], seal=False)
    _set_status(client, copy_id, state)

    response = client.post(
        f"{_COPIES}/{copy_id}/seal",
        headers=_other_account_headers(client, provisioned_user_factory, f"intruder-{state}"),
    )
    unknown = client.post(f"{_COPIES}/{uuid4()}/seal")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_not_found"
    assert response.json() == unknown.json()
    assert _read_copy(client, copy_id).status == state


@pytest.mark.parametrize("state", [STATUS_ABANDONED, STATUS_EXPIRED])
def test_the_store_returns_a_swept_copy_unchanged(
    authenticated_client: TestClient, state: str
) -> None:
    client = authenticated_client
    owner_id = account_id_of(client)
    copy_id = seed_copy(client, owner_id, [], seal=False)
    _set_status(client, copy_id, state)

    result = run_async(client, lambda: store().seal(UUID(copy_id), owner_id))

    assert result is not None
    assert result.status == state
    assert result.sealed_at is None
