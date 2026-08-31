"""OME-1026 rework U1 — the scope-aware discovery port.

FEATURE: two discovery scopes replace the rejected deployment-wide credentialed
listing. ``PUBLIC_GLOBAL`` is one shared catalog safe to publish to every
account; ``PROFILE_CREDENTIAL`` is a private catalog per authenticated profile
that must NEVER reach the global listing.

STORY: as an operator I get OpenRouter's public catalog deployment-wide, and as
an account holder I get Anthropic models discovered with MY OWN stored key —
without either leaking into the other's listing.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.model_discovery_scope import DiscoveryScope, ProviderAuthContext
from aigateway.core.parameter_discovery import RawResponse
from aigateway.core.plugin_base import ModelDiscoverySource, ProviderPluginBase
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings


class _LoudClient:
    """Any dial is a bug in the code under test, not a degraded outcome.

    # WHY the exact ``DiscoveryHttpClient`` signature rather than ``**kwargs``: a
    # loose stub type-checks against anything, so a production signature change
    # would silently stop being exercised here. This shape makes the type checker
    # confirm the catalog is being called the way production calls it.
    """

    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        raise AssertionError(f"DIAL ATTEMPTED: {url}")


def _anthropic(**overrides: Any) -> AnthropicProviderPlugin:
    return AnthropicProviderPlugin(settings=AnthropicPluginSettings(**overrides))


def _openrouter(**overrides: Any) -> OpenRouterProviderPlugin:
    return OpenRouterProviderPlugin(settings=OpenRouterPluginSettings(**overrides))


# ── the scope vocabulary ──────────────────────────────────────────────────────


def test_the_scope_enum_names_exactly_the_three_owner_approved_scopes() -> None:
    # INVARIANT: a provider is absent, public-global, or profile-scoped. A fourth
    # value would be a new trust boundary nothing in the catalog knows how to honor.
    assert {scope.value for scope in DiscoveryScope} == {
        "none",
        "public_global",
        "profile_credential",
    }


def test_a_plugin_declares_no_discovery_by_default() -> None:
    """Every provider that says nothing keeps its static seed listing."""

    class _Plain(ProviderPluginBase):  # type: ignore[type-arg]
        custom_llm_provider = "plain"

    assert _Plain.model_discovery_scope(_Plain) is DiscoveryScope.NONE  # type: ignore[arg-type]


# ── provider declarations ─────────────────────────────────────────────────────


def test_openrouter_declares_public_global_and_keeps_one_shared_catalog() -> None:
    plugin = _openrouter(enabled=True, live_models=True)

    assert plugin.model_discovery_scope() is DiscoveryScope.PUBLIC_GLOBAL
    assert plugin.model_discovery_source() is not None


@pytest.mark.parametrize(
    ("enabled", "live"),
    [(False, True), (True, False), (False, False)],
)
def test_openrouter_declares_no_scope_when_either_flag_is_off(enabled: bool, live: bool) -> None:
    plugin = _openrouter(enabled=enabled, live_models=live)

    assert plugin.model_discovery_scope() is DiscoveryScope.NONE
    assert plugin.model_discovery_source() is None


def test_anthropic_declares_profile_credential_with_no_deployment_key_involved() -> None:
    """The owner decision: Anthropic discovery is driven by the CALLER's profile.

    # INVARIANT: no deployment setting can turn this into a shared catalog. The
    # scope alone decides, and it is private.
    """
    plugin = _anthropic(live_models=True)

    assert plugin.model_discovery_scope() is DiscoveryScope.PROFILE_CREDENTIAL


def test_anthropic_declares_no_scope_when_live_models_is_off() -> None:
    plugin = _anthropic(live_models=False)

    assert plugin.model_discovery_scope() is DiscoveryScope.NONE


def test_the_rejected_deployment_discovery_key_setting_is_gone() -> None:
    """The dedicated-key design is REMOVED, not deprecated (owner decision).

    # WHY assert its ABSENCE: leaving the field would let a deployment re-enable a
    # shared credentialed catalog — the exact architecture the owner rejected — and
    # would silently keep working after this rework.
    """
    assert "discovery_api_key" not in AnthropicPluginSettings.model_fields


# ── the global catalog refuses private providers ──────────────────────────────


@pytest.mark.asyncio
async def test_the_global_catalog_never_serves_a_profile_scoped_provider() -> None:
    """INVARIANT: the private scope cannot enter the shared catalog at all.

    # WHY at the CATALOG and not only at the route: the catalog is what every
    # global consumer shares. Refusing here means no future caller can accidentally
    # publish a credential-derived snapshot deployment-wide, and it holds even if a
    # provider wrongly declares a source alongside the private scope.
    """
    catalog = ModelCatalog()
    client = _LoudClient()
    plugin = _anthropic(live_models=True)

    entries = await catalog.entries_for(plugin, client=client, limits=None)

    assert entries is None, "a private provider must fall back to seeds globally"
    assert client.dialed == [], "and must cause ZERO egress on the global path"


@pytest.mark.asyncio
async def test_the_global_catalog_refuses_a_private_provider_even_if_it_declares_a_source() -> None:
    class _Liar:
        custom_llm_provider = "liar"

        def model_discovery_scope(self) -> DiscoveryScope:
            return DiscoveryScope.PROFILE_CREDENTIAL

        def model_discovery_source(self) -> ModelDiscoverySource:
            return ModelDiscoverySource(
                key="liar:models", revision="v1", ttl_s=300, stale_ttl_s=600, failure_ttl_s=30
            )

        async def discover_live_models(self, **_kwargs: object) -> tuple:
            raise AssertionError("the global catalog must not call a private provider")

    catalog = ModelCatalog()

    assert await catalog.entries_for(_Liar(), client=_LoudClient(), limits=None) is None


# ── the auth context is a credential carrier: it must not render ──────────────


def test_the_provider_auth_context_never_renders_its_header_values() -> None:
    """INVARIANT: this object carries a live credential in ``headers``.

    # WHY a custom repr: the context is passed as a parameter, so it becomes a
    # frame local on the whole discovery path. A dataclass's generated repr would
    # print the credential into any traceback or log that formats it.
    """
    ctx = ProviderAuthContext(
        headers={"x-api-key": "sk-ant-PLAINTEXT-CANARY"},
        auth_type="api_key",
        credential_revision="7",
    )

    rendered = f"{ctx!r} {ctx}"

    assert "sk-ant-PLAINTEXT-CANARY" not in rendered
    assert "x-api-key" in rendered, "header NAMES are safe and useful for debugging"
    assert ctx.headers["x-api-key"] == "sk-ant-PLAINTEXT-CANARY", "the value still works"


def test_the_provider_auth_context_is_immutable() -> None:
    ctx = ProviderAuthContext(headers={}, auth_type="api_key", credential_revision="1")

    with pytest.raises((AttributeError, TypeError)):
        ctx.auth_type = "oauth"  # type: ignore[misc]
