"""OME-479 contract vocabulary and immutable value objects.

FEATURE: effective model-capability contract — the nouns half. This module owns
the published enums, the disabled-reason vocabulary, the construction-time
errors, and the frozen value objects the contract is composed from. The pure
derivations over them live in ``._algebra``.

INVARIANT: nothing here reads or writes provider state. Every type is frozen and
``extra="forbid"``, so a malformed rule or observation fails closed at
construction rather than surfacing as a wrong contract row later.

AIDEV-NOTE: import these from the ``chat_parameters`` PACKAGE, never from this
module directly — the split between halves is an implementation detail and may
move again. Value VALIDATION lives in ``._schema`` (``ParameterSchema`` and its
vocabulary); the dependency runs one way, this module → ``._schema``.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..auth_types import AuthMode
from ._schema import ParameterSchema

# Public enums (fail-closed: Pydantic rejects any value outside these literals).
ProviderSupport = Literal["supported", "conditional", "unsupported", "unknown"]
GatewayStatus = Literal["enabled", "disabled"]
CacheBehavior = Literal["keyed", "bypass", "transport_only"]
ProjectionKind = Literal["direct", "provider_native"]

# request paths are dotted identifier segments: "temperature", "provider_params.top_k".
_REQUEST_PATH_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")
_WRAPPER_PREFIX = "provider_params."
# INVARIANT: explicit provider targets cannot overwrite protocol or gateway
# transport surfaces. Direct rules such as ``stream`` remain valid because those
# fields are authorized structurally by the projection pipeline.
GATEWAY_OWNED_FIELDS: frozenset[str] = frozenset(
    {"model", "messages", "stream", "extra_headers", "metadata", "timeout"}
)
_DISABLED_UNPROJECTED_REASON = "projection_not_implemented"
# Sibling of the above, for the TRANSPORT section: the provider may well support
# the control upstream, but this gateway does not carry it yet.
_DISABLED_TRANSPORT_REASON = "gateway_transport_not_implemented"
# WHY a THIRD reason rather than reusing the first: "the gateway has no projection
# for this path" and "the gateway has a reviewed projection this CREDENTIAL cannot
# use" are different facts with different remedies — the first waits on gateway
# work, the second is fixed by connecting the other auth mode. Collapsing them
# tells a client to wait for something that already exists.
_DISABLED_AUTH_MODE_REASON = "projection_not_available_for_auth_mode"
# The transport control's name is the REQUEST FIELD callers actually send, so a
# client can act on what it reads. ``stream`` is gateway-owned (see
# ``GATEWAY_OWNED_FIELDS``), hence never expressible as a parameter rule — the
# transport section is its only possible home.
STREAM_TRANSPORT_NAME = "stream"


class ParameterRuleError(ValueError):
    """Base class for parameter-rule construction/derivation failures."""


class InvalidParameterRuleError(ParameterRuleError):
    """A single rule is internally inconsistent (fail closed at construction)."""


class DuplicateParameterRuleError(ParameterRuleError):
    """Two rules claim the same request path within one provider rule set."""


class ParameterProjectionRule(BaseModel):
    """Synchronous, provider-owned dispatch policy for one request path.

    A rule is the ONLY thing that enables a parameter. Dynamic discovery never
    creates or enables one.
    """

    # WHY: the wire/constructor key stays "schema" (locked contract + client
    # API) via alias, while the python attribute is renamed so it no longer
    # shadows pydantic BaseModel.schema(). Callers pass schema=...; code reads
    # instance.parameter_schema.
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_path: str
    parameter_schema: ParameterSchema | None = Field(default=None, alias="schema")
    applicable_auth_modes: tuple[AuthMode, ...]
    projection_kind: ProjectionKind
    provider_target: str | None = None
    cache_behavior: CacheBehavior
    output_affecting: bool = True
    projection_revision: str

    @field_validator("request_path")
    @classmethod
    def _valid_request_path(cls, value: str) -> str:
        if not _REQUEST_PATH_RE.match(value):
            raise InvalidParameterRuleError(f"invalid request_path: {value!r}")
        return value

    @field_validator("applicable_auth_modes")
    @classmethod
    def _normalize_auth_modes(cls, value: tuple[AuthMode, ...]) -> tuple[AuthMode, ...]:
        if not value:
            raise InvalidParameterRuleError("applicable_auth_modes must be non-empty")
        # Deterministic: sorted + deduplicated so equal rules hash/compare equal.
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def _check_consistency(self) -> ParameterProjectionRule:
        # INVARIANT: transport_only is reserved for separately reviewed transport
        # controls; an ordinary output-affecting field can never claim it.
        if self.output_affecting and self.cache_behavior == "transport_only":
            raise InvalidParameterRuleError("output-affecting rule cannot be transport_only")
        if (
            self.provider_target is not None
            and self.provider_target.split(".", 1)[0] in GATEWAY_OWNED_FIELDS
        ):
            raise InvalidParameterRuleError("parameter rule cannot target a gateway-owned field")
        if self.projection_kind == "provider_native":
            if not self.request_path.startswith(_WRAPPER_PREFIX):
                raise InvalidParameterRuleError(
                    "provider_native rule must use a provider_params.* request_path"
                )
            if not self.provider_target:
                raise InvalidParameterRuleError("provider_native rule requires a provider_target")
        return self

    @property
    def target(self) -> str:
        """Where the validated value lands in the provider body."""
        return self.provider_target or self.request_path


class ProviderParameterObservation(BaseModel):
    """Raw provider evidence for one request path. Never authorizes dispatch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_path: str
    support: ProviderSupport
    source: str
    stale: bool = False
    parameter_schema: ParameterSchema | None = Field(default=None, alias="schema")
    # Lifecycle, TRI-STATE on purpose (OME-647): True/False are verdicts a source
    # actually made, ``None`` means the source does not model lifecycle at all.
    # WHY not a plain ``bool``: a per-model catalog that lists supported parameter
    # NAMES has said nothing about deprecation, and defaulting it to False would
    # publish "the provider affirms this field is current" on evidence that does
    # not exist. An OpenAPI document, by contrast, does speak: a property it
    # carries without a ``deprecated`` flag is declared current, so that source
    # legitimately emits False.
    deprecated: bool | None = None


