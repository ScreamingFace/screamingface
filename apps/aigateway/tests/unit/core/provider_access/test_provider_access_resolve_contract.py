"""Port contract — `resolve` (OME-1200, spec §3.3 op 2; op 1 `defaults_for` deleted at E2b).

Runs over the pure fake here; `test_connection_backed_resolve_contract` re-runs it over the real
port on a migrated pair (the Profile-backed run retired with its implementation, OME-1209 E4a).
# INVARIANT: the refusal for each situation is part of the contract; an implementation that
# cannot serve the pair's target refuses — it never answers with a different target.
# FEATURE: OME-1138 close-out, L4a — the default is the only selector since the Stage D sunset, so
# every situation resolves it; "a stored credential" is the pair's effective Connection on both
# witnesses.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

import pytest
from provider_access_harness import (
    ANTHROPIC,
    PROVIDER,
    FakeHarness,
    FakeProviderAccess,
    Harness,
)

from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.store import credential_key_for
from aigateway.core.provider_access import (
    CredentialTarget,
    ResolvePolicy,
    Selector,
    SelectorAmbiguous,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
)
from tests.unit.seed_state import SeedState

DEFAULT = Selector.from_header(None)


class _SeededHarness(Harness, Protocol):
    """A harness that names each seeded credential's effective Connection — both witnesses do."""

    @property
    def migrated(self) -> dict[str, str]: ...


class _ApiKeyOnlyPlugin:
    custom_llm_provider = "keyed"

    def available_auth_modes(self) -> tuple[str, ...]:
        return ("api_key",)

    def allows_chatless_credential(self) -> bool:
        return False

    def credentialless_auth_mode(self) -> str | None:
        return None


class _NoCredentialPlugin:
    custom_llm_provider = "local"

    def available_auth_modes(self) -> tuple[str, ...]:
        return ("none",)

    def allows_chatless_credential(self) -> bool:
        return True

    def credentialless_auth_mode(self) -> str | None:
        return None


class _AmbientPlugin:
    custom_llm_provider = "ambient"

    def available_auth_modes(self) -> tuple[str, ...]:
        return ("oauth",)

    def allows_chatless_credential(self) -> bool:
        return True

    def credentialless_auth_mode(self) -> str | None:
        return "oauth"


@pytest.fixture(params=["fake"])
def harness() -> Harness:
    return FakeHarness()


def _resolve(
    harness: Harness,
    selector: Selector,
    *,
    plugin: Any = ANTHROPIC,
    policy: ResolvePolicy = ResolvePolicy.DISPATCH,
) -> CredentialTarget:
    return harness.call(
        harness.access.resolve,
        harness.account_id,
        PROVIDER,
        selector,
        plugin=plugin,
        policy=policy,
    )


# --- no target at all ---------------------------------------------------------------------------


def test_without_any_target_the_dispatch_policy_refuses_as_missing(harness: Harness) -> None:
    with pytest.raises(TargetMissing) as info:
        _resolve(harness, DEFAULT)

    assert (info.value.provider, info.value.requested) == (PROVIDER, DEFAULT.name)


def test_the_datasheet_policy_permits_an_absent_target(harness: Harness) -> None:
    """Today's `missing_target_ok=profile_name == "default"` (OME-1167), as a policy."""
    target = _resolve(harness, DEFAULT, plugin=_ApiKeyOnlyPlugin(), policy=ResolvePolicy.DATASHEET)

    assert target.kind == "none"
    assert target.credential_name is None
    assert target.reauth_url is None
    assert target.context_stamp == f"acct:{harness.account_id}|anon"


def test_a_provider_that_needs_no_credential_yields_the_none_kind(harness: Harness) -> None:
    target = _resolve(harness, DEFAULT, plugin=_NoCredentialPlugin())

    assert target.kind == "none"
    assert target.context_stamp == f"acct:{harness.account_id}|anon"


def test_a_provider_with_an_ambient_credential_yields_the_ambient_kind(harness: Harness) -> None:
    target = _resolve(harness, DEFAULT, plugin=_AmbientPlugin())

    assert target.kind == "ambient"
    assert target.credential_name is None


# --- a stored credential: the pair's effective Connection --------------------------------------


def test_an_authenticated_default_resolves_to_a_stored_target(harness: Harness) -> None:
    harness.seed_credential()

    target = _resolve(harness, DEFAULT)

    assert target.kind == "stored"
    assert target.auth_type == "oauth"
    # INVARIANT (no re-entry): the target reads the blob at the credential's name address.
    assert target.credential_name == credential_name_for(harness.account_id, "default")
    assert target.reauth_url == "/v1/oauth/connections"
    assert target.context_stamp.startswith(f"acct:{harness.account_id}|conn:")
    assert ":active:" in target.context_stamp


