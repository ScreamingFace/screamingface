"""Provider-neutral value objects for the OME-303 accounting wire contract."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Self

from .money import MAX_AMOUNT_FRACTIONAL_DIGITS, MAX_AMOUNT_INTEGER_DIGITS

__all__ = [
    "SCHEMA_PROVIDER_ATTEMPT",
    "SCHEMA_REQUEST_ECONOMICS",
    "SCHEMA_USAGE_ACCOUNTING",
    "TRANSPORT_LITELLM_ASYNC_HTTP",
    "AccountingCapability",
    "CacheReference",
    "CacheWriteTTL",
    "CallOutcome",
    "CaptureStatus",
    "DirectCost",
    "DirectCostStatus",
    "InputTokenUsage",
    "OutputTokenUsage",
    "PricingContext",
    "ProviderAttemptRecord",
    "ProviderExtension",
    "ProviderExtensionFact",
    "ProviderUsageAccountingEvidence",
    "TokenUsage",
    "UsageAccountingStrategy",
    "UsageEvidenceStatus",
    "UsageSource",
]

SCHEMA_USAGE_ACCOUNTING = "aigw.chat_usage_accounting"
SCHEMA_REQUEST_ECONOMICS = "aigw.request_economics"
SCHEMA_PROVIDER_ATTEMPT = "aigw.provider_attempt"

TRANSPORT_LITELLM_ASYNC_HTTP: Literal["litellm_async_http"] = "litellm_async_http"

AccountingCapability = Literal[
    "unsupported",
    "litellm_async_http",
    "provider_owned_http",
    "provider_owned_process",
]
CaptureStatus = Literal["complete", "partial", "accounting_not_supported", "not_applicable"]
CallOutcome = Literal[
    "succeeded", "provider_error", "transport_error", "conversion_error", "indeterminate"
]
UsageSource = Literal[
    "provider_raw_response",
    "provider_converted_response",
    "cached_converted_response",
]
UsageEvidenceStatus = Literal["complete", "partial", "unavailable"]
DirectCostStatus = Literal[
    "reported", "absent", "unavailable", "invalid", "unit_unknown", "archive_matched"
]
ExtensionFactKind = Literal["integer", "decimal", "boolean", "enum"]
ServiceTier = Literal["standard", "priority", "batch"]

MAX_TOKEN_COUNT = 2**53 - 1
MAX_TTL_ROWS = 8
MAX_EXTENSION_FACTS = 8
MAX_EXTENSION_TEXT_BYTES = 128

_CANONICAL_DECIMAL = re.compile(
    rf"^(?:0|[1-9][0-9]{{0,{MAX_AMOUNT_INTEGER_DIGITS - 1}}})"
    rf"(?:\.[0-9]{{1,{MAX_AMOUNT_FRACTIONAL_DIGITS}}})?$"
)


def _validate_count(value: int | None, *, field_name: str) -> None:
    if value is None:
        return
    if type(value) is not int or not 0 <= value <= MAX_TOKEN_COUNT:
        raise ValueError(f"{field_name} must be an integer in 0..{MAX_TOKEN_COUNT}")


def _validate_ascii(value: str | None, *, field_name: str, max_bytes: int) -> None:
    if value is None:
        return
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a string")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be ASCII") from exc
    if not encoded or len(encoded) > max_bytes:
        raise ValueError(f"{field_name} must contain 1..{max_bytes} ASCII bytes")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ValueError(f"{field_name} must contain printable ASCII only")


def _is_canonical_decimal(value: str) -> bool:
    return (
        type(value) is str
        and bool(_CANONICAL_DECIMAL.fullmatch(value))
        and not ("." in value and value.endswith("0"))
    )


@dataclass(frozen=True, slots=True)
class CacheWriteTTL:
    """A pricing-relevant subset of provider-side cache-write tokens."""

    ttl_seconds: int
    tokens: int

    def __post_init__(self) -> None:
        _validate_count(self.ttl_seconds, field_name="ttl_seconds")
        _validate_count(self.tokens, field_name="tokens")

    def as_json(self) -> dict[str, int]:
        return {"ttl_seconds": self.ttl_seconds, "tokens": self.tokens}


@dataclass(frozen=True, slots=True)
class InputTokenUsage:
    """Inclusive input total plus non-additive pricing subsets."""

    total: int | None = None
    uncached: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    cache_write_by_ttl: tuple[CacheWriteTTL, ...] = ()

    def __post_init__(self) -> None:
        for name in ("total", "uncached", "cache_read", "cache_write"):
            _validate_count(getattr(self, name), field_name=name)
        if type(self.cache_write_by_ttl) is not tuple or any(
            type(row) is not CacheWriteTTL for row in self.cache_write_by_ttl
        ):
            raise ValueError("cache_write_by_ttl must contain CacheWriteTTL rows")
        if len(self.cache_write_by_ttl) > MAX_TTL_ROWS:
            raise ValueError(f"cache_write_by_ttl may contain at most {MAX_TTL_ROWS} rows")

    def as_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "uncached": self.uncached,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "cache_write_by_ttl": [row.as_json() for row in self.cache_write_by_ttl],
        }


@dataclass(frozen=True, slots=True)
class OutputTokenUsage:
    """Inclusive output total plus its non-additive reasoning subset."""

    total: int | None = None
    reasoning: int | None = None

    def __post_init__(self) -> None:
        _validate_count(self.total, field_name="total")
        _validate_count(self.reasoning, field_name="reasoning")

    def as_json(self) -> dict[str, int | None]:
        return {"total": self.total, "reasoning": self.reasoning}


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Canonical token evidence with explicit inclusive/subset semantics."""

    status: UsageEvidenceStatus = "unavailable"
    source: UsageSource = "provider_raw_response"
    input: InputTokenUsage = field(default_factory=InputTokenUsage)
    output: OutputTokenUsage = field(default_factory=OutputTokenUsage)

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {
            "complete",
            "partial",
            "unavailable",
        }:
            raise ValueError("usage status must use the canonical vocabulary")
        if type(self.source) is not str or self.source not in {
            "provider_raw_response",
            "provider_converted_response",
            "cached_converted_response",
        }:
            raise ValueError("usage source must use the canonical vocabulary")
        if type(self.input) is not InputTokenUsage or type(self.output) is not OutputTokenUsage:
            raise ValueError("usage input/output must use canonical value objects")
        contradictory = self.status == "complete" and (
            self.input.total is None or self.output.total is None
        )
        if self.input.total is not None:
            subsets = (
                self.input.uncached,
                self.input.cache_read,
                self.input.cache_write,
            )
            contradictory |= any(
                value is not None and value > self.input.total for value in subsets
            )
            known_subsets = [value for value in subsets if value is not None]
            contradictory |= sum(known_subsets) > self.input.total
            contradictory |= len(known_subsets) == 3 and sum(known_subsets) != self.input.total
        contradictory |= bool(
            self.output.total is not None
            and self.output.reasoning is not None
            and self.output.reasoning > self.output.total
        )
        ttl_rows = self.input.cache_write_by_ttl
        contradictory |= bool(
            ttl_rows
            and (
                self.input.cache_write is None
                or sum(row.tokens for row in ttl_rows) != self.input.cache_write
            )
        )
        if contradictory:
            object.__setattr__(self, "status", "partial")

    @classmethod
    def unavailable(cls) -> Self:
        return cls(status="unavailable")

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "input": self.input.as_json(),
            "output": self.output.as_json(),
        }


