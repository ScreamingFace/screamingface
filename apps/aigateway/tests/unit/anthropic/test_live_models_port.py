"""OME-1026 U5/U6: the publishable-id policy, the provider-owned merge, and the port.

FEATURE: profile-scoped live Anthropic model discovery — turning a walked catalog into the
finished rows one PROFILE's model list publishes, using that profile's own stored credential.

INVARIANT (D8, provider-owned merge): the PROVIDER owns the merge of operator-explicit models
with discovered ids. Core receives finished rows and never learns which were seeds, so seed
provenance cannot leak into route logic.

INVARIANT (OME-1026 rework, scope): Anthropic's catalog answers FOR THE CALLING KEY, so its
listing is PROFILE_CREDENTIAL — one private snapshot per authenticated profile. The provider
implements ``discover_profile_models`` and deliberately NOT the public ``discover_live_models``,
so there is no code path that could produce credentialed rows for the shared catalog.

INVARIANT (zero egress when off): ``live_models=false`` withdraws the scope and the source, and
both the public and the private hook return None. Returning None is the port's documented "no
attempt, no connection" signal.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aigateway.core.model_discovery_scope import DiscoveryScope, ProviderAuthContext
from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
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


class _OnePageClient:
    """A canned single-page catalog that RECORDS the exact wire headers."""

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


class _FakeCredentialStore:
    """The encrypted store's seam: hands back one profile's decrypted blob.

    # WHY a fake rather than the real ORMStore: this test is about which HEADER the
    # provider projects a stored key into, not about persistence. The real store needs a
    # database and a master key, neither of which changes the header shape.
    """

    def __init__(self, blob: dict[str, str]) -> None:
        self._blob = json.dumps(blob)
        self.reads = 0

    async def read(self, service: str, account: str) -> str | None:
        self.reads += 1
        return self._blob

    # INVARIANT: discovery only READS a credential. These three complete the
    # ``CredentialBlobStore`` protocol so the type checker accepts the seam, and they
    # fail the test if the discovery path ever mutates stored credential material.
    async def write(self, service: str, account: str, value: str) -> None:
        raise AssertionError("discovery must never write a credential")

    async def delete(self, service: str, account: str) -> None:
        raise AssertionError("discovery must never delete a credential")

    async def mutate(self, service: str, account: str, mutator: object) -> None:
        raise AssertionError("discovery must never mutate a credential")


def _api_key_auth() -> ProviderAuthContext:
    return ProviderAuthContext(headers={"x-api-key": _FAKE_KEY}, auth_type="api_key")


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
# The private port on the plugin (OME-1026 rework).
# --------------------------------------------------------------------------------------


def test_anthropic_declares_a_private_profile_scope() -> None:
    """INVARIANT: Anthropic's listing is per-account data BY CONSTRUCTION.

    # WHY not PUBLIC_GLOBAL: ``GET /v1/models`` upstream answers "what may the calling
    # key call". One shared snapshot would therefore publish whichever account's
    # credential happened to fetch it to every other account.
    """
    plugin = AnthropicProviderPlugin(settings=_settings())

    assert plugin.model_discovery_scope() is DiscoveryScope.PROFILE_CREDENTIAL
    source = plugin.model_discovery_source()
    assert source == ANTHROPIC_MODELS_DISCOVERY_SOURCE
    # INVARIANT: the declared source carries cache POLICY only. The private identity is
    # composed by the profile catalog from ownership data; a credential in either field
    # would put secret-derived material into cache keys and log lines.
    assert source is not None
    assert _FAKE_KEY not in source.key
    assert _FAKE_KEY not in source.revision


def test_live_models_off_withdraws_the_scope_and_the_source() -> None:
    plugin = AnthropicProviderPlugin(settings=_settings(live_models=False))

    assert plugin.model_discovery_scope() is DiscoveryScope.NONE
    assert plugin.model_discovery_source() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [pytest.param({}, id="discovery_on"), pytest.param({"live_models": False}, id="discovery_off")],
)
async def test_the_public_hook_is_never_implemented_for_anthropic(
    overrides: dict[str, Any],
) -> None:
    """INVARIANT (structural, not a rule to remember): no public Anthropic listing exists.

    # WHY assert it even with discovery ON: this is the guarantee that one account's
    # entitlements cannot reach the deployment-wide catalog. The shared ``ModelCatalog``
    # also refuses the private scope, so the leak is denied twice — but only THIS
    # assertion fails if someone re-adds a deployment-credentialed public fetch.
    """
    plugin = AnthropicProviderPlugin(settings=_settings(**overrides))
    client = _LoudClient()

    assert await plugin.discover_live_models(client=client) is None
    assert client.dialed == []


def test_an_oauth_profile_is_refused_before_any_credential_is_touched() -> None:
    """The locked refutation: a Claude-subscription token is NOT a Models-API credential.

    # WHY refuse rather than try: Anthropic's ``/v1/models`` is verified for API keys
    # only, and this has not been probed with an OAuth token. Refusing on the declared
    # auth type means an OAuth profile spends ZERO credentialed requests to find out.
    """
    plugin = AnthropicProviderPlugin(settings=_settings())

    assert plugin.profile_discovery_unsupported_reason(auth_type="oauth") == (
        "unsupported_auth_type"
    )
    assert plugin.profile_discovery_unsupported_reason(auth_type="api_key") is None


@pytest.mark.asyncio
async def test_an_oauth_auth_context_never_dials_even_if_it_reaches_the_provider() -> None:
    """Defence in depth: the catalog gates first, and the provider re-checks."""
    plugin = AnthropicProviderPlugin(settings=_settings())
    client = _LoudClient()

    entries = await plugin.discover_profile_models(
        client=client,
        auth=ProviderAuthContext(
            headers={"authorization": "Bearer oauth-token"}, auth_type="oauth"
        ),
    )

    assert entries is None
    assert client.dialed == []


@pytest.mark.asyncio
async def test_discovery_off_returns_none_for_the_private_hook_with_zero_egress() -> None:
    plugin = AnthropicProviderPlugin(settings=_settings(live_models=False))
    client = _LoudClient()

    entries = await plugin.discover_profile_models(client=client, auth=_api_key_auth())

    assert entries is None
    assert client.dialed == []


@pytest.mark.asyncio
async def test_a_healthy_profile_snapshot_returns_merged_entries() -> None:
    plugin = AnthropicProviderPlugin(settings=_settings(api_version="2023-06-01"))
    client = _OnePageClient()

    entries = await plugin.discover_profile_models(client=client, auth=_api_key_auth())

    assert entries is not None
    assert [entry.model_name for entry in entries] == [
        "claude-opus-5",
        "claude-opus-5-20260801",
    ]
    # INVARIANT (the wire shape): a RAW key authenticates with ``x-api-key``.
    # ``Authorization: Bearer`` is Anthropic's OAUTH shape — the chat path may use it
    # because LiteLLM re-maps it downstream, but a direct catalog dial has no such
    # translation layer, so a bearer-shaped raw key would 401.
    assert client.headers_seen == [{"x-api-key": _FAKE_KEY, "anthropic-version": "2023-06-01"}]


@pytest.mark.asyncio
async def test_only_allowlisted_auth_headers_reach_the_wire() -> None:
    """INVARIANT (header hardening): the provider decides what leaves, not the caller.

    # WHY: the auth context is built from a credential strategy whose header set may grow
    # (a beta header, a cookie, a proxy artefact). Forwarding whatever it contains would
    # let an unrelated header — or a caller-influenced one — be sent to Anthropic
    # alongside the key.
    """
    plugin = AnthropicProviderPlugin(settings=_settings(api_version="2023-06-01"))
    client = _OnePageClient()

    await plugin.discover_profile_models(
        client=client,
        auth=ProviderAuthContext(
            headers={
                "x-api-key": _FAKE_KEY,
                "cookie": "session=should-not-travel",
                "x-forwarded-for": "10.0.0.1",
                "anthropic-version": "1999-01-01",
            }
        ),
    )

    # The provider's own api_version wins over one smuggled in through the context.
    assert client.headers_seen == [{"x-api-key": _FAKE_KEY, "anthropic-version": "2023-06-01"}]


@pytest.mark.asyncio
async def test_an_auth_context_with_no_usable_header_fails_closed() -> None:
    plugin = AnthropicProviderPlugin(settings=_settings())
    client = _LoudClient()

    with pytest.raises(DiscoveryError) as exc:
        await plugin.discover_profile_models(
            client=client, auth=ProviderAuthContext(headers={"x-unrelated": "value"})
        )

    assert exc.value.reason == "missing_credential"
    assert client.dialed == [], "no unauthenticated dial"


@pytest.mark.asyncio
async def test_a_discovery_error_propagates_untouched() -> None:
    class _FailingClient:
        async def get(self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None):
            raise DiscoveryError("unreachable")

    plugin = AnthropicProviderPlugin(settings=_settings())

    # INVARIANT: the provider does NOT catch its own failures — the private catalog owns
    # the stale/fallback ladder, and swallowing the error here would return None, which
    # that catalog treats as an inconsistency rather than a failed attempt.
    with pytest.raises(DiscoveryError) as exc:
        await plugin.discover_profile_models(client=_FailingClient(), auth=_api_key_auth())

    assert exc.value.reason == "unreachable"
    assert _FAKE_KEY not in str(exc.value)


def test_the_auth_context_repr_hides_the_credential() -> None:
    """The context is a frame local for the whole dial — its repr reaches tracebacks."""
    auth = _api_key_auth()

    assert _FAKE_KEY not in repr(auth)
    assert _FAKE_KEY not in str(auth)
    assert "x-api-key" in repr(auth), "header NAMES stay visible for debugging"


@pytest.mark.asyncio
async def test_the_discovery_strategy_reuses_the_stored_key_with_the_catalog_header() -> None:
    """FEATURE: the owner never re-enters a key that is already stored.

    # WHY a second strategy rather than reusing the chat one: same stored blob, same
    # encrypted store, same class — only the header projection differs (``x-api-key``
    # for the REST catalog vs the chat path's bearer shape). Reusing ``ApiKeyStrategy``
    # keeps the store the ONLY component that decrypts.
    """
    plugin = AnthropicProviderPlugin(settings=_settings())
    store = _FakeCredentialStore({"auth_type": "api_key", "api_key": _FAKE_KEY})

    strategy = plugin.discovery_credential_strategy_for("acct-a:work", credential_store=store)
    headers = await strategy.get_authorization_header()

    assert headers == {"x-api-key": _FAKE_KEY}
    assert store.reads == 1, "the key is read from the store, never re-entered"
    # The chat strategy for the same profile projects the SAME key differently.
    chat_headers = await plugin.api_key_strategy_for(
        "acct-a:work", credential_store=store
    ).get_authorization_header()
    assert chat_headers == {"Authorization": f"Bearer {_FAKE_KEY}"}
