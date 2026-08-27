"""OME-1026 U5/U6: the publishable-id policy, the provider-owned merge, and the port.

FEATURE: opt-in live Anthropic model discovery — turning a walked catalog into the finished
rows ``GET /v1/models`` publishes, and gating the whole thing on the operator's opt-in.

INVARIANT (D8, provider-owned merge): the PROVIDER owns the merge of operator-explicit models
with discovered ids. Core receives finished rows and never learns which were seeds, so seed
provenance cannot leak into route logic.

INVARIANT (D3, opt-in): ``model_discovery_source()`` returns None unless a discovery key is
configured AND ``live_models`` is true. Returning None is the port's documented "no attempt,
no connection" signal, so every off state means literally zero catalog egress.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from aigateway.core.parameter_discovery import DiscoveryError
from aigateway.core.plugin_base import ModelEntry
from aigateway.plugins.anthropic_provider.live_models import (
    ANTHROPIC_MODELS_DISCOVERY_SOURCE,
    live_listing_entries,
    publishable_model_ids,
)
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

_FAKE_KEY = "sk-ant-fixture-not-a-real-key"


class _LoudClient:
    """Any dial at all is a failure — the zero-egress pins depend on it."""

    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None) -> Any:
        self.dialed.append(url)
        raise AssertionError(f"discovery is OFF but a dial was attempted: {url}")


def _settings(**overrides: Any) -> AnthropicPluginSettings:
    return AnthropicPluginSettings(**overrides)


# --------------------------------------------------------------------------------------
# U5 — publishable id shape policy.
# --------------------------------------------------------------------------------------


def test_safe_ids_publish_in_upstream_order() -> None:
    ids = ("claude-opus-5", "claude-opus-5-20260801", "claude-haiku-4.5")

    assert publishable_model_ids(ids) == ids


@pytest.mark.parametrize(
    "unsafe",
    [
        "anthropic/claude-opus-5",  # a slash would corrupt the canonical namespace
        "claude-opus-5:beta",  # ':' is gateway-reserved variant syntax
        "claude-opus-5~alias",  # '~' is gateway-reserved alias syntax
        "claude opus 5",  # interior space
        "claude-opus-5\n",  # trailing newline — the fullmatch-vs-match case
        "claude-opus-5\t",
        "-claude-opus-5",  # must start alphanumeric
        ".claude-opus-5",
        "claude-opus-5&limit=1",
        "claude-opus-5?x=1",
        "claude-opus-5#frag",
        "claude-opus-5%20x",
        "a" * 257,  # over the length cap
    ],
)
def test_an_unsafe_shaped_id_is_not_published(unsafe: str) -> None:
    # INVARIANT: publication is a FILTER, not the census — a shape this gateway cannot
    # publish is dropped, while the completeness of the READ is judged by the walk.
    assert publishable_model_ids(("claude-opus-5", unsafe)) == ("claude-opus-5",)


def test_an_id_at_exactly_the_length_cap_is_published() -> None:
    at_cap = "a" * 256
    assert publishable_model_ids((at_cap,)) == (at_cap,)


def test_no_publishable_ids_fails_closed() -> None:
    # INVARIANT: zero survivors must not be cached as a fresh, legitimately-empty listing —
    # that would evict a good snapshot on nothing but a shape change upstream.
    with pytest.raises(DiscoveryError) as exc:
        publishable_model_ids(("anthropic/bad", "also/bad"))

    assert exc.value.reason == "model_catalog_empty"


def test_publication_preserves_unfolded_alias_and_snapshot_order() -> None:
    # D7 mirror of the U4 order pin: no sorting, no folding, at either stage.
    assert publishable_model_ids(("claude-x-5", "claude-x-5-20260101")) == (
        "claude-x-5",
        "claude-x-5-20260101",
    )


# --------------------------------------------------------------------------------------
# U5 — the provider-owned merge.
# --------------------------------------------------------------------------------------


def test_discovered_ids_become_entries_with_the_seed_litellm_template() -> None:
    entries = live_listing_entries(_settings(), ("claude-opus-5", "claude-opus-5-20260801"))

    # INVARIANT: structurally identical to a compiled seed — bare ``model_name``, the
    # ``anthropic/`` prefix living only in litellm_params, which is what makes a discovered
    # id dispatch through exactly the same path as a seeded one.
    assert entries == (
        ModelEntry(model_name="claude-opus-5", litellm_params={"model": "anthropic/claude-opus-5"}),
        ModelEntry(
            model_name="claude-opus-5-20260801",
            litellm_params={"model": "anthropic/claude-opus-5-20260801"},
        ),
    )


def test_compiled_default_seeds_are_absent_from_a_healthy_snapshot() -> None:
    """A retired alias must actually disappear — that is half the product outcome.

    # WHY ``model_fields_set``: pydantic records a field there only when a value arrived
    # from the constructor or the environment; a ``default_factory`` fill does not register.
    # That is the exact line between "the operator asked for these" and "compiled fallback".
    """
    settings = _settings()
    assert "models" not in settings.model_fields_set

    entries = live_listing_entries(settings, ("claude-opus-5",))

    assert [entry.model_name for entry in entries] == ["claude-opus-5"]
    # A seed that upstream no longer serves is gone, not silently retained.
    assert "claude-haiku-4-5" not in [entry.model_name for entry in entries]


def test_operator_explicit_models_lead_and_survive_a_healthy_snapshot() -> None:
    pinned = ModelEntry(
        model_name="claude-operator-pinned",
        litellm_params={"model": "anthropic/claude-operator-pinned"},
    )
    settings = _settings(models=[pinned])
    assert "models" in settings.model_fields_set

    entries = live_listing_entries(settings, ("claude-opus-5",))

    assert entries[0] == pinned
    assert [entry.model_name for entry in entries] == ["claude-operator-pinned", "claude-opus-5"]


def test_a_discovered_id_matching_an_operator_entry_keeps_the_operator_row() -> None:
    """D8: dedupe on the CANONICAL id, so bare and prefixed forms compare equal.

    # WHY canonical comparison rather than raw ``model_name``: the operator may configure
    # ``anthropic/claude-opus-5`` while upstream returns ``claude-opus-5``. Both denote ONE
    # gateway id, so publishing both would emit a duplicate row for the same model.
    """
    pinned = ModelEntry(
        model_name="anthropic/claude-opus-5",
        litellm_params={"model": "anthropic/claude-opus-5"},
    )
    settings = _settings(models=[pinned])

    entries = live_listing_entries(settings, ("claude-opus-5", "claude-sonnet-5"))

    assert entries == (
        pinned,
        ModelEntry(
            model_name="claude-sonnet-5", litellm_params={"model": "anthropic/claude-sonnet-5"}
        ),
    )


def test_live_listing_keeps_unfolded_alias_snapshot_order_after_dedupe() -> None:
    pinned = ModelEntry(
        model_name="claude-pinned", litellm_params={"model": "anthropic/claude-pinned"}
    )
    settings = _settings(models=[pinned])

    entries = live_listing_entries(settings, ("claude-x-5", "claude-x-5-20260101"))

    assert [entry.model_name for entry in entries] == [
        "claude-pinned",
        "claude-x-5",
        "claude-x-5-20260101",
    ]


# --------------------------------------------------------------------------------------
# U6 — the port on the plugin.
# --------------------------------------------------------------------------------------


def test_no_discovery_key_declares_no_source() -> None:
    plugin = AnthropicProviderPlugin(settings=_settings())

    assert plugin.model_discovery_source() is None


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"live_models": False}, id="live_models_off_no_key"),
        pytest.param(
            {"live_models": False, "discovery_api_key": SecretStr(_FAKE_KEY)},
            id="live_models_off_with_key",
        ),
        pytest.param({}, id="no_key_at_all"),
    ],
)
def test_every_off_combination_declares_no_source(overrides: dict[str, Any]) -> None:
    plugin = AnthropicProviderPlugin(settings=_settings(**overrides))

    assert plugin.model_discovery_source() is None


def test_a_configured_key_declares_the_expected_source() -> None:
    plugin = AnthropicProviderPlugin(settings=_settings(discovery_api_key=SecretStr(_FAKE_KEY)))

    source = plugin.model_discovery_source()

    assert source is not None
    assert source == ANTHROPIC_MODELS_DISCOVERY_SOURCE
    # INVARIANT: the cache identity carries NO credential material — the snapshot is
    # deployment-wide, and a key in the identity would silently shard it per credential.
    assert _FAKE_KEY not in source.key
    assert _FAKE_KEY not in source.revision


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="no_key_at_all"),
        pytest.param({"live_models": False}, id="live_models_off_no_key"),
        pytest.param(
            {"live_models": False, "discovery_api_key": SecretStr(_FAKE_KEY)},
            id="live_models_off_with_key",
        ),
    ],
)
async def test_discovery_off_returns_none_with_zero_egress(overrides: dict[str, Any]) -> None:
    plugin = AnthropicProviderPlugin(settings=_settings(**overrides))
    client = _LoudClient()

    assert await plugin.discover_live_models(client=client) is None
    assert client.dialed == []


@pytest.mark.asyncio
async def test_an_oauth_only_configuration_never_dials_for_discovery() -> None:
    """The locked refutation: a Claude-subscription token is NOT a discovery credential.

    # WHY pinned: OAuth is the Anthropic provider's normal auth path, so "we already have a
    # token, use it" is the tempting shortcut. One shared snapshot serves every account, so
    # an account credential would publish one user's entitlements to everyone.
    """
    plugin = AnthropicProviderPlugin(settings=_settings())
    client = _LoudClient()

    assert plugin.model_discovery_source() is None
    assert await plugin.discover_live_models(client=client) is None
    assert client.dialed == []


@pytest.mark.asyncio
async def test_a_healthy_snapshot_returns_merged_entries() -> None:
    import json

    from aigateway.core.parameter_discovery import RawResponse

    class _OnePageClient:
        def __init__(self) -> None:
            self.headers_seen: list[dict[str, str]] = []

        async def get(
            self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
        ) -> RawResponse:
            assert headers is not None
            self.headers_seen.append(dict(headers))
            if url != "https://api.anthropic.com/v1/models?limit=1000":
                raise AssertionError(f"unexpected dial: {url}")
            body = json.dumps(
                {
                    "data": [
                        {"id": "claude-opus-5", "type": "model"},
                        {"id": "claude-opus-5-20260801", "type": "model"},
                    ],
                    "has_more": False,
                }
            )
            return RawResponse(status=200, content_type="application/json", body=body)

    plugin = AnthropicProviderPlugin(
        settings=_settings(discovery_api_key=SecretStr(_FAKE_KEY), api_version="2023-06-01")
    )
    client = _OnePageClient()

    entries = await plugin.discover_live_models(client=client)

    assert entries is not None
    assert [entry.model_name for entry in entries] == [
        "claude-opus-5",
        "claude-opus-5-20260801",
    ]
    # The configured api_version travels with the key, not a hardcoded copy.
    assert client.headers_seen == [{"x-api-key": _FAKE_KEY, "anthropic-version": "2023-06-01"}]


@pytest.mark.asyncio
async def test_a_discovery_error_propagates_untouched() -> None:
    class _FailingClient:
        async def get(self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None):
            raise DiscoveryError("unreachable")

    plugin = AnthropicProviderPlugin(settings=_settings(discovery_api_key=SecretStr(_FAKE_KEY)))

    # INVARIANT: the provider does NOT catch its own failures — core owns the
    # stale/fallback ladder, and swallowing the error here would return None, which the
    # cache stores as a successful refresh and thereby evicts the last good listing.
    with pytest.raises(DiscoveryError) as exc:
        await plugin.discover_live_models(client=_FailingClient())

    assert exc.value.reason == "unreachable"
    assert _FAKE_KEY not in str(exc.value)
