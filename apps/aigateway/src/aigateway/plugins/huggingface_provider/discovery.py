"""OME-479 §6.2 — Hugging Face public-catalog parsers (PURE).

FEATURE: Hugging Face P0 observation overlay. Two kinds of evidence, kept apart:

- BACKEND-CONDITIONAL capability from the FIXED public router catalog
  (`/v1/models`): for the selected backend, the tool / structured-output / modality
  facts (source label ``huggingface:router``);
- labelled-static PARAMETER evidence (``huggingface:static``): the standard sampling
  fields the INSTALLED litellm ``HuggingFaceChatConfig`` transform accepts, used as
  the detail contract's observation source. HF's catalog carries NO parameter list
  (§5.1), so parameters can only come from this labelled-static fallback.

INVARIANT (SOLID/hexagonal): the parsing is pure — functions over an already-fetched
document, NO clock and NO credentials. The single async entry point below reaches the
network only through the INJECTED bounded transport (``core/parameter_discovery``),
never a raw client and never a caller-supplied URL.
INVARIANT (§5.1): capability and parameter evidence carry DISTINCT source labels.
INVARIANT (§5.3): a model or backend absent from the catalog yields ``None`` —
honest absence, never fabricated support.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aigateway.core.chat_parameters import (
    ProviderDiscoverySnapshot,
    ProviderParameterObservation,
    ProviderSupport,
    ProviderToolObservation,
)
from aigateway.core.input_modalities import InputModality, normalize_input_modalities
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    fetch_discovery_json,
)
from aigateway.core.plugin_base import ModelDiscoverySource

# Fixed public source (the async fetch step passes this to the bounded transport;
# the parsers below never dereference a URL themselves).
MODELS_URL = "https://router.huggingface.co/v1/models"
ALLOWED_ORIGINS: frozenset[str] = frozenset({"https://router.huggingface.co"})

# Live catalog capability evidence vs labelled-static parameter evidence — DISTINCT
# provenance so a reader can tell network-derived capability from a reviewed-static
# parameter fallback (§5.1 "labelled").
ROUTER_SOURCE = "huggingface:router"
STATIC_SOURCE = "huggingface:static"

# INVARIANT: the revision names the SOURCE **and the gateway-side reading** of it,
# because the observation cache decides a stored entry's trustworthiness by matching
# it. Bump this whenever the projection below changes what the same bytes mean.
ROUTER_SOURCE_REVISION = "huggingface:router:bounded-backend-capabilities-2026-07"

_MAX_CATALOG_MODELS = 10_000
_MAX_MODEL_PROVIDERS = 512

# The one OpenAI-compatible tool type the router speaks. `supports_tools` is a single
# boolean, so it can only ever describe function calling.
_FUNCTION_TOOL = "function"


@dataclass(frozen=True)
class HfBackendCapabilities:
    """Per-BACKEND capability facts for one model row (§6.2 backend-conditional).

    # INVARIANT: a capability absent from the backend row stays ``None`` (UNKNOWN),
    # never coerced to ``False`` — the catalog lists positive support, and silence
    # is not a negative verdict.
    """

    input_modalities: tuple[str, ...]
    output_modalities: tuple[str, ...]
    supports_tools: bool | None
    supports_structured_output: bool | None


def _modalities(architecture: Any, key: str) -> tuple[str, ...]:
    if not isinstance(architecture, Mapping):
        return ()
    values = architecture.get(key)
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str))


def _bool_or_none(value: Any) -> bool | None:
    # WHY: only a genuine JSON boolean is a verdict; anything else is UNKNOWN.
    return value if isinstance(value, bool) else None


def parse_hf_backend_capabilities(
    catalog: Any, *, upstream_model_id: str, backend: str
) -> HfBackendCapabilities | None:
    """Capability facts for one model+backend, or ``None`` if either is absent.

    The catalog keys rows by the bare ``<org>/<model>`` id; the ``:<provider>``
    backend is one entry in that row's ``providers[]`` array. Support is read from
    the SELECTED backend only, so the verdict is backend-conditional (§6.2).
    """
    if not isinstance(catalog, Mapping):
        return None
    data = catalog.get("data")
    if not isinstance(data, list):
        return None
    if len(data) > _MAX_CATALOG_MODELS:
        raise DiscoveryError("model_catalog_too_large")
    row = next(
        (m for m in data if isinstance(m, Mapping) and m.get("id") == upstream_model_id),
        None,
    )
    if row is None:
        return None
    providers = row.get("providers")
    if not isinstance(providers, list):
        return None
    if len(providers) > _MAX_MODEL_PROVIDERS:
        raise DiscoveryError("provider_catalog_too_large")
    entry = next(
        (p for p in providers if isinstance(p, Mapping) and p.get("provider") == backend),
        None,
    )
    if entry is None:
        return None
    architecture = row.get("architecture")
    return HfBackendCapabilities(
        input_modalities=_modalities(architecture, "input_modalities"),
        output_modalities=_modalities(architecture, "output_modalities"),
        supports_tools=_bool_or_none(entry.get("supports_tools")),
        supports_structured_output=_bool_or_none(entry.get("supports_structured_output")),
    )


def _verdict(flag: bool) -> ProviderSupport:
    return "supported" if flag else "unsupported"


def _router_observation(name: str, flag: bool) -> ProviderParameterObservation:
    return ProviderParameterObservation(
        request_path=name, support=_verdict(flag), source=ROUTER_SOURCE
    )


def project_backend_capabilities(
    capabilities: HfBackendCapabilities | None,
) -> tuple[tuple[ProviderParameterObservation, ...], tuple[ProviderToolObservation, ...]]:
    """Turn one backend's capability facts into published evidence (OME-631).

    FEATURE: backend-conditional tool and structured-output reporting. ``tools`` and
    ``tool_choice`` are request paths while ``function`` is a tool type, but ONE
    catalog boolean decides all three — so they are emitted together here rather
    than derived twice, and the detailed contract cannot contradict itself.

    INVARIANT: ``supports_tools`` and ``supports_structured_output`` are INDEPENDENT
    verdicts. The live catalog contains backends that do function calling but not
    structured output, so neither may be inferred from the other.
    INVARIANT (§5.3): ``None`` is silence, not a negative. An absent flag, row or
    backend contributes nothing and leaves the labelled-static evidence standing.
    """
    if capabilities is None:
        return (), ()
    parameters: list[ProviderParameterObservation] = []
    tools: tuple[ProviderToolObservation, ...] = ()
    if capabilities.supports_tools is not None:
        flag = capabilities.supports_tools
        parameters.extend(_router_observation(name, flag) for name in ("tool_choice", "tools"))
        tools = (ProviderToolObservation(tool_type=_FUNCTION_TOOL, support=_verdict(flag)),)
    if capabilities.supports_structured_output is not None:
        parameters.append(
            _router_observation("response_format", capabilities.supports_structured_output)
        )
    return tuple(sorted(parameters, key=lambda o: o.request_path)), tools


def parse_router_capability_snapshot(
    catalog: Any, *, upstream_model_id: str, backend: str
) -> ProviderDiscoverySnapshot:
    """Read the router catalog into a snapshot for ONE model+backend pair.

    INVARIANT (§5.1): this is per-MODEL evidence, so it lands in
    ``model_observations`` — never ``endpoint_observations``, which the overlay
    treats as the LESS specific claim.
    AIDEV-NOTE: deliberately NOT closed-world, unlike the OpenRouter catalog. A row
    lists the backends the router serves and carries no parameter vocabulary at all,
    so an absent key is an unknown deployment, not a capability denial. Do not
    "align" this with the OpenRouter reading — the documents make different claims.
    """
    parameters, tools = project_backend_capabilities(
        parse_hf_backend_capabilities(catalog, upstream_model_id=upstream_model_id, backend=backend)
    )
    return ProviderDiscoverySnapshot(
        source_revision=ROUTER_SOURCE_REVISION,
        model_observations=parameters,
        tool_observations=tools,
    )


# OME-1537: the router's modality words the gateway vocabulary shares. The live
# catalogue lists only ``text``/``image`` today; anything else (audio, video) has no
# gateway equivalent and is dropped rather than approximated.
_HF_MODALITIES: frozenset[str] = frozenset({"text", "image"})

# INVARIANT: declared before any fetch, like every discovery source (OME-972). The
# listing is one process-local document per provider, shared across accounts.
LIVE_MODALITIES_DISCOVERY_SOURCE = ModelDiscoverySource(
    key="huggingface:models:modalities",
    revision="huggingface:models:modalities-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)


def parse_router_input_modalities(catalog: Any) -> dict[str, tuple[InputModality, ...]]:
    """Per-``<org>/<model>`` input modalities from the router catalogue (OME-1537).

    Reads the same ``architecture.input_modalities`` field as
    ``parse_hf_backend_capabilities`` — per MODEL, not per backend, because the
    catalogue states it on the row. Absent/malformed evidence leaves the id out
    (unknown -> text-only downstream); only an over-cap document raises.
    """
    if not isinstance(catalog, Mapping):
        return {}
    data = catalog.get("data")
    if not isinstance(data, list):
        return {}
    if len(data) > _MAX_CATALOG_MODELS:
        raise DiscoveryError("model_catalog_too_large")
    evidence: dict[str, tuple[InputModality, ...]] = {}
    for row in data:
        if not isinstance(row, Mapping):
            continue
        model_id = row.get("id")
        architecture = row.get("architecture")
        if not isinstance(model_id, str) or not isinstance(architecture, Mapping):
            continue
        raw = architecture.get("input_modalities")
        if not isinstance(raw, list):
            continue
        evidence[model_id] = normalize_input_modalities(v for v in raw if v in _HF_MODALITIES)
    return evidence


async def discover_router_input_modalities(
    *, client: DiscoveryHttpClient, limits: DiscoveryLimits | None = None
) -> dict[str, tuple[InputModality, ...]]:
    """Fetch the fixed public router catalogue and read every row's modalities.

    INVARIANT: a transport failure PROPAGATES as ``DiscoveryError`` so the model
    catalog serves its last good listing or the text-only seeds — never a guess.
    """
    catalog = await fetch_discovery_json(
        MODELS_URL,
        allowed_origins=ALLOWED_ORIGINS,
        client=client,
        limits=limits or DiscoveryLimits(),
    )
    # INVARIANT: an HTTP 200 that is not a ``{"data": [...]}`` catalogue (maintenance
    # page, envelope change) is a FAILED read, not fresh "no evidence" — returning
    # ``{}`` would let the catalog replace a last-good image-capable snapshot with
    # text-only rows for a whole TTL. Leniency stays on optional per-row fields only.
    if not isinstance(catalog, Mapping) or not isinstance(catalog.get("data"), list):
        raise DiscoveryError("malformed_json")
    return parse_router_input_modalities(catalog)


async def discover_huggingface_snapshot(
    upstream_model_id: str,
    *,
    backend: str,
    client: DiscoveryHttpClient,
    limits: DiscoveryLimits | None = None,
) -> ProviderDiscoverySnapshot:
    """Fetch the fixed public router catalog and project the pinned backend's row.

    INVARIANT (§5.3): a transport failure PROPAGATES as ``DiscoveryError``. An empty
    snapshot means "reached the source; it lists nothing for this pair" — letting a
    failure return one would have the cache store an outage labelled fresh.
    """
    catalog = await fetch_discovery_json(
        MODELS_URL,
        allowed_origins=ALLOWED_ORIGINS,
        client=client,
        limits=limits or DiscoveryLimits(),
    )
    return parse_router_capability_snapshot(
        catalog, upstream_model_id=upstream_model_id, backend=backend
    )


# OME-479 §6.2 — labelled-static PARAMETER evidence (NO network). The standard
# OpenAI sampling fields the INSTALLED litellm ``HuggingFaceChatConfig`` transform
# (a subclass of ``OpenAIGPTConfig``) accepts and forwards — verified against the
# installed transform's ``get_supported_openai_params`` / ``transform_request``. HF
# has no native ``top_k``, so it is intentionally NOT listed (honest absence). Tool
# capabilities are reported in their own contract section, and the ``tools`` /
# ``tool_choice`` request-path observations are contributed at the plugin level
# (``tool_parameter_observations`` over the plugin's tool capabilities, OME-583) —
# kept OUT of this sampling constant so it stays a pure sampling-field inventory.
# AIDEV-NOTE: reviewed labelled-static evidence, not a central inventory — extend
# only for a SAMPLING field the installed transform provably accepts; tool request
# paths are added via the plugin's tool observations, never here.
_STATIC_PARAM_NAMES: tuple[str, ...] = (
    "temperature",
    "top_p",
    "max_tokens",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "stop",
)


def _observation(name: str) -> ProviderParameterObservation:
    return ProviderParameterObservation(
        request_path=name, support="supported", source=STATIC_SOURCE
    )


HF_STATIC_PARAM_OBSERVATIONS: tuple[ProviderParameterObservation, ...] = tuple(
    _observation(name) for name in sorted(_STATIC_PARAM_NAMES)
)
