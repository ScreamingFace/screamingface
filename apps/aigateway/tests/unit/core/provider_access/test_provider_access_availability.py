"""`ProviderAccess.availability` (OME-1230, Stage A3; spec §3.3 op 6, D17).

# FEATURE: the caller-scoped provider availability listing, gateway-side, so the Hosted Engine can
# stop aggregating raw Profile listings at A4.
# INVARIANT (spec op 6): no secret read, no refresh, no mutation; rows carry provider and status
# ONLY; `needs_reauth` is never emitted in the window.
# INVARIANT (golden): the status per provider equals the Engine rule in
# `screamingface_engine/connections/profile_availability.py::decode_profile_statuses`
# (authenticated > pending > error) applied to today's `GET /v1/auth/profiles` body, and a
# registered provider with no Profile row shows `not_connected` — the Engine's "none" case.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

import pytest
from provider_access_fake import FakeHarness

from aigateway.core.profile_index import INDEX_CREDENTIAL_SERVICE, ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.core.provider_access import AvailabilityRow
from aigateway.core.provider_access import profile_authorize as authorize_module

_ENGINE_STATES = frozenset({"pending", "authenticated", "error"})


def _engine_rule(body: dict[str, Any]) -> dict[str, str]:
    """A faithful re-statement of the Engine's `decode_profile_statuses` + `_public_status`.

    # WHY re-stated rather than imported: the Engine is a separate deployable with its own venv;
    # the gateway test suite cannot import it. The rule is three lines and is pinned here so a
    # drift in either copy shows up as a red test on one side.
    """
    states_by_provider: dict[str, set[str]] = {}
    for profile in body["profiles"]:
        assert profile["state"] in _ENGINE_STATES
        states_by_provider.setdefault(profile["provider"], set()).add(profile["state"])
    decoded: dict[str, str] = {}
    for provider, states in states_by_provider.items():
        if "authenticated" in states:
            decoded[provider] = "connected"
        elif "pending" in states:
            decoded[provider] = "pending"
        else:
            decoded[provider] = "error"
    return decoded


# Recorded listing shapes: every ordering of the three states, per provider, plus mixes.
_LISTINGS: list[list[tuple[str, str]]] = [
    [],
    [("anthropic", "authenticated")],
    [("anthropic", "pending")],
    [("anthropic", "error")],
    [("anthropic", "error"), ("anthropic", "pending")],
    [("anthropic", "pending"), ("anthropic", "error"), ("anthropic", "authenticated")],
    [("anthropic", "error"), ("anthropic", "error")],
    [("anthropic", "authenticated"), ("gemini", "pending"), ("codex", "error")],
    [("gemini", "error"), ("gemini", "authenticated"), ("anthropic", "pending")],
]


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


# --- the Engine rule, gateway-side --------------------------------------------------------


@pytest.mark.parametrize(
    "listing", _LISTINGS, ids=lambda rows: ",".join(f"{p}:{s}" for p, s in rows) or "empty"
)
def test_availability_is_golden_equivalent_to_the_engine_rule(seam: _Seam, listing) -> None:
    for provider, state in listing:
        seam.seed(provider, state)
    body = {
        "profiles": [p.model_dump(mode="json") for p in seam.call(seam.index.list, seam.account_id)]
    }
    expected = _engine_rule(body)

    rows = seam.rows()

    by_provider = {row.provider: row.status for row in rows}
    # Every provider the Engine decodes agrees; every other registered provider is the
    # Engine's "none" case, `not_connected`.
    assert {p: s for p, s in by_provider.items() if p in expected} == expected
    assert {p for p, s in by_provider.items() if p not in expected} == seam.registered - set(
        expected
    )
    assert all(s == "not_connected" for p, s in by_provider.items() if p not in expected)
    assert set(by_provider) == seam.registered | set(expected)


def test_availability_rows_carry_provider_and_status_only_sorted_by_provider(seam: _Seam) -> None:
    seam.seed("gemini", "authenticated")
    seam.seed("anthropic", "pending")

    rows = seam.rows()

    assert isinstance(rows, tuple)
    assert [row.provider for row in rows] == sorted(row.provider for row in rows)
    assert all(set(vars(row)) == {"provider", "status"} for row in rows)
    assert "needs_reauth" not in {row.status for row in rows}


def test_availability_reads_only_the_index_and_writes_nothing(seam: _Seam, monkeypatch) -> None:
    seam.seed("anthropic", "authenticated")
    seam.seed("anthropic", "error")
    store = seam.app.state.credential_store
    real_read = store.read
    services_read: list[str] = []

    async def _spy_read(service: str, account: str) -> str | None:
        services_read.append(service)
        return await real_read(service, account)

    def _no_strategy(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("availability must not build a credential strategy")

    async def _no_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("availability must not write")

    monkeypatch.setattr(store, "read", _spy_read)
    monkeypatch.setattr(authorize_module, "credential_strategy_from", _no_strategy)
    for name in ("write", "mutate", "delete"):
        monkeypatch.setattr(store, name, _no_write)
    for name in (
        "upsert",
        "remove",
        "mark_authenticated_error",
        "mark_pending_error",
        "update_metadata",
    ):
        monkeypatch.setattr(seam.index, name, _no_write)

    rows = seam.rows()

    assert {row.provider: row.status for row in rows}["anthropic"] == "connected"
    assert services_read
    assert set(services_read) == {INDEX_CREDENTIAL_SERVICE}


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
