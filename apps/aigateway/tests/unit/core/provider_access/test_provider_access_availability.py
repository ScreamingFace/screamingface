"""`ProviderAccess.availability` (OME-1230, Stage A3; spec §3.3 op 6, D17).

# FEATURE: the caller-scoped provider availability listing, gateway-side, so the Hosted Engine can
# stop aggregating raw Profile listings at A4.
# INVARIANT (spec op 6): no secret read, no refresh, no mutation; rows carry provider and status
# ONLY; `needs_reauth` is never emitted in the window.
# INVARIANT (OME-1209, Stage E, E4a): availability reads no Profile document, so the golden
# equivalence to the Engine's Profile-listing rule (authenticated > pending > error) retired with
# it. A registered provider shows `not_connected` unless its pair is migrated, which reports its
# effective Connection's status (`test_connection_only_resolve.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

import pytest
from provider_access_fake import FakeHarness

from aigateway.core.credential_names import profile_id_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.core.provider_access import AvailabilityRow


class _Seam:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.app = client.app
        self.access = client.app.state.provider_access
        self.account_id: str = client.get("/v1/auth/me").json()["id"]
        self.index: ProfileIndexStore = client.app.state.profile_index
        self.registered: set[str] = {
            plugin.custom_llm_provider for plugin in client.app.state.providers.all()
        }

    def call(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        return self.client.portal.call(partial(fn, *args, **kwargs))

    def seed(self, provider: str, state: str, name: str | None = None) -> None:
        name = name or f"{state}-{sum(1 for _ in self.call(self.index.list, self.account_id))}"
        self.call(
            self.index.upsert,
            Profile(
                id=profile_id_for(self.account_id, provider, name),
                account_id=self.account_id,
                provider=provider,
                name=name,
                state=ProfileState(state),
            ),
        )

    def rows(self) -> tuple[AvailabilityRow, ...]:
        return self.call(self.access.availability, self.account_id)


@pytest.fixture
def seam(authenticated_client, credential_blobs) -> _Seam:
    return _Seam(authenticated_client)


def test_availability_rows_carry_provider_and_status_only_sorted_by_provider(seam: _Seam) -> None:
    seam.seed("gemini", "authenticated")
    seam.seed("anthropic", "pending")

    rows = seam.rows()

    assert isinstance(rows, tuple)
    assert [row.provider for row in rows] == sorted(row.provider for row in rows)
    assert all(set(vars(row)) == {"provider", "status"} for row in rows)
    assert "needs_reauth" not in {row.status for row in rows}


# --- the fake witness agrees on the rule for providers it has rows for ----------------------


def test_the_fake_witness_applies_the_same_precedence() -> None:
    harness = FakeHarness()
    harness.seed_profile(name="a", state=ProfileState.ERROR)
    harness.seed_profile(name="b", state=ProfileState.PENDING)
    assert harness.call(harness.access.availability, harness.account_id) == (
        AvailabilityRow("anthropic", "pending"),
    )

    harness.seed_profile(name="c", state=ProfileState.AUTHENTICATED)
    assert harness.call(harness.access.availability, harness.account_id) == (
        AvailabilityRow("anthropic", "connected"),
    )
