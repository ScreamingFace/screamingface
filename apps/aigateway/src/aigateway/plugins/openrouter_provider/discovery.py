"""OME-479 §6.1 — OpenRouter public-catalog discovery.

FEATURE: OpenRouter P0 observation overlay. Turns OpenRouter's two FIXED public
documents into raw ``ProviderParameterObservation`` evidence:

- the per-model ``/api/v1/models`` catalog → per-model ``supported_parameters``;
- the public OpenAPI 3 document → the chat request schema's accepted fields.

INVARIANT (SOLID/hexagonal): both parsers are pure functions over already-fetched,
already-bounded documents. They own NO network, NO clock, NO credentials — the
bounded transport (``core/parameter_discovery``) and the async fetch step below
supply the documents. Keeping parsing pure makes every shape deterministic and
fixture-testable, and keeps the safety envelope in one place.

INVARIANT (§5.1): endpoint and per-model evidence carry DISTINCT source labels and
are never merged into one support verdict here.
INVARIANT (§5.3): a model missing from the catalog, or a malformed row, yields NO
observations — honest absence, never fabricated support.

AIDEV-NOTE (OME-653): the OpenAPI shape reader lives in ``openapi_schema`` and the
shared observation vocabulary in ``observations``, purely to keep each file within
the repository's 450-line limit. THIS module stays the import path for both
parsers and for every source label — ``parse_openapi_endpoint_observations`` is
re-exported here rather than imported from its half.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aigateway.core.chat_parameters import (
    ProviderDiscoverySnapshot,
    ProviderParameterObservation,
)
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    DiscoverySourceRef,
    fetch_discovery_json,
)
from aigateway.core.parameter_projection import GATEWAY_OWNED_FIELDS

from .observations import LOCAL_SOURCE, MODEL_SOURCE, _dedup_sorted, _observation
from .openapi_schema import openapi_request_schema_present, parse_openapi_endpoint_observations
from .settings import GATEWAY_MODEL_PREFIX, is_valid_upstream_model_id

# Fixed public sources (the async fetch step passes these to the bounded
# transport; the parsers below never dereference a URL themselves).
MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENAPI_URL = "https://openrouter.ai/openapi.json"
ALLOWED_ORIGINS: frozenset[str] = frozenset({"https://openrouter.ai"})

# The component holding the chat endpoint's request body in OpenRouter's document.
# AIDEV-NOTE: verified against the live document 2026-07-28 — it is ``ChatRequest``,
# NOT the OpenAI-ish ``ChatCompletionRequest`` one might assume. A wrong name here
# does not raise: ``parse_openapi_endpoint_observations`` returns () for a schema it
# cannot find, so the whole endpoint source would go silently empty. That failure
# mode is exactly why this name is pinned by a wiring test through the real route
# and not by a fixture alone.
CHAT_REQUEST_SCHEMA = "ChatRequest"

# Cardinality limits are distinct from the transport's byte/node envelope: they
# bound the number of contract observations one accepted document can generate.
_MAX_CATALOG_MODELS = 10_000
_MAX_PARAMETER_NAMES = 512


def _listed_parameters(row: Any) -> set[str] | None:
    """The row's ``supported_parameters`` as a name set, or None when unreadable."""
    if not isinstance(row, Mapping):
        return None
    params = row.get("supported_parameters")
    if not isinstance(params, list):
        return None
    if len(params) > _MAX_PARAMETER_NAMES:
        raise DiscoveryError("parameter_catalog_too_large")
    # Gateway-owned fields are protocol plumbing, never model parameters; excluding
    # them here keeps them out of BOTH the vocabulary and the verdicts, so a row
    # that omits one can never produce an "unsupported stream" contract row.
    return {
        param
        for param in params
        if isinstance(param, str) and param and param not in GATEWAY_OWNED_FIELDS
    }


def _catalog_vocabulary(rows: list[Any]) -> frozenset[str]:
    """Every parameter name this catalog DOCUMENT tracks, across all its rows.

    # WHY derived from the payload instead of a reviewed constant: it is what makes
    # the closed-world reading below sound. A name some row lists is demonstrably
    # part of OpenRouter's capability vocabulary, so another row's omission of it
    # is a real signal. A name NO row mentions is one the catalog does not model at
    # all (``n``, ``logprobs``), and calling that "unsupported" would fabricate a
    # negative — and wrongly overwrite reviewed labelled-local evidence for a field
    # the endpoint does accept. A constant would also silently rot as OpenRouter's
    # vocabulary grows; the document cannot.
    """
    vocabulary: set[str] = set()
    for row in rows:
        listed = _listed_parameters(row)
        if listed is not None:
            vocabulary |= listed
            if len(vocabulary) > _MAX_PARAMETER_NAMES:
                raise DiscoveryError("parameter_catalog_too_large")
    return frozenset(vocabulary)


