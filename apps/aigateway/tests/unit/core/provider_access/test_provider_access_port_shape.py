"""The port's DECLARED shape against spec §3.3 (OME-1200, review finding F1/F3).

# INVARIANT: the two Protocols name exactly the operations the spec approves, with the spec's
# parameter shapes, so A2/A3 add implementations — never re-cut the port. Both witnesses
# (the fake and the Profile-backed implementation) satisfy the read interface structurally.
"""

from __future__ import annotations

import inspect
from inspect import Parameter
from types import SimpleNamespace
from typing import Any

import pytest
from provider_access_fake import FakeProviderAccess
from provider_access_harness import ANTHROPIC, PROVIDER, FakeHarness, Harness, ProfileBackedHarness

from aigateway.core.provider_access import (
    AvailabilityRow,
    CredentialSummary,
    ProfileBackedProviderAccess,
    ProviderAccess,
    ProviderCredentialAdmin,
    Selector,
    UnsupportedAuthMode,
)

KW = Parameter.KEYWORD_ONLY
POS = Parameter.POSITIONAL_OR_KEYWORD


def _params(fn: Any) -> dict[str, Parameter]:
    params = dict(inspect.signature(fn, eval_str=True).parameters)
    params.pop("self", None)
    return params


def _returns(fn: Any) -> Any:
    return inspect.signature(fn, eval_str=True).return_annotation


# --- ProviderAccess (spec ops 1–6) ---------------------------------------------------------


def test_the_read_interface_declares_the_six_spec_operations() -> None:
    declared = {
        name
        for name, member in vars(ProviderAccess).items()
        if callable(member) and not name.startswith("_")
    }

    assert declared == {
        "defaults_for",
        "resolve",
        "auth_mode",
        "contract_auth_mode",
        "authorize",
        "record_dispatch_failure",
        "availability",
    }


@pytest.mark.parametrize("name", ["auth_mode", "contract_auth_mode"])
def test_the_mode_operations_take_target_and_plugin_positionally(name: str) -> None:
    params = _params(getattr(ProviderAccess, name))

    assert [(p.name, p.kind) for p in params.values()] == [("target", POS), ("plugin", POS)]
    assert not inspect.iscoroutinefunction(getattr(ProviderAccess, name))


def test_record_dispatch_failure_takes_status_and_detail_then_the_plugin_by_keyword() -> None:
    params = _params(ProviderAccess.record_dispatch_failure)

    assert [(p.name, p.kind) for p in params.values()] == [
        ("target", POS),
        ("status", POS),
        ("detail", POS),
        ("plugin", KW),
    ]
    assert params["status"].annotation is int


def test_availability_is_account_scoped_and_returns_rows_only() -> None:
    params = _params(ProviderAccess.availability)

    assert list(params) == ["account_id"]
    assert _returns(ProviderAccess.availability) == tuple[AvailabilityRow, ...]


# --- ProviderCredentialAdmin (spec ops 7–9) --------------------------------------------------


def test_the_admin_listing_returns_a_tuple_of_summaries() -> None:
    params = _params(ProviderCredentialAdmin.list)

    assert list(params) == ["account_id", "provider"]
    assert params["provider"].default is None
    assert _returns(ProviderCredentialAdmin.list) == tuple[CredentialSummary, ...]


def test_set_api_key_is_pair_addressed_with_the_window_compatible_keywords() -> None:
    params = _params(ProviderCredentialAdmin.set_api_key)

    assert [(p.name, p.kind) for p in params.values()] == [
        ("account_id", POS),
        ("provider", POS),
        ("raw_api_key", KW),
        ("legacy_name", KW),
    ]


def test_delete_is_pair_addressed_and_names_the_legacy_profile_by_keyword() -> None:
    params = _params(ProviderCredentialAdmin.delete)

    assert [(p.name, p.kind) for p in params.values()] == [
        ("account_id", POS),
        ("provider", POS),
        ("legacy_name", KW),
    ]


# --- both witnesses satisfy the read interface ----------------------------------------------


def test_both_witnesses_satisfy_the_read_interface_structurally() -> None:
    app = SimpleNamespace(state=SimpleNamespace())

    assert isinstance(FakeProviderAccess(), ProviderAccess)
    assert isinstance(ProfileBackedProviderAccess(app), ProviderAccess)


@pytest.fixture(params=["fake", "profile_backed"])
def harness(request: pytest.FixtureRequest) -> Harness:
    if request.param == "fake":
        return FakeHarness()
    return ProfileBackedHarness(
        request.getfixturevalue("authenticated_client"),
        request.getfixturevalue("credential_blobs"),
        request.getfixturevalue("monkeypatch"),
    )


class _ApiKeyOnlyPlugin:
    custom_llm_provider = "keyed"

    def available_auth_modes(self) -> tuple[str, ...]:
        return ("api_key",)

    def allows_chatless_profile(self) -> bool:
        return False

    def profileless_auth_mode(self) -> str | None:
        return None


def test_the_mode_operations_answer_through_the_port(harness: Harness) -> None:
    harness.seed_profile()
    target = harness.call(
        harness.access.resolve,
        harness.account_id,
        PROVIDER,
        Selector.from_header(None),
        plugin=ANTHROPIC,
    )

    assert harness.access.auth_mode(target, ANTHROPIC) == "oauth"
    assert harness.access.contract_auth_mode(target, ANTHROPIC) == "oauth"
    with pytest.raises(UnsupportedAuthMode):
        harness.access.auth_mode(target, _ApiKeyOnlyPlugin())
