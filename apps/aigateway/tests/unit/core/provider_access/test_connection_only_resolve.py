"""Resolve and availability read no Profile document (OME-1209, Stage E, E4a; spec §9 Q8, Q9).

# FEATURE: Stage E plan §3 E4a — the pair marker alone decides how a pair resolves. An absent or
# `none` marker resolves through the pair's Connections (the label path, chatless or ambient), and
# a `migrated` marker serves its effective Connection when it names one and the label path
# otherwise. Any other stored state is refused as unknown (OME-1138 close-out, L4a:
# `test_compatibility_paths_retired.py`).
# INVARIANT: a blob left at a pair's name address is never a credential target and never a status
# on its own; only the marker and the pair's Connections decide.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import (
    MigrationState,
    PairAuthorityStore,
    ResolvePolicy,
    Selector,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
)
from tests.unit.seed_state import SeedState

DEFAULT = Selector.from_header(None)
CHAT_COMPLETION = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)


@pytest.fixture
def h(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _resolve(h: ConnectionBackedHarness, policy: ResolvePolicy = ResolvePolicy.DISPATCH) -> Any:
    return h.call(
        h.access.resolve, h.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC, policy=policy
    )


def _mark(
    h: ConnectionBackedHarness, state: MigrationState, *, effective: str | None = None
) -> None:
    async def advance() -> None:
        current = await PairAuthorityStore().read(h.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            h.account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state=state,
            effective_connection_id=None if effective is None else UUID(effective),
        )

    h.call(advance)


def _stamp_of(h: ConnectionBackedHarness, connection_id: str) -> str:
    return f"acct:{h.account_id}|conn:{connection_id}:active:"


def _statuses(h: ConnectionBackedHarness) -> dict[str, str]:
    rows = h.call(h.access.availability, h.account_id)
    return {row.provider: row.status for row in rows}


# --- absent and `none` markers: the pair's Connections ------------------------------------------


def test_an_unmarked_pair_resolves_its_one_active_connection_without_the_index(
    h: ConnectionBackedHarness,
) -> None:
    connection_id = h.seed_connection(label="work")

    target = _resolve(h)

    assert target.kind == "stored"
    assert target.context_stamp.startswith(_stamp_of(h, connection_id))


def test_an_unmarked_pair_reads_its_marker_once_per_resolve(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (D14): one authority per pair per call — the marker is read once, at the top.
    h.seed_connection(label="work")
    reads: list[tuple[str, str]] = []
    real = PairAuthorityStore.read

    async def counting(self: PairAuthorityStore, account_id: str, provider: str) -> Any:
        reads.append((account_id, provider))
        return await real(self, account_id, provider)

    monkeypatch.setattr(PairAuthorityStore, "read", counting)

    _resolve(h)

    assert reads == [(h.account_id, PROVIDER)]


@pytest.mark.parametrize("refreshed", [True, False], ids=["refreshed", "never-refreshed"])
def test_a_connection_target_stamps_its_id_status_and_refresh_time(
    h: ConnectionBackedHarness, refreshed: bool
) -> None:
    connection_id = h.seed_connection(label="work")
    if not refreshed:

        async def never_refreshed() -> None:
            await OAuthConnection.filter(id=connection_id).update(last_refreshed_at=None)

        h.call(never_refreshed)
    connection = h.call(OAuthConnectionStore().get, h.account_id, connection_id)
    assert connection is not None

    target = _resolve(h)

    stamp = connection.last_refreshed_at if refreshed else "-"
    assert target.context_stamp == f"acct:{h.account_id}|conn:{connection_id}:active:{stamp}"


def test_chat_dispatches_the_connection_beside_a_default_profile_document(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.seed_blob(credential="document-tok")
    h.seed_connection(label="work", credential="connection-tok")
    captured: dict[str, Any] = {}

    async def answered(_self: Any, body: dict[str, Any]) -> dict[str, Any]:
        captured.update(body)
        return {
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }

    monkeypatch.setattr(CHAT_COMPLETION, answered)
    resp = h.client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 200, resp.text
    assert captured["api_key"] == "connection-tok"


def test_a_lone_profile_document_is_not_a_target_of_an_unmarked_pair(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_blob(credential="tok")

    with pytest.raises(TargetMissing):
        _resolve(h)


def test_a_none_pair_resolves_its_connection_even_beside_a_profile_document(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_blob(credential="tok")
    connection_id = h.seed_connection(label="work")
    _mark(h, "none")

    target = _resolve(h)

    assert target.context_stamp.startswith(_stamp_of(h, connection_id))
    observed = target._observed_pair
    assert observed is not None
    assert (observed.migration_state, observed.generation) == ("none", 1)


def test_the_datasheet_answers_an_unmarked_pair_targetless_despite_a_profile_document(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_blob(credential="tok")

    target = _resolve(h, ResolvePolicy.DATASHEET)

    assert (target.kind, target.credential_name) == ("none", None)
    assert target.context_stamp == f"acct:{h.account_id}|anon"


# --- `migrated`: the effective Connection when named, else the label path -----------------------


def test_a_migrated_pair_serves_its_named_effective_connection_beside_another_row(
    h: ConnectionBackedHarness,
) -> None:
    effective = h.seed_authority()
    h.seed_connection(label="extra")

    target = _resolve(h)

    assert target.context_stamp.startswith(_stamp_of(h, effective))
    assert target.credential_name == credential_name_for(h.account_id, "default")


def test_a_migrated_pair_with_no_effective_connection_takes_the_label_path(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_blob(credential="tok")
    connection_id = h.seed_connection(label="work")
    _mark(h, "migrated")

    target = _resolve(h)

    assert target.context_stamp.startswith(_stamp_of(h, connection_id))


def test_a_disconnected_migrated_pair_with_no_connection_is_missing(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_blob(credential="tok")
    _mark(h, "migrated")

    with pytest.raises(TargetMissing):
        _resolve(h)


@pytest.mark.parametrize(
    ("status", "refusal"),
    [("revoked", TargetMissing), ("error", TargetReauthRequired), ("pending", TargetPending)],
)
def test_an_unusable_effective_connection_is_refused_beside_an_active_sibling(
    h: ConnectionBackedHarness, status: str, refusal: type[Exception]
) -> None:
    # INVARIANT: the marker's reference is the pair's target; an active sibling never stands in
    # for it (refuse, never retarget).
    effective = h.seed_authority()
    h.seed_connection(label="sibling")

    async def move() -> None:
        await OAuthConnection.filter(id=UUID(effective)).update(status=status)

    h.call(move)

    with pytest.raises(refusal):
        _resolve(h)


# --- availability: the effective reference (label rule: its own module) ------------------------


def test_availability_reports_no_profile_state_and_reads_no_index(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_blob()

    statuses = _statuses(h)

    registered = {plugin.custom_llm_provider for plugin in h.client.app.state.providers.all()}
    assert set(statuses) == registered
    assert set(statuses.values()) == {"not_connected"}


@pytest.mark.parametrize(
    ("state", "status"),
    [(SeedState.AUTHENTICATED, "connected"), (SeedState.ERROR, "error")],
    ids=["active", "error"],
)
def test_availability_reports_a_migrated_pair_by_its_effective_connection(
    h: ConnectionBackedHarness, state: SeedState, status: str
) -> None:
    h.seed_authority(state=state)

    assert _statuses(h)[PROVIDER] == status