def test_an_api_key_profile_carries_the_api_key_reauth_url(harness: _SeededHarness) -> None:
    # WHY the effective Connection's own route: the re-key replaces the row chat reads (OME-1209
    # E1), so the URL names it.
    harness.seed_credential(name="work", auth_type="api_key", credential="sk-1")

    target = _resolve(harness, DEFAULT)

    assert target.auth_type == "api_key"
    assert target.reauth_url == f"/v1/oauth/connections/{harness.migrated['work']}/api-key"


def test_a_pending_profile_is_refused_as_pending(harness: Harness) -> None:
    harness.seed_credential(state=SeedState.PENDING, credential=None)

    with pytest.raises(TargetPending) as info:
        _resolve(harness, DEFAULT)

    assert (info.value.provider, info.value.requested) == (PROVIDER, "default")


def test_an_errored_profile_is_refused_with_the_legacy_reauth_url(harness: Harness) -> None:
    """The resolve-time 401 names the Connection list even for an api-key profile: the target is
    unknown before resolve succeeds."""
    harness.seed_credential(name="work", state=SeedState.ERROR, auth_type="api_key")

    with pytest.raises(TargetReauthRequired) as info:
        _resolve(harness, DEFAULT)

    assert info.value.reauth_url == "/v1/oauth/connections"
    assert info.value.requested == DEFAULT.name
    assert info.value.message is None


def test_a_profile_wins_over_an_active_connection(harness: Harness) -> None:
    harness.seed_credential()
    harness.seed_connection(label="work")

    target = _resolve(harness, DEFAULT)

    assert target.credential_name == credential_name_for(harness.account_id, "default")


# --- a pair with no effective Connection: its one active row --------------------------------


def test_a_single_active_connection_serves_the_default_selector(harness: Harness) -> None:
    connection_id = harness.seed_connection(label="work")

    target = _resolve(harness, DEFAULT)

    assert target.kind == "stored"
    assert target.credential_name == credential_key_for(harness.account_id, UUID(connection_id))
    assert target.context_stamp.startswith(
        f"acct:{harness.account_id}|conn:{connection_id}:active:"
    )
    assert target.reauth_url == "/v1/oauth/connections"


def test_two_active_connections_make_the_default_selector_ambiguous(harness: Harness) -> None:
    harness.seed_connection(label="work")
    harness.seed_connection(label="personal")

    with pytest.raises(SelectorAmbiguous) as info:
        _resolve(harness, DEFAULT)

    assert info.value.provider == PROVIDER


def test_a_default_label_does_not_disambiguate_two_active_connections(harness: Harness) -> None:
    harness.seed_connection(label="default")
    harness.seed_connection(label="backup")

    with pytest.raises(SelectorAmbiguous) as info:
        _resolve(harness, DEFAULT)

    assert info.value.provider == PROVIDER


def test_an_api_key_connection_reauths_through_its_own_replace_route(harness: Harness) -> None:
    connection_id = harness.seed_connection(label="work", auth_type="api_key")

    target = _resolve(harness, DEFAULT)

    assert target.auth_type == "api_key"
    assert target.reauth_url == f"/v1/oauth/connections/{connection_id}/api-key"


# --- refuse, never retarget -----------------------------------------------------------------


def _assert_never_retargets(harness: Harness) -> None:
    harness.seed_credential(state=SeedState.ERROR)
    harness.seed_connection(label="work")
    with pytest.raises(TargetReauthRequired):
        _resolve(harness, DEFAULT)


def test_an_implementation_refuses_a_target_it_cannot_serve(harness: Harness) -> None:
    _assert_never_retargets(harness)


class _RetargetingFake(FakeProviderAccess):
    """The wrong implementation: an unusable stored credential falls back to another row."""

    async def resolve(self, account_id: str, provider: str, selector: Selector, **kw: Any) -> Any:
        try:
            return await super().resolve(account_id, provider, selector, **kw)
        except (TargetPending, TargetReauthRequired):
            self.references.pop((account_id, provider), None)
            return await super().resolve(account_id, provider, selector, **kw)


def test_a_fake_that_retargets_fails_the_contract() -> None:
    harness = FakeHarness()
    harness.access = _RetargetingFake()

    with pytest.raises(pytest.fail.Exception):
        _assert_never_retargets(harness)
