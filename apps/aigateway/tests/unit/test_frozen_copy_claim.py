"""The frozen copy claim route and its guard
(OME-1947, contracts K4, prd/score-claim.md K-1 to K-7).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from aigateway.config import Settings
from aigateway.core.frozen_copy.models import STATUS_ABANDONED, STATUS_EXPIRED, FrozenCopy
from aigateway.core.frozen_copy.sweep import build_frozen_copy_sweep
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    run_async,
    seed_copy,
    store,
    stored_entries,
)
from tests.unit.test_frozen_copy_sweep_support import make_entries

CLAIMER = "scoreboard@openmined.org"
ADMIN = "admin@openmined.org"
OUTSIDER = "nobody@example.com"
POD_NETWORK = ip_network("10.0.0.0/8")
UNTRUSTED_PEER = "203.0.113.7"
_STORE_LOGGER = "aigateway.core.frozen_copy.store"


def _settings_of(client) -> Any:
    return client.app.state.settings


def _claim_client(
    client,
    *,
    peer: str = "10.1.2.3",
    claimers: frozenset[str] | None = None,
    admins: frozenset[str] = frozenset(),
) -> TestClient:
    settings = _settings_of(client)
    settings.auth_mode = "cloudflare_headers"
    settings.allowed_networks = (POD_NETWORK,)
    settings.frozen_copy_claim_emails = frozenset({CLAIMER}) if claimers is None else claimers
    settings.admin_emails = admins
    return TestClient(client.app, client=(peer, 50000))


def _claim_path(copy_id: str) -> str:
    return f"/v1/frozen-copies/{copy_id}/claim"


def _new_copy(client: TestClient, *, seal: bool = True) -> str:
    return seed_copy(client, account_id_of(client), [], seal=seal)


def _set_status(client: TestClient, copy_id: str, status: str) -> None:
    async def _update() -> None:
        await FrozenCopy.filter(id=UUID(copy_id)).update(status=status)

    run_async(client, _update)


def _read_copy(client: TestClient, copy_id: str) -> FrozenCopy:
    async def _read() -> FrozenCopy:
        return await FrozenCopy.get(id=UUID(copy_id))

    return run_async(client, _read)


def test_k1_a_first_claim_sets_claimed_at_and_answers_already_false(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == copy_id
    assert body["status"] == "sealed"
    assert body["already"] is False
    assert datetime.fromisoformat(body["claimed_at"]).utcoffset() == timedelta(0)
    assert _read_copy(client, copy_id).claimed_at is not None


def test_k2_a_second_claim_answers_already_true_and_keeps_the_first_time(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client)
    first = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER}).json()

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 200
    second = resp.json()
    assert second["already"] is True
    assert second["claimed_at"] == first["claimed_at"]


def test_k3_a_claim_of_an_expired_copy_answers_410_and_changes_nothing(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    _set_status(client, copy_id, STATUS_EXPIRED)
    claimer = _claim_client(client)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "frozen_copy_expired"
    assert resp.json()["detail"]["state"] == "expired"
    copy = _read_copy(client, copy_id)
    assert copy.claimed_at is None
    assert copy.status == "expired"


def test_k4_a_claim_of_an_open_copy_answers_409(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client, seal=False)
    claimer = _claim_client(client)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "code": "frozen_copy_not_sealed",
        "message": "the frozen copy is not sealed",
    }
    assert _read_copy(client, copy_id).claimed_at is None


def test_k4_a_claim_of_an_abandoned_copy_answers_410(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    _set_status(client, copy_id, STATUS_ABANDONED)
    claimer = _claim_client(client)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "frozen_copy_expired"
    assert resp.json()["detail"]["state"] == "abandoned"
    assert _read_copy(client, copy_id).claimed_at is None


def test_k4_an_unknown_and_a_malformed_id_get_the_same_404(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    claimer = _claim_client(client)

    unknown = claimer.post(_claim_path(str(uuid4())), headers={"X-User-Email": CLAIMER})
    malformed = claimer.post(_claim_path("not-a-uuid"), headers={"X-User-Email": CLAIMER})

    assert unknown.status_code == 404
    assert malformed.status_code == 404
    assert unknown.json()["detail"] == malformed.json()["detail"]
    assert unknown.json()["detail"] == {
        "code": "frozen_copy_not_found",
        "message": "no such frozen copy",
    }


def test_k5_the_address_case_does_not_matter(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": "ScoreBoard@OpenMined.ORG"})

    assert resp.status_code == 200


def test_k5_an_address_outside_the_claim_list_gets_403(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": OUTSIDER})

    assert resp.status_code == 403
    assert _read_copy(client, copy_id).claimed_at is None


def test_k5_an_empty_claim_list_gets_503(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client, claimers=frozenset())

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 503


def test_k5_the_empty_list_is_checked_before_the_peer(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client, claimers=frozenset(), peer=UNTRUSTED_PEER)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 503


def test_k5_no_identity_header_gets_401(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client)

    assert claimer.post(_claim_path(copy_id)).status_code == 401
    assert claimer.post(_claim_path(copy_id), headers={"X-User-Email": "   "}).status_code == 401


def test_k5_an_untrusted_peer_gets_403_with_a_listed_address(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client, peer=UNTRUSTED_PEER)

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 403
    assert _read_copy(client, copy_id).claimed_at is None


def test_k5_the_peer_is_checked_before_the_identity_header(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client, peer=UNTRUSTED_PEER)

    resp = claimer.post(_claim_path(copy_id))

    assert resp.status_code == 403


def test_k5_a_claim_makes_no_account_row(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client, admins=frozenset({ADMIN}))

    assert claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER}).status_code == 200
    assert claimer.post(_claim_path(copy_id), headers={"X-User-Email": OUTSIDER}).status_code == 403

    resp = claimer.get("/v1/admin/accounts", headers={"X-User-Email": ADMIN})

    assert resp.status_code == 200
    usernames = {account["username"] for account in resp.json()["accounts"]}
    assert CLAIMER not in usernames
    assert OUTSIDER not in usernames


def test_k6_jwt_mode_gets_503(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client)
    _settings_of(client).auth_mode = "jwt"

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})
    bearer = client.post(_claim_path(copy_id))

    assert resp.status_code == 503
    assert bearer.status_code == 503
    assert _read_copy(client, copy_id).claimed_at is None


def test_k6_disabled_mode_accepts_the_call_with_no_list(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client, claimers=frozenset())
    _settings_of(client).auth_mode = "disabled"

    resp = claimer.post(_claim_path(copy_id))

    assert resp.status_code == 200
    assert resp.json()["already"] is False


def test_k7_an_admin_only_address_cannot_claim(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)
    claimer = _claim_client(client, admins=frozenset({ADMIN}))

    resp = claimer.post(_claim_path(copy_id), headers={"X-User-Email": ADMIN})

    assert resp.status_code == 403
    assert _read_copy(client, copy_id).claimed_at is None


def test_k7_a_claimer_only_address_cannot_call_the_admin_api(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    claimer = _claim_client(client, admins=frozenset({ADMIN}))

    resp = claimer.get("/v1/admin/accounts", headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 403


def test_the_store_claim_of_an_unknown_copy_is_none(authenticated_client: TestClient) -> None:
    client = authenticated_client

    outcome = run_async(client, lambda: store().claim(uuid4()))

    assert outcome is None


def test_the_store_claim_is_first_only_once(authenticated_client: TestClient) -> None:
    client = authenticated_client
    copy_id = _new_copy(client)

    first = run_async(client, lambda: store().claim(UUID(copy_id)))
    second = run_async(client, lambda: store().claim(UUID(copy_id)))

    assert first is not None and second is not None
    assert first.first is True
    assert second.first is False
    assert second.copy.claimed_at is not None


def test_b1_3_a_claim_writes_one_info_record_with_the_copy_id_and_no_email(
    authenticated_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    client = authenticated_client
    owner = account_id_of(client)
    copy_id = _new_copy(client)
    claimer = _claim_client(client)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger=_STORE_LOGGER):
        first = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})
        second = claimer.post(_claim_path(copy_id), headers={"X-User-Email": CLAIMER})

    assert first.status_code == 200
    assert second.status_code == 200
    records = [r for r in caplog.records if r.name == _STORE_LOGGER and r.levelno == logging.INFO]
    assert len(records) == 1
    assert records[0].getMessage() == f"frozen copy claimed copy={copy_id}"
    assert CLAIMER not in caplog.text
    assert str(owner) not in caplog.text


def test_k25_a_claim_of_an_unmarked_copy_past_its_period_keeps_it(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    owner = account_id_of(client)
    kept_id = seed_copy(client, owner, make_entries(2))
    lost_id = seed_copy(client, owner, make_entries(2))

    async def _age() -> None:
        old = datetime.now(UTC) - timedelta(days=91)
        await FrozenCopy.filter(id__in=[UUID(kept_id), UUID(lost_id)]).update(sealed_at=old)

    run_async(client, _age)
    claimer = _claim_client(client)

    resp = claimer.post(_claim_path(kept_id), headers={"X-User-Email": CLAIMER})

    assert resp.status_code == 200
    assert resp.json()["already"] is False
    assert _read_copy(client, kept_id).claimed_at is not None
    no_env_file: dict[str, Any] = {"_env_file": None}
    sweep = build_frozen_copy_sweep(Settings(**no_env_file))
    report = run_async(client, lambda: sweep.run_pass(trigger="command"))
    assert report.marked["expired"] == 1
    kept = _read_copy(client, kept_id)
    assert kept.status == "sealed"
    assert len(stored_entries(client, kept_id)) == 2
    # WHY the second copy: without it this test passes when the builder has no expiry rule.
    assert _read_copy(client, lost_id).status == "expired"