def parse_catalog_model_ids(catalog: Any) -> frozenset[str] | None:
    """The set of upstream model ids the public catalog document lists (OME-879).

    Membership evidence for dynamic admission, nothing more. Returns ``None``
    for an unreadable document so the caller can refuse with a distinct
    "catalog unavailable" verdict — an outage must never read as "your model is
    a typo" (that refusal would wrongly tell the user to fix a correct id).
    """
    if not isinstance(catalog, Mapping):
        return None
    data = catalog.get("data")
    if not isinstance(data, list):
        return None
    if len(data) > _MAX_CATALOG_MODELS:
        raise DiscoveryError("model_catalog_too_large")
    return frozenset(
        row["id"] for row in data if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    )


def parse_model_catalog_observations(
    catalog: Any, *, upstream_model_id: str
) -> tuple[ProviderParameterObservation, ...]:
    """Per-model evidence from the public ``/api/v1/models`` catalog.

    CLOSED-WORLD INSIDE A PRESENT ROW (OME-629). OpenRouter documents
    ``supported_parameters`` as "array of supported API parameters for this model"
    and lets the catalog be FILTERED by it (``/models?supported_parameters=tools``),
    which only works if each array is complete enough for negative filtering. So
    within a row that exists and parses, an omission is a genuine ``unsupported``
    verdict — but only for a name the document's own vocabulary proves the catalog
    tracks (see ``_catalog_vocabulary``); outside that vocabulary the source is
    SILENT, and silence yields no observation in either direction.

    # AIDEV-NOTE: this REPLACES the earlier open-world reading ("an unlisted field
    # is left unknown, never marked unsupported"), which made every model's
    # evidence a subset of the same static inventory and could never report a
    # per-model gap. Reverting it would silently re-break that.
    # INVARIANT: an unreadable document, an absent row, or a malformed array yields
    # NO observations — the labelled-local evidence then serves. Absence of a
    # readable source is never turned into a wall of negatives.
    # INVARIANT: this is EVIDENCE. A negative verdict here narrows what the contract
    # CLAIMS; it never disables a rule and never blocks dispatch.
    """
    if not isinstance(catalog, Mapping):
        return ()
    data = catalog.get("data")
    if not isinstance(data, list):
        return ()
    if len(data) > _MAX_CATALOG_MODELS:
        raise DiscoveryError("model_catalog_too_large")
    row = next(
        (m for m in data if isinstance(m, Mapping) and m.get("id") == upstream_model_id),
        None,
    )
    if row is None:
        return ()
    supported = _listed_parameters(row)
    if supported is None:
        return ()
    return _dedup_sorted(
        [
            _observation(
                param,
                source=MODEL_SOURCE,
                support="supported" if param in supported else "unsupported",
            )
            for param in _catalog_vocabulary(data)
        ]
    )


# OME-479 §5.3 — REVIEWED labelled-local endpoint evidence (NO network). The
# OpenRouter chat endpoint's accepted optional SAMPLING/GENERATION fields, used
# as the detail contract's observation source in v1. Each name is backed by
# verified public ``supported_parameters``; native fields map through the wrapper
# so an observation lines up with its rule. Tool capabilities are reported in their
# own contract section, and the ``tools`` / ``tool_choice`` request-path observations
# are contributed at the plugin level (``tool_parameter_observations`` over the
# plugin's tool capabilities, OME-583) — kept OUT of this sampling constant so it
# stays a pure sampling-field inventory.
# AIDEV-NOTE: provider-local REVIEWED evidence, not a central inventory — extend
# deliberately, and only for a SAMPLING field the public catalog proves the endpoint
# takes; tool request paths are added via the plugin's tool observations, never here.
_REVIEWED_ENDPOINT_PARAMS: tuple[str, ...] = (
    "temperature",
    "top_p",
    "top_k",
    "max_tokens",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "stop",
    # OME-993: OpenRouter documents the OpenAI-compat reasoning-effort field on the
    # chat endpoint (public `supported_parameters` carries `reasoning`); the installed
    # litellm transform forwards it top-level (tripwire in
    # test_openrouter_parameter_projection).
    "reasoning_effort",
)