class ProviderToolObservation(BaseModel):
    """Raw provider evidence for one ``tools[].type``. Never authorizes dispatch.

    # WHY no ``source``/``stale`` twin of ``ProviderParameterObservation``: the
    # tools section publishes only ``provider_support`` + ``gateway_status``
    # (``ToolCapability.to_dict``), and a provider that reports a tool verdict also
    # projects it onto the ``tools``/``tool_choice`` request paths — which DO carry
    # provenance. Duplicating it here would be state the document never renders.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_type: str
    support: ProviderSupport


class ProviderDiscoverySnapshot(BaseModel):
    """A provider's discovered evidence, endpoint- and model-scoped kept separate.

    # INVARIANT (§5.1): endpoint evidence (what the API accepts syntactically) and
    # per-model evidence (what one model supports) are held in SEPARATE fields, so
    # they can never be conflated into a single support verdict for a path. Tool
    # evidence is a third, distinct field for the same reason — it feeds a different
    # published section and must not be merged into a request-path verdict.
    # INVARIANT: discovery NEVER enables a parameter — a rule does. This snapshot is
    # evidence a caller overlays onto rules; on its own it authorizes nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_revision: str
    endpoint_observations: tuple[ProviderParameterObservation, ...] = ()
    model_observations: tuple[ProviderParameterObservation, ...] = ()
    tool_observations: tuple[ProviderToolObservation, ...] = ()


