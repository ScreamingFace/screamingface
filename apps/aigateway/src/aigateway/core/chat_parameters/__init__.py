"""OME-479 contract value types and rule algebra.

FEATURE: effective model-capability contract. This package owns the immutable
value objects and the *pure* derivations that turn a provider-local rule set
into the two client-facing projections:

- the conservative, caller-independent inline ``/v1/models`` summary, and
- the overlaid detailed ``/v1/model-parameters`` entries, bound to the caller's credential
  target.

INVARIANT: provider *observation* (raw support) and gateway *rule* (what the
gateway validates and forwards) are separate concerns. Only a gateway rule
authorizes dispatch; an observation never does. Presence, provider support,
staleness, or an unknown enum value never authorize a parameter.

INVARIANT (SOLID/hexagonal): this package contains NO provider-name switch and
NO central provider inventory. Each plugin owns and selects its own rules; the
algebra here is provider-agnostic.

AIDEV-NOTE (OME-602, extended OME-704): the implementation is split across
``_types`` (vocabulary and value objects), ``_schema`` (``ParameterSchema`` and
the value-validation vocabulary) and ``_algebra`` (the pure derivations) to keep
each file within the repository's 450-line limit. That layout is an
implementation detail — THIS module is the public surface, and every name below
is importable exactly as it was from the former single ``chat_parameters``
module. Import from here, never from a half; a name may move between halves
without notice.
"""

from ._algebra import (
    compose_contract_entries,
    inline_supported_parameters,
    normalize_rules,
    overlay_observations,
    overlay_tool_capabilities,
    supported_tool_types,
)
from ._schema import (
    ParameterSchema,
    ParameterValidationError,
    SchemaItemType,
    SchemaType,
)
from ._types import (
    GATEWAY_OWNED_FIELDS,
    STREAM_TRANSPORT_NAME,
    CacheBehavior,
    DuplicateParameterRuleError,
    GatewayStatus,
    InvalidParameterRuleError,
    ParameterContractEntry,
    ParameterProjectionRule,
    ParameterRuleError,
    ProjectionKind,
    ProviderDiscoverySnapshot,
    ProviderParameterObservation,
    ProviderSupport,
    ProviderToolObservation,
    ToolCapability,
    TransportCapability,
    stream_transport_capability,
)

__all__ = [
    "GATEWAY_OWNED_FIELDS",
    "STREAM_TRANSPORT_NAME",
    "CacheBehavior",
    "DuplicateParameterRuleError",
    "GatewayStatus",
    "InvalidParameterRuleError",
    "ParameterContractEntry",
    "ParameterProjectionRule",
    "ParameterRuleError",
    "ParameterSchema",
    "ParameterValidationError",
    "ProjectionKind",
    "ProviderDiscoverySnapshot",
    "ProviderParameterObservation",
    "ProviderSupport",
    "ProviderToolObservation",
    "SchemaItemType",
    "SchemaType",
    "ToolCapability",
    "TransportCapability",
    "compose_contract_entries",
    "inline_supported_parameters",
    "normalize_rules",
    "overlay_observations",
    "overlay_tool_capabilities",
    "stream_transport_capability",
    "supported_tool_types",
]
