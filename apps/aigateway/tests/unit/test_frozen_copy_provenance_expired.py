"""The provenance read of a swept copy (OME-1947, contracts K3, prd/expired-copy-replay.md R-8).

The provenance read uses the lookup of the replay routes. Owner decision 2026-11-23: an
`expired` copy gets the same 410 `frozen_copy_expired` as a replay, although the purge keeps the
provenance column. An `abandoned` copy stays the 404 of an unknown id.
"""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import STATUS_ABANDONED, STATUS_EXPIRED, FrozenCopy
from tests.unit.test_frozen_copy_support import run_async

_COPIES = "/v1/frozen-copies"
_PROVENANCE = {
    "engine_version": "4.2.0",
    "routers": [{"binding": "router_0", "revision": "sha256:" + "0123456789abcdef" * 4}],
}


def _sealed_with_provenance(client: TestClient) -> str:
    opened = client.post(_COPIES)
    assert opened.status_code == 201, opened.text
    copy_id = opened.json()["id"]
    sealed = client.post(f"{_COPIES}/{copy_id}/seal", json={"provenance": _PROVENANCE})
    assert sealed.status_code == 200, sealed.text
    return copy_id


def _set_status(client: TestClient, copy_id: str, status: str) -> None:
    async def _update() -> None:
        await FrozenCopy.filter(id=UUID(copy_id)).update(status=status)

    run_async(client, _update)


def _read(client: TestClient, copy_id: str):
    return client.get(f"{_COPIES}/{copy_id}/provenance")


def test_r8_the_provenance_of_an_expired_copy_answers_410(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _sealed_with_provenance(client)
    assert _read(client, copy_id).json() == _PROVENANCE
    _set_status(client, copy_id, STATUS_EXPIRED)

    resp = _read(client, copy_id)

    assert resp.status_code == 410
    assert resp.json()["detail"] == {
        "code": "frozen_copy_expired",
        "state": "expired",
        "message": "the frozen copy expired and its entries were deleted",
    }
    assert "X-AIGW-Replay" not in resp.headers


def test_r8_the_provenance_of_an_abandoned_copy_stays_the_404(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _sealed_with_provenance(client)
    _set_status(client, copy_id, STATUS_ABANDONED)

    resp = _read(client, copy_id)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "frozen_copy_unavailable"