REVIEWED_ENDPOINT_OBSERVATIONS: tuple[ProviderParameterObservation, ...] = _dedup_sorted(
    [_observation(name, source=LOCAL_SOURCE) for name in _REVIEWED_ENDPOINT_PARAMS]
)


# Source identity for a LIVE snapshot, and the cache revision it is stored under.
# The cache TTL — not this constant — governs freshness; the revision identifies
# the SOURCE together with the gateway-side READING of it.
# AIDEV-NOTE: bump this whenever the reading changes, not only when the URL does.
# The closed-world tag marks the OME-629 per-model reading; the source-pair tag
# marks OME-647, where a snapshot stopped being one document and became two. In
# both cases the same bytes now yield a different snapshot, so entries cached
# under the previous label must not be reused — that is what the guard is for.
SNAPSHOT_SOURCE_REVISION = "openrouter:models+openapi:bounded-source-pair-2026-07"

# Source-specific bounds for the OpenAPI document (§5.2 stays enforced — these are
# the bounds, not an exemption from them). MEASURED against the live document on
# 2026-07-28: 1,660,091 bytes, max depth 22, 38,055 nodes. The shared defaults
# (1,000,000 bytes / depth 16) reject it outright on TWO axes, and its node count
# already sits at 76% of the shared node ceiling.
# WHY per-source rather than a global increase: the models catalog is small and flat,
# and raising the envelope for every provider's every fetch to accommodate one large
# document would spend the safety margin where it was not needed. These values give
# the measured document roughly 2.4x headroom on bytes and nodes so ordinary upstream
# growth does not silently degrade the contract, while still capping memory.
# The timeout is widened for the same measured reason: reading 1.6 MB inside the 3s
# budget sized for the catalog needs a sustained ~550 KB/s, and a miss degrades the
# WHOLE snapshot (see the partial-source note below), not just this half.
_OPENAPI_MIN_TIMEOUT_S = 10.0
_OPENAPI_MIN_BYTES = 4_000_000
_OPENAPI_MIN_DEPTH = 32
_OPENAPI_MIN_NODES = 150_000


def upstream_model_for_discovery(model: str) -> str | None:
    """The upstream catalog key for a gateway id, or None when there is none.

    ONE predicate shared by ``chat_discovery_source`` and
    ``discover_chat_parameter_snapshot``: the source declaration and the fetch must
    agree on exactly which ids are discoverable, or the runtime sees a provider that
    promised evidence and then reported NO ATTEMPT. It applies the SAME strip as
    ``prepare_chat_body``, so discovery and dispatch also agree on model identity.
    """
    if not model.startswith(GATEWAY_MODEL_PREFIX):
        return None
    upstream = model[len(GATEWAY_MODEL_PREFIX) :]
    return upstream if is_valid_upstream_model_id(upstream) else None


def openrouter_chat_discovery_source(model: str) -> DiscoverySourceRef | None:
    """Declare the public catalog for ``model``, or nothing when it is not ours.

    OME-629: declared BEFORE any fetch, so the observation cache can judge a stored
    entry's trustworthiness without paying for a round trip. The revision names the
    reading as well as the source.

    # INVARIANT: the SAME predicate gates this and the fetch below — a model this
    # provider cannot dispatch has nothing to discover. Owning it here (rather than
    # only in the fetch) makes "declared a source, then reported NOT ATTEMPTED"
    # structurally unreachable, which is the one inconsistency the runtime cannot
    # distinguish from a real outage.
    # AIDEV-NOTE (OME-647): ``source`` is the provider's CACHE-KEY label, not a
    # published claim about which document an observation came from — that provenance
    # rides on each observation. The snapshot draws on the catalog AND the OpenAPI
    # document, and the REVISION names the pair.
    """
    if upstream_model_for_discovery(model) is None:
        return None
    return DiscoverySourceRef(source=MODEL_SOURCE, revision=SNAPSHOT_SOURCE_REVISION)


