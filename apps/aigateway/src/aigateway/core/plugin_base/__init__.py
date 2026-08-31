"""The aigateway provider-plugin contract.

FEATURE: the port every provider implements. A plugin contributes models,
produces credentials, exposes auth routes, dispatches completions, and declares
its chat-parameter contract; the gateway core knows nothing provider-specific
beyond what these hooks return.

INVARIANT (SOLID/hexagonal): core defines this port and never imports a plugin.
Wiring happens through the plugin registry, not through direct imports.

AIDEV-NOTE (OME-653): the implementation is split across ``_ports`` (value types
and the credential port), ``_provider`` (auth, model registration, dispatch),
``_contract`` (the OME-479 chat-parameter hooks), ``_model_discovery`` (the OME-1026
model-LIST discovery hooks) and ``_resolvers`` (duck-typed credential resolution)
purely to keep each file within the repository's 450-line limit, split by
RESPONSIBILITY rather than by line count. That layout is an implementation detail —
THIS module is the public surface, and every name below is importable exactly as it
was from the former single ``plugin_base`` module. Import from here, never from a half.
"""

from ..cache_ports import PROJECTION_BYPASS_REASON, CacheBypass, GlobalCacheProjection
from ._contract import ProviderPluginBase
from ._model_discovery import ModelDiscoverySource
from ._ports import (
    CredentialStrategy,
    ModelAdmission,
    ModelEntry,
    OAuthCodeExchangeRequest,
    OAuthConfig,
    OAuthStrategy,
    PluginSettings,
)
from ._resolvers import credential_service_provider_for, credential_strategy_from

# WHY these three are re-exported here (OME-305): they are part of the
# ``global_cache_projection`` port's SIGNATURE — a plugin cannot implement the hook
# without naming ``CacheBypass``. The docstring above promises this module is the
# public surface, so a plugin author reaching for the base class must find the port's
# own vocabulary in the same import, not be sent to ``core.cache_ports`` to discover
# which of two modules owns half a contract.
#
# INVARIANT: ``core.cache_ports`` stays the DEFINITION and is deliberately a leaf —
# it imports nothing from the gateway, which is what lets both the plugin facade and
# the request-cache internals depend on it without a cycle. This is a re-export, not
# a second definition.
__all__ = [
    "PROJECTION_BYPASS_REASON",
    "CacheBypass",
    "CredentialStrategy",
    "GlobalCacheProjection",
    "ModelAdmission",
    "ModelDiscoverySource",
    "ModelEntry",
    "OAuthCodeExchangeRequest",
    "OAuthConfig",
    "OAuthStrategy",
    "PluginSettings",
    "ProviderPluginBase",
    "credential_service_provider_for",
    "credential_strategy_from",
]
