"""OME-479 detailed ``/v1/model-parameters`` document composition (app layer).

FEATURE: profile-bound detailed parameter contract. Overlays a provider plugin's
OWN observations with its OWN gateway rules (the SAME rule source as the
``/v1/models`` summary) into the locked v1 document, and derives the opaque
``contract_id`` / ``context.revision`` digests.

INVARIANT (purity): this composer takes no clock and does no I/O. ``freshness``
and the opaque ``context_identity`` token are supplied by the caller, so the
document is a deterministic function of its inputs — which is what lets the
digests be reproducible and testable.

INVARIANT (privacy): the digests are one-way SHA-256 over non-secret identity and
version inputs. The raw inputs — account ids, connection ids, credential names,
secrets — are hashed, never echoed, so they cannot be recovered from the output.

INVARIANT (SOLID/hexagonal): no provider-name switch and no central inventory
live here; the plugin selects its rules/observations/tools/transport and this
module only composes them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from .chat_parameters import compose_contract_entries, normalize_rules

if TYPE_CHECKING:
    from .chat_parameters import (
        ParameterProjectionRule,
        ParameterSchema,
        ProviderParameterObservation,
        ToolCapability,
        TransportCapability,
    )
    from .profile_models import AuthMode

SCHEMA_VERSION = 1

_CONTRACT_ID_PREFIX = "pc_"
_CONTEXT_REVISION_PREFIX = "ctx_"
# Unit separator: forbidden in every digest input (ids, paths, enums), so joined
# fields cannot collide across differently-structured inputs.
_SEP = "\x1f"
_DIGEST_HEX = 40


def upstream_model_id(canonical_id: str) -> str:
    """Return the model-author id: the canonical id minus its owning provider.

    WHY: derived from the canonical public id (AIGateway namespace), never from a
    LiteLLM transport prefix such as ``ollama_chat/`` (plan 4.1).
    """
    return canonical_id.split("/", 1)[1] if "/" in canonical_id else canonical_id


def _sha(parts: Iterable[str]) -> str:
    return hashlib.sha256(_SEP.join(parts).encode("utf-8")).hexdigest()


def _schema_key(schema: ParameterSchema | None) -> str:
    # WHY: fold the VALIDATION SCHEMA into the revision so a range/enum/type change
    # moves the contract id even when the hand-authored projection_revision string is
    # unchanged. Canonical (sorted keys) + order-independent; empty when absent.
    if schema is None:
        return ""
    return json.dumps(schema.to_json_schema(), sort_keys=True, separators=(",", ":"))


def _rules_revision(rules: tuple[ParameterProjectionRule, ...]) -> str:
    # INVARIANT: the gateway projection revision changes when a rule is added,
    # removed, or revised — INCLUDING a change to its validation schema (range,
    # enum, type) — so the contract id always moves with dispatch behavior.
    return _sha(
        f"{r.request_path}|{r.projection_kind}|{r.cache_behavior}|{r.projection_revision}"
        f"|{','.join(r.applicable_auth_modes)}|{_schema_key(r.parameter_schema)}"
        for r in rules  # normalized: deterministically ordered, one per path
    )


def _evidence_revision(observations: Iterable[ProviderParameterObservation]) -> str:
    # The provider evidence revision changes when any observed field/support/
    # source/staleness changes. Sorted so input order is irrelevant.
    # INVARIANT: the observation SCHEMA is folded in too, because it is PUBLISHED —
    # directly for every disabled entry, and as the fallback for an enabled entry
    # whose rule carries no schema of its own (``compose_contract_entries``).
    # INVARIANT: so is the LIFECYCLE verdict (OME-647). It is published as
    # ``provider.deprecated``, and the tri-state is encoded distinctly — "" for the
    # silent case, so a source that starts declaring a field CURRENT moves the
    # identity just as a source that starts declaring it deprecated does.
    return _sha(
        sorted(
            f"{o.request_path}|{o.support}|{o.source}|{int(o.stale)}"
            f"|{_schema_key(o.parameter_schema)}"
            f"|{'' if o.deprecated is None else int(o.deprecated)}"
            for o in observations
        )
    )


def _section_revision(section: Mapping[str, Any]) -> str:
    """Digest of an already-SERIALIZED document section, keyed by published key.

    WHY digest the serialized form rather than the capability objects: coverage
    then holds structurally instead of by memory. A field added to a capability's
    ``to_dict`` reaches the digest with no second edit — whereas a hand-listed
    field set is exactly the kind of "keep these two in sync" seam that let tools
    and transport drop out of the contract identity in the first place.

    Sorted by key so input ordering is irrelevant; values are canonical JSON so an
    equal section always yields an equal digest.
    """
    return _sha(
        sorted(
            f"{key}|{json.dumps(value, sort_keys=True, separators=(',', ':'))}"
            for key, value in section.items()
        )
    )


def _opaque_id(prefix: str, tag: str, inputs: tuple[str, ...]) -> str:
    # ``tag`` is domain separation so contract_id and context.revision are
    # distinct values even though both hash the same input set (and both move
    # when ANY input changes).
    return prefix + _sha((tag, *inputs))[:_DIGEST_HEX]


def build_model_parameter_document(
    *,
    canonical_id: str,
    gateway_provider: str,
    auth_mode: AuthMode,
    scope: str,
    context_identity: str,
    rules: Iterable[ParameterProjectionRule],
    observations: Iterable[ProviderParameterObservation],
    tools: Iterable[ToolCapability],
    transport: Iterable[TransportCapability],
    freshness: dict[str, Any],
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Compose the locked v1 detailed contract for one (model, profile) context.

    ``source_revision`` is the discovered snapshot's SOURCE identity — which
    documents were read, under which gateway-side reading. It is optional because a
    provider with no dynamic source has none, and it is both PUBLISHED (under
    ``context``) and HASHED from this one argument, so the served value and the
    digest input cannot drift apart.
    """
    normalized = normalize_rules(rules)
    observations = tuple(observations)

    # Serialize the capability sections ONCE, then digest and serve the very same
    # objects — there is no second representation that could disagree.
    tools_section = {tool.tool_type: tool.to_dict() for tool in tools}
    transport_section = {cap.name: cap.to_dict() for cap in transport}

    projection_revision = _rules_revision(normalized)
    evidence_revision = _evidence_revision(observations)
    # INVARIANT: the digests identify parameter semantics, not every response field.
    # ``freshness`` is excluded because time-varying evidence would churn the id.
    # The route also adds ``context.execution_access`` AFTER composition: access
    # configuration is request-time information, deliberately outside this identity.
    # Consumers must not cache access state by contract_id or context.revision.
    # Other published sections are folded in: omitting a semantic
    # field fails DANGEROUSLY (a stale contract served under a frozen id), while
    # including a superfluous one fails SAFELY (extra churn). Include by default;
    # every exclusion is a stated decision. ``gateway_provider`` is hashed even
    # though the sole caller derives it from ``canonical_id`` — this composer takes
    # the two as independent arguments and enforces no relationship between them.
    # OME-647: the SOURCE revision is folded in as its own input, not left implicit
    # in the evidence digest. Those two answer different questions — the evidence
    # digest moves when an observed VALUE changes, while this moves when the gateway
    # starts reading DIFFERENT documents or reading the same ones differently. A
    # source-pair change that happened to yield byte-identical observations would
    # otherwise serve new-meaning evidence under an unchanged contract id.
    digest_inputs = (
        canonical_id,
        gateway_provider,
        auth_mode,
        scope,
        context_identity,
        source_revision or "",
        evidence_revision,
        projection_revision,
        _section_revision(tools_section),
        _section_revision(transport_section),
        str(SCHEMA_VERSION),
    )

    entries = compose_contract_entries(normalized, observations, auth_mode=auth_mode)
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": _opaque_id(_CONTRACT_ID_PREFIX, "contract", digest_inputs),
        "model": {
            "id": canonical_id,
            "gateway_provider": gateway_provider,
            "upstream_id": upstream_model_id(canonical_id),
        },
        "context": {
            "scope": scope,
            "auth_mode": auth_mode,
            "revision": _opaque_id(_CONTEXT_REVISION_PREFIX, "context", digest_inputs),
            # OME-648: source_revision is published HERE and hashed, unlike
            # ``freshness`` and the route-added ``context.execution_access``.
            # Those two are deliberate identity exclusions (see above); placing
            # source_revision in freshness would falsely suggest it is excluded too.
            # Null when the provider declares no dynamic source; the key is always
            # present, so "read from nothing" needs no key-presence check to detect.
            # Non-secret by construction: a provider-authored label naming its own
            # public documents and the gateway's reading of them, never an input.
            "source_revision": source_revision,
        },
        "freshness": freshness,
        "parameters": {entry.request_path: entry.to_detail_dict() for entry in entries},
        "tools": tools_section,
        "transport": transport_section,
    }