async def discover_openrouter_chat_snapshot(
    model: str,
    *,
    client: DiscoveryHttpClient,
    limits: DiscoveryLimits | None = None,
) -> ProviderDiscoverySnapshot | None:
    """The DYNAMIC source for a gateway model id (OME-479 §5.1).

    Strips the gateway prefix to the upstream id the public catalog is keyed by — the
    SAME rule as ``prepare_chat_body``, so discovery and dispatch agree on identity. A
    value that is not a valid gateway id is not dispatchable, so there is nothing to
    discover: return None WITHOUT opening a connection — NOT ATTEMPTED, which is a
    different claim from "attempted and failed".

    # INVARIANT: never enables a parameter (only a rule does); off the chat dispatch
    # path; a sanitized DiscoveryError from the fetch PROPAGATES so the cache can
    # degrade honestly rather than store a failure as fresh.
    """
    upstream = upstream_model_for_discovery(model)
    if upstream is None:
        return None
    return await discover_openrouter_snapshot(upstream, client=client, limits=limits)


def openapi_discovery_limits(limits: DiscoveryLimits) -> DiscoveryLimits:
    """The operator's bounds, WIDENED where the OpenAPI document provably needs it.

    # INVARIANT (widen, never narrow): every axis is a ``max`` against what the
    # operator configured, so an installation that has deliberately raised a bound
    # keeps it. This helper can only ever admit more, never silently tighten a
    # limit an operator chose.
    """
    return DiscoveryLimits(
        timeout_s=max(limits.timeout_s, _OPENAPI_MIN_TIMEOUT_S),
        max_bytes=max(limits.max_bytes, _OPENAPI_MIN_BYTES),
        max_json_depth=max(limits.max_json_depth, _OPENAPI_MIN_DEPTH),
        max_json_nodes=max(limits.max_json_nodes, _OPENAPI_MIN_NODES),
    )


async def discover_openrouter_snapshot(
    upstream_model_id: str,
    *,
    client: DiscoveryHttpClient,
    limits: DiscoveryLimits | None = None,
) -> ProviderDiscoverySnapshot:
    """Fetch BOTH fixed public documents and return the provider's live evidence.

    §5.1 names a source PAIR: the ``/api/v1/models`` catalog for what one model
    supports, and the public OpenAPI document for what the endpoint accepts, its
    field shapes, and their lifecycle. Both are fetched through the injected bounded
    transport; the OpenAPI half under its own measured bounds.

    # INVARIANT (§5.3): reaching the source and failing to reach it are DIFFERENT
    # outcomes and get different signals. A successful fetch whose catalog lacks
    # the model returns a present-but-empty snapshot — the honest "reached it,
    # found nothing" — while a sanitized ``DiscoveryError`` PROPAGATES.
    # AIDEV-NOTE: do not reintroduce a ``return None`` here. Swallowing made a
    # failure indistinguishable from "no evidence", and ``ObservationCache`` reads
    # any normal return as a successful refresh — so a swallowed outage was stored
    # labelled ``fresh``, evicting the last good snapshot. Raising is precisely
    # what routes it to the stale/degraded paths. It also preserves the reason
    # code, which ``None`` discards.
    # WHY a PARTIAL failure also propagates: one snapshot is one revision's evidence
    # from both documents, and the cache stores whatever is returned as a successful
    # refresh. Returning the half that succeeded would therefore cache a contract
    # that is silently missing the other half — the same swallowing bug in a new
    # place. Trade-off, accepted deliberately: the catalog evidence that ships today
    # now degrades whenever the larger OpenAPI document is unreachable, which the
    # stale/degraded machinery already handles honestly.
    # INVARIANT (§5.1): the two kinds stay in SEPARATE snapshot fields and keep
    # DISTINCT source labels; nothing here merges them into one support verdict.
    """
    effective = limits or DiscoveryLimits()
    catalog = await fetch_discovery_json(
        MODELS_URL,
        allowed_origins=ALLOWED_ORIGINS,
        client=client,
        limits=effective,
    )
    openapi = await fetch_discovery_json(
        OPENAPI_URL,
        allowed_origins=ALLOWED_ORIGINS,
        client=client,
        limits=openapi_discovery_limits(effective),
    )
    if not openapi_request_schema_present(openapi, schema_name=CHAT_REQUEST_SCHEMA):
        raise DiscoveryError("schema_not_found")
    endpoint_observations = parse_openapi_endpoint_observations(
        openapi, schema_name=CHAT_REQUEST_SCHEMA
    )
    if not endpoint_observations:
        raise DiscoveryError("schema_not_found")
    return ProviderDiscoverySnapshot(
        source_revision=SNAPSHOT_SOURCE_REVISION,
        endpoint_observations=endpoint_observations,
        model_observations=parse_model_catalog_observations(
            catalog, upstream_model_id=upstream_model_id
        ),
    )
