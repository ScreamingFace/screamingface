"""OME-479 model-row capability projection (application-layer composition).

FEATURE: effective model-capability contract. Wires each provider plugin's OWN
rules/tools/auth-modes (the Strategy) through the pure ``chat_parameters``
algebra into the locked ``/v1/models`` row shape.

INVARIANT (SOLID/hexagonal): no provider-name switch and no central provider
inventory live here. The plugin selects the rules it owns; this module only
composes them. The inline summary and the detailed contract read the SAME
plugin rule source, so they cannot drift.

INVARIANT (conservative subset): the inline ``/v1/models`` summary is the cross-auth
INTERSECTION of the rule set — a subset of any single auth mode's enabled detail, NOT
an exact copy. An api-key-only field is enabled in the api-key detail yet absent from
the summary; that asymmetry is intentional (never overclaim an auth-specific field
profile-independently), so the summary must never be "reconciled" to equal the detail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from .chat_parameters import (
    inline_supported_parameters,
    normalize_rules,
    supported_tool_types,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .plugin_base import ModelEntry, ProviderPluginBase

# INVARIANT: unsupported_parameter_behavior is the literal 'reject' in schema
# version 1 (fail closed — unknown/disabled params never silently pass).
UNSUPPORTED_PARAMETER_BEHAVIOR = "reject"


def canonical_model_id(*, custom_llm_provider: str, model_name: str) -> str:
    """Return the canonical, provider-prefixed public id for a model.

    Order (plan 4.1): keep ``model_name`` unchanged when it already begins with
    ``<custom_llm_provider>/``; otherwise prefix it.

    WHY: the id is derived from ``model_name`` (the AIGateway provider
    namespace), NEVER from ``litellm_params['model']`` which may carry a
    LiteLLM-only transport prefix such as ``ollama_chat/``. Because the prefix
    is the owning plugin's ``custom_llm_provider`` (a unique registry key),
    resolving the first path segment returns the same plugin and the id
    dispatches unchanged to ``/v1/chat/completions``.
    """
    prefix = f"{custom_llm_provider}/"
    return model_name if model_name.startswith(prefix) else f"{prefix}{model_name}"


def canonical_ids(
    plugin: ProviderPluginBase, entries: Iterable[ModelEntry] | None
) -> frozenset[str]:
    """The canonical ids of a listing — exactly what ``/v1/models`` publishes.

    # INVARIANT: canonicalized, because ``model_row`` canonicalizes too. A provider
    # using the established unprefixed ``model_name`` convention would otherwise
    # publish an id this set never matches, and the detail route would 404 its own
    # listing. ``None`` (no live listing) is an empty set, never an error: this widens
    # a known-id set, it never gates one.
    """
    if entries is None:
        return frozenset()
    return frozenset(
        canonical_model_id(
            custom_llm_provider=plugin.custom_llm_provider, model_name=entry.model_name
        )
        for entry in entries
    )


def parameter_contract_url(canonical_id: str) -> str:
    """Same-origin relative URL for the optional detailed parameter contract."""
    return f"/v1/model-parameters?model={quote(canonical_id, safe='')}"


def model_row(plugin: ProviderPluginBase, entry: ModelEntry) -> dict[str, Any]:
    """Compose one locked ``/v1/models`` row from a plugin's own rule set."""
    canonical_id = canonical_model_id(
        custom_llm_provider=plugin.custom_llm_provider, model_name=entry.model_name
    )
    # normalize_rules enforces the one-rule-per-path invariant at the boundary,
    # so the summary, the detail, and dispatch cannot disagree about a path.
    rules = normalize_rules(plugin.chat_parameter_rules(model=canonical_id, auth_type=None))
    tools = plugin.chat_parameter_tools(model=canonical_id, auth_type=None)
    return {
        "id": canonical_id,
        "object": "model",
        "owned_by": plugin.custom_llm_provider,
        "supported_parameters": list(
            inline_supported_parameters(rules, available_auth_modes=plugin.available_auth_modes())
        ),
        "supported_tools": list(supported_tool_types(tools)),
        "unsupported_parameter_behavior": UNSUPPORTED_PARAMETER_BEHAVIOR,
        "parameter_contract_url": parameter_contract_url(canonical_id),
    }
