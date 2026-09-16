"""Core helpers of the boundary: `auth_mode`, `contract_auth_mode`, `apply_defaults`,
`apply_authorization`, `reauth_url_for` (OME-1200, spec §3.3 op 3 and §3.4 rows 3–4).

# INVARIANT: these are provider-declared-mode and pure-merge helpers; none of them touches a
# store. Outcomes are pinned against today's `resolved_auth_mode` / `_contract_auth_mode` /
# `_apply_defaults` behaviour at 17048f5d.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from aigateway.core.profile_models import ProfileDefaults
from aigateway.core.provider_access import (
    CredentialTarget,
    UnsupportedAuthMode,
    apply_authorization,
    apply_defaults,
    auth_mode,
    contract_auth_mode,
    reauth_url_for,
)
from aigateway.routes.model_parameters import _contract_auth_mode as legacy_contract_auth_mode


class _Plugin:
    def __init__(
        self,
        modes: tuple[str, ...],
        *,
        chatless: bool = False,
        profileless: str | None = None,
        provider: str = "p",
        skip_default: str | None = None,
    ) -> None:
        self._modes = modes
        self._chatless = chatless
        self._profileless = profileless
        self.custom_llm_provider = provider
        self._skip = skip_default

    def available_auth_modes(self) -> tuple[str, ...]:
        return self._modes

    def allows_chatless_profile(self) -> bool:
        return self._chatless

    def profileless_auth_mode(self) -> str | None:
        return self._profileless

    def should_apply_profile_default(self, field: str) -> bool:
        return field != self._skip


def _target(kind: str, auth_type: str = "oauth") -> CredentialTarget:
    return CredentialTarget(
        kind=cast(Any, kind),
        auth_type=cast(Any, auth_type),
        credential_name="acct:default" if kind == "stored" else None,
        context_stamp="acct:a|anon",
        reauth_url=None,
        defaults=ProfileDefaults(),
        _backing=None,
    )


# --- auth_mode ------------------------------------------------------------------------------


def test_a_stored_target_uses_its_own_auth_type_when_the_provider_declares_it() -> None:
    assert (
        auth_mode(_target("stored", "api_key"), plugin=_Plugin(("oauth", "api_key"))) == "api_key"
    )
    assert auth_mode(_target("stored", "oauth"), plugin=_Plugin(("oauth",))) == "oauth"


def test_a_stored_target_with_an_undeclared_mode_is_unsupported() -> None:
    with pytest.raises(UnsupportedAuthMode) as info:
        auth_mode(_target("stored", "api_key"), plugin=_Plugin(("oauth",), provider="anthropic"))

    assert (info.value.auth_mode, info.value.provider) == ("api_key", "anthropic")


def test_an_unsupported_mode_carries_no_provider_when_the_plugin_names_none() -> None:
    with pytest.raises(UnsupportedAuthMode) as info:
        auth_mode(_target("none"), plugin=_Plugin(("api_key",), provider=""))

    assert info.value.provider is None


def test_a_target_less_result_takes_the_profileless_mode_first() -> None:
    assert auth_mode(_target("ambient"), plugin=_Plugin(("oauth",), profileless="api_key")) == (
        "api_key"
    )


def test_a_target_less_result_for_a_no_credential_provider_is_none() -> None:
    assert auth_mode(_target("none"), plugin=_Plugin(("none",), chatless=True)) == "none"


def test_a_target_less_result_falls_back_to_oauth_and_is_checked() -> None:
    assert auth_mode(_target("none"), plugin=_Plugin(("oauth",), chatless=True)) == "oauth"
    with pytest.raises(UnsupportedAuthMode):
        auth_mode(_target("none"), plugin=_Plugin(("api_key",)))


# --- contract_auth_mode (the keyless datasheet branch, OME-1167) ------------------------------


def test_the_datasheet_binds_a_keyless_api_key_only_provider_to_its_first_mode() -> None:
    plugin = _Plugin(("api_key",))

    assert contract_auth_mode(_target("none"), plugin=plugin) == "api_key"
    assert contract_auth_mode(_target("none"), plugin=plugin) == legacy_contract_auth_mode(
        cast(Any, plugin),
        None,
        None,
    )


def test_the_datasheet_prefers_the_profileless_mode_when_declared() -> None:
    plugin = _Plugin(("oauth", "api_key"), profileless="api_key")

    assert contract_auth_mode(_target("ambient"), plugin=plugin) == "api_key"


def test_the_datasheet_uses_the_dispatch_mode_for_stored_and_chatless_targets() -> None:
    assert contract_auth_mode(_target("stored", "oauth"), plugin=_Plugin(("oauth",))) == "oauth"
    assert contract_auth_mode(_target("none"), plugin=_Plugin(("none",), chatless=True)) == "none"


# --- apply_defaults -------------------------------------------------------------------------


def test_apply_defaults_fills_only_omitted_paths_and_reports_them() -> None:
    body: dict[str, Any] = {"model": "p/m", "messages": [{"role": "user", "content": "hi"}]}
    defaults = ProfileDefaults(
        system_prompt="be brief", max_tokens=8, temperature=0.2, timeout_seconds=9.5
    )

    merged, written = apply_defaults(body, defaults, _Plugin(("oauth",)))

    assert merged["messages"][0] == {"role": "system", "content": "be brief"}
    assert merged["max_tokens"] == 8
    assert merged["timeout"] == 9.5
    assert written == frozenset({"messages", "max_tokens", "temperature", "timeout"})


def test_apply_defaults_never_overrides_the_body_or_an_existing_system_message() -> None:
    body: dict[str, Any] = {
        "model": "p/m",
        "max_tokens": 1,
        "messages": [{"role": "system", "content": "mine"}],
    }

    merged, written = apply_defaults(
        body, ProfileDefaults(system_prompt="theirs", max_tokens=8), _Plugin(("oauth",))
    )

    assert merged["max_tokens"] == 1
    assert merged["messages"] == [{"role": "system", "content": "mine"}]
    assert written == frozenset()


def test_apply_defaults_honours_the_plugin_veto_per_field() -> None:
    body: dict[str, Any] = {"model": "p/m", "messages": []}

    merged, written = apply_defaults(
        body,
        ProfileDefaults(system_prompt="x", max_tokens=8),
        _Plugin(("oauth",), skip_default="system_prompt"),
    )

    assert "system" not in {m.get("role") for m in merged["messages"]}
    assert written == frozenset({"max_tokens"})


# --- apply_authorization + reauth_url_for ----------------------------------------------------


def test_apply_authorization_moves_the_bearer_into_api_key_and_merges_the_rest() -> None:
    body: dict[str, Any] = {"extra_headers": {"x-keep": "1"}}

    apply_authorization(body, {"Authorization": "Bearer tok", "anthropic-beta": "b"})

    assert body["api_key"] == "tok"
    assert body["extra_headers"] == {"x-keep": "1", "anthropic-beta": "b"}


def test_apply_authorization_with_no_headers_leaves_the_body_alone() -> None:
    body: dict[str, Any] = {"model": "x"}

    apply_authorization(body, {})

    assert body == {"model": "x"}


def test_apply_authorization_keeps_a_non_bearer_authorization_header_out_of_api_key() -> None:
    body: dict[str, Any] = {}

    apply_authorization(body, {"Authorization": "Basic abc"})

    assert "api_key" not in body
    assert "extra_headers" not in body


@pytest.mark.parametrize(
    ("auth_type", "connection_id", "expected"),
    [
        ("oauth", None, "/v1/auth/anthropic/profiles/work"),
        ("api_key", None, "/v1/auth/anthropic/profiles/work/api-key"),
        ("oauth", "c-1", "/v1/auth/anthropic/profiles/work"),
        ("api_key", "c-1", "/v1/oauth/connections/c-1/api-key"),
    ],
)
def test_reauth_url_for_matches_the_legacy_shapes(
    auth_type: str, connection_id: str | None, expected: str
) -> None:
    assert (
        reauth_url_for("anthropic", "work", cast(Any, auth_type), connection_id=connection_id)
        == expected
    )
