"""Port contract — `resolve` (OME-1200, spec §3.3 op 2; op 1 `defaults_for` deleted at E2b).

Runs over the pure fake here; `test_connection_backed_resolve_contract` re-runs it over the real
port on a migrated pair (the Profile-backed run retired with its implementation, OME-1209 E4a).
# INVARIANT: the refusal for each situation is part of the contract; an implementation that
# cannot honour a selector refuses — it never answers with a different target.
"""

from __future__ import annotations

from typing import Any
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
    SelectorUnknown,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
)
from tests.unit.seed_state import SeedState

DEFAULT = Selector.from_header(None)
WORK = Selector.from_header("work")


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


@pytest.mark.parametrize("selector", [DEFAULT, WORK], ids=["default", "named"])
def test_without_any_target_the_dispatch_policy_refuses_as_missing(
    harness: Harness, selector: Selector
) -> None:
    with pytest.raises(TargetMissing) as info:
        _resolve(harness, selector)

    assert (info.value.provider, info.value.requested) == (PROVIDER, selector.name)


def test_the_datasheet_policy_permits_an_absent_target_for_the_default_selector_only(
    harness: Harness,
) -> None:
    """Today's `missing_target_ok=profile_name == "default"` (OME-1167), as a policy."""
    target = _resolve(harness, DEFAULT, plugin=_ApiKeyOnlyPlugin(), policy=ResolvePolicy.DATASHEET)

    assert target.kind == "none"
    assert target.credential_name is None
    assert target.reauth_url is None
    assert target.context_stamp == f"acct:{harness.account_id}|anon"

    with pytest.raises(TargetMissing):
        _resolve(harness, WORK, plugin=_ApiKeyOnlyPlugin(), policy=ResolvePolicy.DATASHEET)


def test_a_provider_that_needs_no_credential_yields_the_none_kind(harness: Harness) -> None:
    target = _resolve(harness, DEFAULT, plugin=_NoCredentialPlugin())

    assert target.kind == "none"
    assert target.context_stamp == f"acct:{harness.account_id}|anon"


def test_a_provider_with_an_ambient_credential_yields_the_ambient_kind(harness: Harness) -> None:
    target = _resolve(harness, DEFAULT, plugin=_AmbientPlugin())

    assert target.kind == "ambient"
    assert target.credential_name is None


# --- a stored Profile -----------------------------------------------------------------------


def test_an_authenticated_default_resolves_to_a_stored_target(harness: Harness) -> None:
    harness.seed_credential()

    target = _resolve(harness, DEFAULT)

    assert target.kind == "stored"
    assert target.auth_type == "oauth"
    assert target.credential_name == credential_name_for(harness.account_id, "default")
    assert target.reauth_url == "/v1/oauth/connections"
    assert target.context_stamp.startswith(
        f"acct:{harness.account_id}|prof:{harness.account_id}:{PROVIDER}:default:authenticated:"
    )


def test_an_api_key_profile_carries_the_api_key_reauth_url(harness: Harness) -> None:
    harness.seed_credential(name="work", auth_type="api_key", credential="sk-1")

    target = _resolve(harness, WORK)

    assert target.auth_type == "api_key"
    assert target.reauth_url == "/v1/oauth/connections/api-key"


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
        _resolve(harness, WORK)

    assert info.value.reauth_url == "/v1/oauth/connections"
    assert info.value.requested == "work"
    assert info.value.message is None


def test_a_profile_wins_over_an_active_connection(harness: Harness) -> None:
    harness.seed_credential()
    harness.seed_connection(label="work")

    target = _resolve(harness, DEFAULT)

    assert target.credential_name == credential_name_for(harness.account_id, "default")


# --- Connections when no Profile matches ---------------------------------------------------


def test_a_single_active_connection_serves_the_default_selector(harness: Harness) -> None:
    connection_id = harness.seed_connection(label="work")

    target = _resolve(harness, DEFAULT)

    assert target.kind == "stored"
    assert target.credential_name == credential_key_for(harness.account_id, UUID(connection_id))
    assert target.context_stamp.startswith(
        f"acct:{harness.account_id}|conn:{connection_id}:active:"
    )
    assert target.reauth_url == "/v1/oauth/connections"


def test_a_label_selects_among_active_connections(harness: Harness) -> None:
    harness.seed_connection(label="work")
    personal = harness.seed_connection(label="personal")

    target = _resolve(harness, Selector.from_header("personal"))

    assert target.credential_name == credential_key_for(harness.account_id, UUID(personal))


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


def test_an_unknown_label_is_refused_with_the_valid_labels(harness: Harness) -> None:
    harness.seed_connection(label="work")
    harness.seed_connection(label="personal")

    with pytest.raises(SelectorUnknown) as info:
        _resolve(harness, Selector.from_header("nope"))

    assert info.value.requested == "nope"
    assert sorted(info.value.valid_labels) == ["personal", "work"]


def test_an_api_key_connection_reauths_through_its_own_replace_route(harness: Harness) -> None:
    connection_id = harness.seed_connection(label="work", auth_type="api_key")

    target = _resolve(harness, WORK)

    assert target.auth_type == "api_key"
    assert target.reauth_url == f"/v1/oauth/connections/{connection_id}/api-key"


# --- refuse, never retarget -----------------------------------------------------------------


def _assert_never_retargets(harness: Harness) -> None:
    harness.seed_credential()
    with pytest.raises((TargetMissing, SelectorUnknown)):
        _resolve(harness, Selector.from_header("nope"))


def test_an_implementation_refuses_a_selector_it_cannot_honour(harness: Harness) -> None:
    _assert_never_retargets(harness)


class _RetargetingFake(FakeProviderAccess):
    """The wrong implementation: an unknown named selector silently falls back to default."""

    async def resolve(self, account_id: str, provider: str, selector: Selector, **kw: Any) -> Any:
        try:
            return await super().resolve(account_id, provider, selector, **kw)
        except TargetMissing:
            return await super().resolve(account_id, provider, Selector.from_header(None), **kw)


def test_a_fake_that_retargets_fails_the_contract() -> None:
    harness = FakeHarness()
    harness.access = _RetargetingFake()

    with pytest.raises(pytest.fail.Exception):
        _assert_never_retargets(harness)
