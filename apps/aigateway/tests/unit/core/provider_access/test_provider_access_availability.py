"""`ProviderAccess.availability` (OME-1230, Stage A3; spec §3.3 op 6, D17).

# FEATURE: the caller-scoped provider availability listing, gateway-side, so the Hosted Engine can
# stop aggregating raw Profile listings at A4.
# INVARIANT (spec op 6): no secret read, no refresh, no mutation; rows carry provider and status
# ONLY.
# INVARIANT (OME-1209, Stage E, E4a): availability reads no Profile document, so the golden
# equivalence to the Engine's Profile-listing rule (authenticated > pending > error) retired with
# it. Since the D17 fold-in (OME-1138) a provider lists by the rule its default chat resolve
# follows: a migrated pair's effective Connection (`test_connection_only_resolve.py`), any other
# pair its Connections by label (`test_availability_follows_resolve.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

import pytest
from connection_backed_harness import ConnectionBackedHarness
from provider_access_fake import PROVIDER, FakeHarness
from provider_access_harness import Harness

from aigateway.core.provider_access import AvailabilityRow, AvailabilityStatus
from tests.unit.seed_state import SeedState


class _Seam:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.app = client.app
        self.access = client.app.state.provider_access
        self.account_id: str = client.get("/v1/auth/me").json()["id"]
        self.registered: set[str] = {
            plugin.custom_llm_provider for plugin in client.app.state.providers.all()
        }

    def call(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        return self.client.portal.call(partial(fn, *args, **kwargs))

    def rows(self) -> tuple[AvailabilityRow, ...]:
        return self.call(self.access.availability, self.account_id)


@pytest.fixture
def seam(authenticated_client, credential_blobs) -> _Seam:
    return _Seam(authenticated_client)


def test_availability_rows_carry_provider_and_status_only_sorted_by_provider(seam: _Seam) -> None:
    rows = seam.rows()

    assert isinstance(rows, tuple)
    assert [row.provider for row in rows] == sorted(row.provider for row in rows)
    assert all(set(vars(row)) == {"provider", "status"} for row in rows)
    assert "needs_reauth" not in {row.status for row in rows}


# --- the fake witness agrees with the real backing for the default selector -------------------


def _errored_beside_an_active_row(harness: Harness) -> None:
    harness.seed_credential(state=SeedState.ERROR)
    harness.seed_connection(label="work")


def _two_active_rows(harness: Harness) -> None:
    harness.seed_connection(label="work")
    harness.seed_connection(label="personal")


# WHY these situations: they are the ones both witnesses can seed — a stored credential (the
# pair's effective Connection) in each state, and plain active Connections with no marker.
_SITUATIONS: dict[str, tuple[Callable[[Harness], Any], AvailabilityStatus]] = {
    "authenticated": (lambda harness: harness.seed_credential(), "connected"),
    "pending": (
        lambda harness: harness.seed_credential(state=SeedState.PENDING, credential=None),
        "pending",
    ),
    "errored": (lambda harness: harness.seed_credential(state=SeedState.ERROR), "error"),
    "errored-beside-active": (_errored_beside_an_active_row, "error"),
    "one-active-row": (lambda harness: harness.seed_connection(label="work"), "connected"),
    "two-active-rows": (_two_active_rows, "error"),
}


def _status(harness: Harness) -> AvailabilityStatus:
    rows = harness.call(harness.access.availability, harness.account_id)
    return next(row.status for row in rows if row.provider == PROVIDER)


@pytest.mark.parametrize("situation", list(_SITUATIONS))
def test_the_fake_witness_agrees_with_the_real_backing(
    situation: str, authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> None:
    # FEATURE: OME-1138 close-out, L4a — the fake lists by the rule the real backing follows for
    # the default selector, the only one since the Stage D sunset; it seeds no Profile.
    seed, expected = _SITUATIONS[situation]
    fake = FakeHarness()
    real = ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)

    seed(fake)
    seed(real)

    assert _status(fake) == _status(real) == expected
