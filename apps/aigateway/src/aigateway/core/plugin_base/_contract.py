"""The OME-479 chat-parameter contract hooks on the provider plugin.

FEATURE: effective model-capability contract — the provider-side Strategy hooks.
These are the ONLY provider-specific input to the ``/v1/models`` summary, the
detailed ``/v1/model-parameters`` document, and chat dispatch: one source, three
projections.

INVARIANT: core owns the contract algebra; each plugin owns the rules it selects.
A rule is the only thing that enables a parameter, so every hook here that
returns EVIDENCE — observations, tool verdicts, discovered snapshots — is
incapable of enabling one by construction.

The MODEL-LIST discovery hooks live in ``._model_discovery`` and are mixed in below —
an independent responsibility with self-contained defaults, unlike these hooks.

AIDEV-NOTE: ``ProviderPluginBase`` is the name plugins subclass and the name the
package exports; splitting it from ``ProviderPluginCore`` keeps each file within
the repository's 450-line limit and nothing more. See ``._provider`` for why the
contract half is the subclass rather than a mixin.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

# Runtime (not TYPE_CHECKING) import: the default transport capability and both
# default overlays are CONSTRUCTED here, not merely annotated. Safe —
# ``chat_parameters`` is pure core vocabulary and imports nothing that reaches
# this module.
from ..chat_parameters import (
    overlay_observations,
    overlay_tool_capabilities,
    stream_transport_capability,
)

# Runtime import: ``DiscoveryScope.NONE`` is RETURNED by the default
# ``model_discovery_scope`` below, not merely annotated. Safe — the scope module is
# leaf vocabulary (dataclass + enum) and imports nothing that reaches plugin_base.
from ._model_discovery import ModelDiscoveryContract
from ._ports import PluginSettings
from ._provider import ProviderPluginCore

if TYPE_CHECKING:
    from ..chat_parameters import (
        ParameterProjectionRule,
        ProviderDiscoverySnapshot,
        ProviderParameterObservation,
        ToolCapability,
        TransportCapability,
    )
    from ..parameter_discovery import DiscoveryHttpClient, DiscoveryLimits, DiscoverySourceRef
    from ..profile_models import AuthMode


class ProviderPluginBase[TSettings: PluginSettings](
    ModelDiscoveryContract, ProviderPluginCore[TSettings]
):
    """Contract for an aigateway provider plugin.

    Each plugin owns: model contributions, the OAuth strategy, the auth UI
    router, and the chat-parameter contract hooks below. The gateway core loads
    plugins, builds a litellm Router from their combined model lists, and mounts
    each auth router under `/v1/auth/{custom_llm_provider}`.
    """

    # --- OME-479 effective parameter contract (Strategy hooks) ---------------
    #
    # INVARIANT: core owns the contract algebra; each plugin owns the rules it
    # selects. These hooks are the ONLY provider-specific input to the summary,
    # the detailed contract, and dispatch — one source, three projections.

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        """Reviewed, provider-owned dispatch rules for ``model``.

        INVARIANT: a rule is the ONLY thing that enables a parameter, so the
        default is none — a provider advertises (and later forwards) an
        optional parameter only by returning a rule here. Dynamic discovery
        never creates or enables one.

        ``auth_type=None`` requests every rule the provider owns for the model
        and is used SOLELY to derive the conservative profile-independent
        summary; it must never be read as permission for every auth mode. A
        concrete auth mode filters rules for the profile-bound detailed
        contract and for dispatch.
        """
        return ()

    def chat_parameter_tools(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ToolCapability, ...]:
        """Accepted OpenAI-compatible ``tools[].type`` capabilities for ``model``.

        Default: none. A provider advertises ``function`` only once it validates
        OpenAI-compatible tool definitions through the final provider boundary.
        """
        return ()

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        """Raw provider evidence for ``model`` (labelled-local in v1; no network).

        INVARIANT: an observation NEVER authorizes a parameter — only a rule
        does. Observations exist so the detailed contract can show a
        provider-supported-but-not-yet-projected field as visible-but-disabled.
        Default: none.
        """
        return ()

    def validate_chat_parameter_combination(
        self, body: Mapping[str, Any], *, model: str, auth_mode: AuthMode
    ) -> None:
        """Refuse a COMBINATION of accepted parameters this model cannot serve.

        The one seam for cross-field constraints (OME-640). A
        ``ParameterProjectionRule`` is per-path by construction and the classifier
        is deliberately provider-agnostic, so "these two individually-valid fields
        cannot travel together on THIS model under THIS auth mode" has nowhere
        else to live without putting a provider switch into core.

        Called once per chat request on the PROJECTED body, after classification
        and before provider preparation, cache planning, credential access and
        dispatch. Raise ``IncompatibleParametersError`` to refuse; return to
        accept.

        INVARIANT: opt-in. The default accepts everything, so a provider that
        states no cross-field constraint dispatches exactly as it did before —
        the hook never makes a field newly refusable on its own.

        # AIDEV-NOTE: it RAISES rather than returning an optional error because it
        # sits directly under the classification seam in the route and is the same
        # kind of fail-closed refusal; a computed conflict must not be able to
        # vanish because a caller ignored a return value.
        """
        return None

    def chat_discovery_source(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> DiscoverySourceRef | None:
        """The cache identity of this provider's dynamic source for ``model``.

        INVARIANT (§5.3): declared BEFORE any fetch, because the observation cache
        must decide whether a stored value is still trustworthy without paying for
        a round trip. A revision read off the fetched payload would let the source
        itself declare its own old evidence valid.

        ``auth_type`` is the RESOLVED mode of the contract read, bound by
        ``core.discovery_runtime.auth_scoped``. Most providers ignore it — their
        evidence is the same whichever credential dispatch will use. A provider
        whose modes reach different upstreams answers ``None`` for the mode with no
        published source, so no fetch is paid and no freshness window is published
        for evidence the contract would have had to discard. ``None`` means the
        mode was not resolved: fail closed, do not guess one.

        INVARIANT: this is the ONE place that answers "is there a dynamic source
        for this model". Returning a ref commits the provider to answering
        ``discover_chat_parameter_snapshot`` with a snapshot or a
        ``DiscoveryError`` — a ``None`` there is then an inconsistency the runtime
        degrades on rather than caching as evidence.

        Default: None — no dynamic source; the detailed contract is served from
        labelled-local observations alone.
        """
        return None

    def overlay_discovered_observations(
        self,
        observations: tuple[ProviderParameterObservation, ...],
        snapshot: ProviderDiscoverySnapshot | None,
        *,
        stale: bool = False,
    ) -> tuple[ProviderParameterObservation, ...]:
        """Fold a discovered snapshot into this provider's labelled-local evidence.

        INVARIANT (§5.1): per-model evidence is the MORE SPECIFIC claim, so it is
        applied last and wins over endpoint evidence for a shared path. Both remain
        strictly evidence — the result is fed to ``compose_contract_entries``
        alongside the rules, which alone decide ``gateway.status``.

        INVARIANT: ``snapshot is None`` (no dynamic source, NOT ATTEMPTED, or a
        degraded read past the stale window) returns the labelled-local evidence
        UNCHANGED. A discovery outage must never empty the contract, and must never
        be dressed up as a per-model verdict.

        The default is ACTIVE, not a stub: the merge is provider-agnostic, so a
        plugin that declares a source gets the reviewed behaviour for free.
        Override only for a genuinely different precedence.
        """
        if snapshot is None:
            return observations
        return overlay_observations(
            observations,
            snapshot.endpoint_observations + snapshot.model_observations,
            stale=stale,
        )

    def overlay_discovered_tools(
        self,
        tools: tuple[ToolCapability, ...],
        snapshot: ProviderDiscoverySnapshot | None,
    ) -> tuple[ToolCapability, ...]:
        """Fold a discovered snapshot's tool evidence into the reviewed capabilities.

        The tools-section sibling of ``overlay_discovered_observations``, so a
        provider whose discovered verdict reaches the ``tools``/``tool_choice``
        request paths cannot leave the tools section disagreeing with them.

        INVARIANT: ``snapshot is None`` (no dynamic source, NOT ATTEMPTED, or a
        degraded read past the stale window) returns the reviewed capabilities
        UNCHANGED — a discovery outage must never empty or downgrade this section.

        The default is ACTIVE, not a stub: the merge is provider-agnostic. Note it
        takes no ``stale`` flag — the tools section publishes no staleness field, so
        the document's staleness is carried by ``freshness`` and by the mirrored
        request-path observations, which do have somewhere to put it.
        """
        if snapshot is None:
            return tools
        return overlay_tool_capabilities(tools, snapshot.tool_observations)

    async def discover_chat_parameter_snapshot(
        self,
        *,
        model: str,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth_type: AuthMode | None = None,
    ) -> ProviderDiscoverySnapshot | None:
        """Best-effort DYNAMIC evidence for ``model`` from FIXED public catalogs.

        ``auth_type`` carries the same resolved mode ``chat_discovery_source``
        received, from the same binder — so a provider whose source declaration is
        auth-scoped can gate BOTH hooks on ONE predicate.

        INVARIANT (§4.2/§5.2): the async sibling of
        ``chat_parameter_observations``. It fetches this provider's FIXED public
        documents through the INJECTED bounded transport (never a raw client,
        never a caller-supplied URL, never a credential). It NEVER runs on the
        chat dispatch path, and — like an observation — it NEVER enables a
        parameter; only a rule does.

        INVARIANT (§5.3): three outcomes, three signals, because a consumer must
        be able to tell an OUTAGE from an absence of evidence:

        - ``ProviderDiscoverySnapshot`` — the source was reached. An EMPTY
          snapshot is the honest "reached it; this model is not listed".
        - raises sanitized ``DiscoveryError`` — the fetch was attempted and
          FAILED. ``ObservationCache`` maps this to its stale/degraded paths.
        - ``None`` — NO ATTEMPT was made, and no connection was opened.

        AIDEV-NOTE: ``None`` must not be widened back to cover failure. The cache
        treats every normal return as a successful refresh, so a ``None`` returned
        for a failure is stored labelled ``fresh`` and evicts the last good
        snapshot — the contract then claims currency it never had.

        Default: None — no dynamic source; the caller relies on labelled-local
        observations alone.
        """
        return None

    def chat_transport_capabilities(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[TransportCapability, ...]:
        """Transport controls (e.g. ``stream``) reported separately from params.

        Streaming is a transport capability, not an ordinary model parameter, so
        it is surfaced in its own contract section.

        INVARIANT: the default is DERIVED from ``supports_chat_streaming`` — the
        same flag ``/v1/chat/completions`` enforces — so the published contract
        cannot disagree with what dispatch actually does. Deriving it here rather
        than per plugin means a new provider is described correctly with no extra
        code, and no plugin can publish a status that contradicts its own flag.

        Override to add further controls, or to replace the ``stream`` entry when
        the plugin has real upstream evidence to report as ``provider_support``.
        """
        return (stream_transport_capability(gateway_enabled=self.supports_chat_streaming()),)

    def available_auth_modes(self) -> tuple[AuthMode, ...]:
        """Auth modes a client could use with this provider (profile-independent).

        Drives the conservative summary intersection on ``/v1/models``. Derived
        from declared capability: api-key iff ``supports_api_key()``, oauth iff
        the provider advertises ``oauth_config()``. Providers with bespoke auth
        override this.

        # WHY the empty case became ``("none",)`` (OME-636): declaring NEITHER
        # credential type is itself a declaration — the provider needs none. The
        # summary intersection reads an empty tuple as "nothing can be proven" and
        # forces ``supported_parameters`` empty, so a credential-free provider
        # could never advertise a parameter until it had a mode of its own to
        # prove them under.
        # INVARIANT: "none" is derived HERE, from the provider's own declaration —
        # never from an absent profile. A provider that merely permits a
        # profile-less request (``allows_chatless_profile``) still declares real
        # credential types and keeps them.
        """
        modes: list[AuthMode] = []
        if self.supports_api_key():
            modes.append("api_key")
        if self.oauth_config() is not None:
            modes.append("oauth")
        return tuple(modes) or ("none",)