@dataclass(frozen=True, slots=True)
class PricingContext:
    """Provider-neutral dimensions an Engine rate selection may require."""

    service_tier: ServiceTier | None = None
    backend: str | None = None

    def __post_init__(self) -> None:
        if self.service_tier is not None and type(self.service_tier) is not str:
            raise ValueError("service_tier must be a string")
        if self.service_tier not in {None, "standard", "priority", "batch"}:
            raise ValueError("service_tier must use the canonical vocabulary")
        _validate_ascii(self.service_tier, field_name="service_tier", max_bytes=64)
        _validate_ascii(self.backend, field_name="backend", max_bytes=64)

    def as_json(self) -> dict[str, str | None]:
        return {"service_tier": self.service_tier, "backend": self.backend}


@dataclass(frozen=True, slots=True)
class DirectCost:
    """Provider-authored direct-cost evidence and its independent status."""

    status: DirectCostStatus
    amount: str | None = None
    unit: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {
            "reported",
            "absent",
            "unavailable",
            "invalid",
            "unit_unknown",
            "archive_matched",
        }:
            raise ValueError("direct cost status must use the canonical vocabulary")
        if self.amount is not None and not _is_canonical_decimal(self.amount):
            raise ValueError("amount must be a bounded nonnegative canonical decimal")
        _validate_ascii(self.unit, field_name="unit", max_bytes=64)
        _validate_ascii(self.source, field_name="source", max_bytes=MAX_EXTENSION_TEXT_BYTES)
        # INVARIANT (ERD §3.2, M2): ``archive_matched`` carries the SAME requirement as
        # ``reported`` — amount, unit and source are all mandatory. The status exists so a
        # real-but-not-this-row's value is never mistaken for provider-authored money.
        if self.status in {"reported", "archive_matched"} and None in (
            self.amount,
            self.unit,
            self.source,
        ):
            raise ValueError(f"{self.status} direct cost requires amount, unit and source")
        if self.status == "unit_unknown" and None in (self.amount, self.source):
            raise ValueError("unit_unknown direct cost requires amount and source")
        if self.status == "unit_unknown" and self.unit is not None:
            raise ValueError("unit_unknown direct cost cannot carry a unit")
        if self.status in {"absent", "unavailable", "invalid"} and any(
            value is not None for value in (self.amount, self.unit, self.source)
        ):
            raise ValueError(f"{self.status} direct cost cannot carry amount metadata")

    @classmethod
    def reported(cls, *, amount: str, unit: str, source: str) -> Self:
        return cls(status="reported", amount=amount, unit=unit, source=source)

    @classmethod
    def absent(cls) -> Self:
        return cls(status="absent")

    @classmethod
    def unavailable(cls) -> Self:
        return cls(status="unavailable")

    @classmethod
    def invalid(cls) -> Self:
        return cls(status="invalid")

    @classmethod
    def unit_unknown(cls, *, amount: str, source: str) -> Self:
        return cls(status="unit_unknown", amount=amount, source=source)

    @classmethod
    def archive_matched(cls, *, amount: str, unit: str, source: str) -> Self:
        """A real measured value paired to a logged archive call, not provider-authored.

        INVARIANT (ERD §3.2, PRD S7/M8): never summed with ``reported`` money. The distinct
        status is the only thing preventing that, so it is never rendered as ``reported``.
        """
        return cls(status="archive_matched", amount=amount, unit=unit, source=source)

    def as_json(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "amount": self.amount,
            "unit": self.unit,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ProviderExtensionFact:
    """One allowlisted bounded scalar fact used only for audit/debugging."""

    name: str
    kind: ExtensionFactKind
    value: int | str | bool
    unit: str | None
    source: str

    def __post_init__(self) -> None:
        if type(self.kind) is not str:
            raise ValueError("extension fact kind is not supported by accounting")
        _validate_ascii(self.name, field_name="name", max_bytes=64)
        _validate_ascii(self.unit, field_name="unit", max_bytes=64)
        _validate_ascii(self.source, field_name="source", max_bytes=MAX_EXTENSION_TEXT_BYTES)
        if self.kind == "integer":
            if type(self.value) is not int:
                raise ValueError("integer extension facts require integer values")
            _validate_count(self.value, field_name="value")
        elif self.kind == "boolean":
            if type(self.value) is not bool:
                raise ValueError("boolean extension facts require bool values")
        elif self.kind == "decimal":
            if type(self.value) is not str or not _is_canonical_decimal(self.value):
                raise ValueError("decimal extension facts require canonical decimal strings")
        elif self.kind == "enum":
            if type(self.value) is not str:
                raise ValueError("enum extension facts require plugin-declared strings")
            _validate_ascii(self.value, field_name="value", max_bytes=64)
        else:
            raise ValueError("extension fact kind is not supported by accounting")

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ProviderExtension:
    """Audit-only namespace. Engine never needs it for canonical rollup."""

    namespace: str
    facts: tuple[ProviderExtensionFact, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        _validate_ascii(self.namespace, field_name="namespace", max_bytes=64)
        if type(self.facts) is not tuple or any(
            type(fact) is not ProviderExtensionFact for fact in self.facts
        ):
            raise ValueError("provider extension facts must use canonical value objects")
        if len(self.facts) > MAX_EXTENSION_FACTS:
            raise ValueError(f"provider extension may contain at most {MAX_EXTENSION_FACTS} facts")
        if type(self.truncated) is not bool:
            raise ValueError("provider extension truncated must be a boolean")

    def as_json(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "facts": [fact.as_json() for fact in self.facts],
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class UsageAccountingStrategy:
    """Declared observation strategy; support never follows from mapper presence alone."""

    capability: AccountingCapability = "unsupported"

    def __post_init__(self) -> None:
        if type(self.capability) is not str or self.capability not in {
            "unsupported",
            "litellm_async_http",
            "provider_owned_http",
            "provider_owned_process",
        }:
            raise ValueError("accounting capability must use the canonical vocabulary")

    @classmethod
    def unsupported(cls) -> Self:
        return cls(capability="unsupported")

    @classmethod
    def litellm_async_http(cls) -> Self:
        return cls(capability=TRANSPORT_LITELLM_ASYNC_HTTP)

    @property
    def uses_shared_litellm_http(self) -> bool:
        return self.capability == TRANSPORT_LITELLM_ASYNC_HTTP

    @property
    def is_supported(self) -> bool:
        return self.capability != "unsupported"


@dataclass(frozen=True, slots=True)
class ProviderUsageAccountingEvidence:
    """Pure mapper output for one observed provider attempt."""

    supported: bool = False
    usage: TokenUsage = field(default_factory=TokenUsage.unavailable)
    pricing_context: PricingContext = field(default_factory=PricingContext)
    direct_cost: DirectCost = field(default_factory=DirectCost.unavailable)
    response_model: str | None = None
    provider_response_id: str | None = None
    provider_extensions: tuple[ProviderExtension, ...] = ()

    def __post_init__(self) -> None:
        if type(self.supported) is not bool:
            raise ValueError("supported must be a boolean")
        if type(self.usage) is not TokenUsage:
            raise ValueError("usage must use the canonical TokenUsage value object")
        if type(self.pricing_context) is not PricingContext:
            raise ValueError("pricing_context must use the canonical PricingContext value object")
        if type(self.direct_cost) is not DirectCost:
            raise ValueError("direct_cost must use the canonical DirectCost value object")
        if type(self.provider_extensions) is not tuple or any(
            type(extension) is not ProviderExtension for extension in self.provider_extensions
        ):
            raise ValueError("provider_extensions must use canonical value objects")
        if len(self.provider_extensions) > 4:
            raise ValueError("an attempt may contain at most 4 extension namespaces")
        if sum(len(extension.facts) for extension in self.provider_extensions) > 8:
            raise ValueError("an attempt may contain at most 8 extension facts")

    @classmethod
    def unsupported(cls) -> Self:
        return cls(supported=False)


@dataclass(frozen=True, slots=True)
class ProviderAttemptRecord:
    """One observed local provider send-pipeline admission."""

    attempt_id: str
    sequence: int
    dispatch_index: int
    attempt_index: int
    provider: str
    transport: str
    outcome: CallOutcome
    requested_model: str | None = None
    response_model: str | None = None
    provider_response_id: str | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    usage: TokenUsage = field(default_factory=TokenUsage.unavailable)
    pricing_context: PricingContext = field(default_factory=PricingContext)
    direct_cost: DirectCost = field(default_factory=DirectCost.unavailable)
    provider_extensions: tuple[ProviderExtension, ...] = ()
    redirect_hop_count: int = 0
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if len(self.provider_extensions) > 4:
            raise ValueError("an attempt may contain at most 4 extension namespaces")
        if sum(len(extension.facts) for extension in self.provider_extensions) > 8:
            raise ValueError("an attempt may contain at most 8 extension facts")

    def as_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_PROVIDER_ATTEMPT,
            "attempt_id": self.attempt_id,
            "sequence": self.sequence,
            "dispatch_index": self.dispatch_index,
            "attempt_index": self.attempt_index,
            "provider": self.provider,
            "requested_model": self.requested_model,
            "response_model": self.response_model,
            "provider_response_id": self.provider_response_id,
            "transport": self.transport,
            "outcome": self.outcome,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "usage": self.usage.as_json(),
            "pricing_context": self.pricing_context.as_json(),
            "direct_cost": self.direct_cost.as_json(),
            "provider_extensions": [extension.as_json() for extension in self.provider_extensions],
            "redirect_hop_count": self.redirect_hop_count,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True, slots=True)
class CacheReference:
    """Historical evidence for the cached final response, never current spend or savings."""

    usage: TokenUsage = field(
        default_factory=lambda: TokenUsage(status="unavailable", source="cached_converted_response")
    )
    direct_cost: DirectCost = field(default_factory=DirectCost.unavailable)
    # ERD §3.5: the stored provider latency. A gateway-side fact no response body holds,
    # so it can only arrive from ``metadata_json``. ``None`` means unknown, and the
    # ``latency`` block is OMITTED from ``as_json`` rather than rendered as a null.
    provider_latency_ms: int | None = None
    kind: Literal["cached_final_response"] = "cached_final_response"
    coverage: Literal["final_successful_response_only"] = "final_successful_response_only"
    incurred_in_current_request: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.usage) is not TokenUsage:
            raise ValueError("cache usage must use the canonical TokenUsage value object")
        if type(self.direct_cost) is not DirectCost:
            raise ValueError("cache direct_cost must use the canonical DirectCost value object")
        if self.provider_latency_ms is not None and (
            type(self.provider_latency_ms) is not int or self.provider_latency_ms < 0
        ):
            raise ValueError("cache provider_latency_ms must be a non-negative int or None")
        if type(self.kind) is not str or self.kind != "cached_final_response":
            raise ValueError("cache reference kind must use the canonical value")
        if type(self.coverage) is not str or self.coverage != "final_successful_response_only":
            raise ValueError("cache reference coverage must use the canonical value")
        if self.incurred_in_current_request is not False:
            raise ValueError("cache reference cannot be current-request spend")

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "coverage": self.coverage,
            "incurred_in_current_request": self.incurred_in_current_request,
            "usage": self.usage.as_json(),
            "direct_cost": self.direct_cost.as_json(),
        }
        if self.provider_latency_ms is not None:
            payload["latency"] = {"provider_latency_ms": self.provider_latency_ms}
        return payload
