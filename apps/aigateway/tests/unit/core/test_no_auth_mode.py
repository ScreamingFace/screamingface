"""OME-636: the explicit no-auth mode, and why it cannot be forged.

FEATURE: honest auth reporting for a provider that needs no credentials. The
gateway had only ``oauth`` and ``api_key``, so a local Ollama host resolved to
``oauth`` — a fiction, and the value every parameter rule, the summary
intersection and the detailed contract were then matched against.

STORY: as a caller on a local no-auth provider, the gateway tells me the mode is
``none`` instead of naming a credential type nobody holds; and as an operator, I
cannot store or send that mode, because it exists only as the OUTCOME of
resolution.

INVARIANT: PERSISTED credential types stay ``oauth | api_key``; the RESOLVED mode
is the separate, wider ``AuthMode``. The split is what makes ``none``
unforgeable — no persisted model or request schema ever widens to accept it, so
the type checker enforces it rather than a validation rule someone can forget.
INVARIANT: ``none`` is resolved from the PROVIDER's own declaration, never from a
missing profile. A provider that merely permits a profile-less request still
resolves to a real mode.

Retired at OME-1138 Stage E, E5c: `test_a_resolved_profile_still_wins_over_the_provider_declaration`
— no Profile resolves any more; successor: `test_a_connection_auth_type_still_wins`. The
`profile` case of `test_none_cannot_be_persisted` went with the Profile model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, get_args
from uuid import UUID

import pytest
from pydantic import ValidationError

from aigateway.core.auth_types import AuthMode, AuthType
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.schemas import OAuthConnectionResponse
from aigateway.core.plugin_base import ModelEntry, OAuthConfig, ProviderPluginBase
from aigateway.core.provider_access import auth_mode_for, auth_type_of


def resolved_auth_mode(connection: Any, *, plugin: Any) -> Any:
    """The port composition the retired `routes/chat_credentials.py` shim wrapped (E2b)."""
    stored = None if connection is None else auth_type_of(connection)
    return auth_mode_for(stored, plugin=plugin)


class _NoAuthPlugin(ProviderPluginBase):
    """Declares neither OAuth nor api-key: the shape that MAKES a no-auth provider."""

    custom_llm_provider = "stub_noauth"

    def register_models(self) -> list[ModelEntry]:
        return [ModelEntry(model_name="stub_noauth/m", litellm_params={"model": "m"})]


class _ChatlessButAuthenticatedPlugin(ProviderPluginBase):
    """Permits a profile-less request YET holds real auth — the Gemini shape.

    This is the double that keeps the resolution honest: if ``none`` were inferred
    from an absent profile rather than from the provider's declaration, this
    provider would silently fall into no-auth.
    """

    custom_llm_provider = "stub_chatless"

    def register_models(self) -> list[ModelEntry]:
        return [ModelEntry(model_name="stub_chatless/m", litellm_params={"model": "m"})]

    def supports_api_key(self) -> bool:
        return True

    def allows_chatless_credential(self) -> bool:
        return True

    def oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            authorize_url="https://example.invalid/a",
            token_url="https://example.invalid/t",
            client_id="cid",
            scopes=["s"],
            redirect_path="/cb",
        )


# --- the type split -----------------------------------------------------------


def test_the_resolved_mode_admits_none_and_the_persisted_type_does_not() -> None:
    # The whole safety argument in one assertion: 'none' is expressible ONLY as a
    # resolution outcome. Widening AuthType instead of adding AuthMode would make
    # the mode persistable, which is exactly what this split prevents.
    assert set(get_args(AuthMode)) == {"oauth", "api_key", "none"}
    assert set(get_args(AuthType)) == {"oauth", "api_key"}


# WHY the ignore below: pyright REJECTING this call is the primary result — it is
# the static half of the guarantee, and the reason the split was chosen over
# widening AuthType. The ignore lets the runtime half be asserted as well, so the
# protection survives a caller that reaches the model untyped (e.g. from parsed
# JSON). Same pattern, same reason as test_chat_parameter_contract.py.
@pytest.mark.parametrize(
    "build",
    [
        lambda: OAuthConnectionResponse(
            id=UUID(int=1),
            account_id=UUID(int=2),
            provider="p",
            label="default",
            status="active",
            auth_type="none",  # type: ignore[arg-type]
            credential_locator={},
            created_at=datetime(2026, 7, 27, tzinfo=UTC),
        ),
    ],
    ids=["oauth_connection"],
)
def test_none_cannot_be_persisted(build: Any) -> None:
    # A regression guard with a specific target: someone later "simplifying" the two
    # types into one would make this pass a stored auth_type of 'none', and the
    # gateway would start honoring a mode no credential path can serve.
    # AIDEV-NOTE: the guard lives in the TYPED surfaces asserted here. The Tortoise
    # column (oauth/models/oauth_connection.py) is a bare CharField with no choices,
    # so it would happily store the string — which is exactly why AuthType must stay
    # narrow: nothing on the write path can produce the value in the first place.
    with pytest.raises(ValidationError):
        build()


# --- resolution ---------------------------------------------------------------


def test_a_provider_declaring_no_auth_resolves_to_none() -> None:
    assert resolved_auth_mode(None, plugin=_NoAuthPlugin()) == "none"


def test_a_provider_that_merely_allows_a_profileless_request_still_resolves_real_auth() -> None:
    # INVARIANT under test: the trigger is the provider declaration, NOT the absent
    # profile. Both doubles reach this call with no stored credential.
    assert resolved_auth_mode(None, plugin=_ChatlessButAuthenticatedPlugin()) == "oauth"


def test_a_connection_auth_type_still_wins() -> None:
    connection = OAuthConnection(provider="p", label="default", auth_type="api_key")
    assert resolved_auth_mode(connection, plugin=_ChatlessButAuthenticatedPlugin()) == "api_key"


# --- what the provider advertises ---------------------------------------------


def test_a_no_auth_provider_advertises_the_none_mode() -> None:
    # Drives the /v1/models summary intersection: with NO modes at all the summary
    # is forced empty (nothing can be proven), so a no-auth provider could never
    # advertise a parameter until it had a mode of its own to prove them under.
    assert _NoAuthPlugin().available_auth_modes() == ("none",)


def test_declaring_real_auth_never_yields_the_none_mode() -> None:
    modes = _ChatlessButAuthenticatedPlugin().available_auth_modes()
    assert "none" not in modes
    assert set(modes) == {"oauth", "api_key"}
