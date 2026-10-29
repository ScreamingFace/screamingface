"""Resolve and availability read no Profile document (OME-1209, Stage E, E4a; spec §9 Q8, Q9).

# FEATURE: Stage E plan §3 E4a — the pair marker alone decides how a pair resolves. An absent or
# `none` marker resolves through the pair's Connections (the label path, chatless or ambient), a
# `quarantined` marker fails closed with the D18 pair refusal, and a `migrated` marker serves its
# effective Connection when it names one and the label path otherwise.
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
    PairNotManageable,
    ResolvePolicy,
    Selector,
    SelectorUnknown,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
)
from tests.unit.seed_state import SeedState

DEFAULT = Selector.from_header(None)
CHAT_COMPLETION = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)
UNRESOLVED = {
    "code": "credential_pair_unresolved",
    "message": (
        "The provider credential cannot be managed safely. Resolve its state before retrying."
    ),
    "provider": PROVIDER,
}


@pytest.fixture
def h(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _resolve(h: ConnectionBackedHarness, policy: ResolvePolicy = ResolvePolicy.DISPATCH) -> Any:
    return h.call(
        h.access.resolve, h.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC, policy=policy
    )


def _resolve_named(h: ConnectionBackedHarness, name: str) -> Any:
    return h.call(
        h.access.resolve, h.account_id, PROVIDER, Selector.from_header(name), plugin=ANTHROPIC
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
            migration_note="seeded by the test" if state == "quarantined" else None,
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


# --- `quarantined`: fail closed ------------------------------------------------------------------


@pytest.mark.parametrize("policy", list(ResolvePolicy), ids=lambda policy: policy.value)
def test_a_quarantined_pair_refuses_with_the_pair_code_and_reads_no_index(
    h: ConnectionBackedHarness, policy: ResolvePolicy
) -> None:
    h.seed_blob(credential="tok")
    h.seed_connection(label="work")
    _mark(h, "quarantined")

    with pytest.raises(PairNotManageable) as refused:
        _resolve(h, policy)

    assert (refused.value.provider, refused.value.kind) == (PROVIDER, "unresolved")


def test_chat_and_model_parameters_answer_a_quarantined_pair_with_409_unresolved(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.seed_blob(credential="tok")
    _mark(h, "quarantined")

    async def never(_self: Any, _body: dict[str, Any]) -> Any:
        raise AssertionError("a refused pair must not reach the provider")

    monkeypatch.setattr(CHAT_COMPLETION, never)
    chat = h.client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    parameters = h.client.get("/v1/model-parameters", params={"model": "anthropic/claude-opus-4-8"})

    assert (chat.status_code, chat.json()["detail"]) == (409, UNRESOLVED)
    assert (parameters.status_code, parameters.json()["detail"]) == (409, UNRESOLVED)


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


def test_a_named_selector_on_a_migrated_pair_is_refused_not_served_by_the_effective_row(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_authority(label="work")

    with pytest.raises(SelectorUnknown) as refused:
        _resolve_named(h, "nope")

    assert (refused.value.requested, refused.value.valid_labels) == ("nope", ("work",))


def test_a_named_selector_on_a_migrated_pair_matches_its_connection_by_label(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_authority(label="work")
    other = h.seed_connection(label="other")

    target = _resolve_named(h, "other")

    assert target.context_stamp.startswith(_stamp_of(h, other))


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


# --- availability: quarantine and the effective reference (label rule: its own module) ----------


def test_availability_reports_no_profile_state_and_reads_no_index(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_blob()

    statuses = _statuses(h)

    registered = {plugin.custom_llm_provider for plugin in h.client.app.state.providers.all()}
    assert set(statuses) == registered
    assert set(statuses.values()) == {"not_connected"}


@pytest.mark.parametrize("state", ["quarantined"])
def test_availability_reports_a_non_migrated_pair_as_not_connected(
    h: ConnectionBackedHarness, state: MigrationState
) -> None:
    h.seed_blob()
    h.seed_connection(label="work")
    _mark(h, state)

    assert _statuses(h)[PROVIDER] == "not_connected"


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