class ToolCapability(BaseModel):
    """Accepted ``tools[].type`` discriminator value + its gateway status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_type: str
    provider_support: ProviderSupport
    gateway_status: GatewayStatus

    def to_dict(self) -> dict[str, Any]:
        # Detailed contract reports every tool with its status (the summary
        # reports only enabled types — see ``supported_tool_types``).
        return {"provider_support": self.provider_support, "gateway_status": self.gateway_status}


class TransportCapability(BaseModel):
    """A transport control (e.g. ``stream``) reported separately from params."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    provider_support: ProviderSupport
    gateway_status: GatewayStatus
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "provider_support": self.provider_support,
            "gateway_status": self.gateway_status,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        return out


def stream_transport_capability(*, gateway_enabled: bool) -> TransportCapability:
    """The ``stream`` transport control, derived from the gateway's own policy.

    FEATURE: discoverable transport contract. ``/v1/chat/completions`` rejects
    ``stream: true`` for a provider that cannot stream through this gateway;
    publishing that decision here is what lets a client read the policy instead of
    discovering it from a 400.

    INVARIANT: ``gateway_status`` carries POLICY, ``provider_support`` carries
    EVIDENCE, and the two are not the same claim. The gateway knows its own
    streaming decision; it has observed nothing about the upstream, so support
    stays ``unknown``. A plugin holding real evidence overrides the hook rather
    than having this factory invent it.

    AIDEV-NOTE: this reports an ALREADY-ENFORCED behaviour and enables nothing —
    which is why it needs no provider-transform proof. Keep it that way: if a
    control is ever published here BEFORE the dispatch path honours it, the
    contract starts lying.
    """
    return TransportCapability(
        name=STREAM_TRANSPORT_NAME,
        provider_support="unknown",
        gateway_status="enabled" if gateway_enabled else "disabled",
        reason=None if gateway_enabled else _DISABLED_TRANSPORT_REASON,
    )


class ParameterContractEntry(BaseModel):
    """One composed row of the detailed contract (observation + gateway rule)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_path: str
    parameter_schema: ParameterSchema | None = Field(alias="schema")
    provider_support: ProviderSupport
    provider_source: str
    provider_stale: bool
    # Published as ``provider.deprecated``; ``None`` when no source spoke. Defaulted
    # so a provider that models no lifecycle constructs entries unchanged.
    provider_deprecated: bool | None = None
    gateway_status: GatewayStatus
    gateway_projection: str | None
    gateway_reason: str | None
    cache_behavior: CacheBehavior
    applicable_auth_modes: tuple[AuthMode, ...]

    def to_detail_dict(self) -> dict[str, Any]:
        gateway: dict[str, Any] = {"status": self.gateway_status}
        if self.gateway_status == "enabled":
            gateway["projection"] = self.gateway_projection
        else:
            gateway["reason"] = self.gateway_reason
        gateway["cache_behavior"] = self.cache_behavior
        # WHY published rather than kept internal: without it a DISABLED row cannot
        # say WHICH credential would enable it, so "not available under this auth
        # mode" is a dead end for the client. Empty tuple == no gateway rule at all.
        # No new exposure: ``context.auth_mode`` already names the reading mode in
        # this same profile-bound document, and these are gateway-authored policy
        # values, never account or credential material.
        gateway["applicable_auth_modes"] = list(self.applicable_auth_modes)
        return {
            "request_path": self.request_path,
            "schema": (
                self.parameter_schema.to_json_schema()
                if self.parameter_schema is not None
                else None
            ),
            "provider": {
                "support": self.provider_support,
                "source": self.provider_source,
                "stale": self.provider_stale,
                # WHY always present, and null when unknown: a client reading a
                # UNIFORM shape can tell "the provider declares this deprecated"
                # from "nobody said" without a key-presence check. Omitting the key
                # for the silent case makes those two indistinguishable in JSON.
                "deprecated": self.provider_deprecated,
            },
            "gateway": gateway,
        }
