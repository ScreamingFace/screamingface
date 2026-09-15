"""Read-only Engine discovery values."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from screamingface._benchmark_identity import benchmark_id as _benchmark_id


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Lightweight capabilities for one Model route addressable through the Engine."""

    id: str
    provider: str
    supported_parameters: tuple[str, ...] = ()
    supported_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _nonblank(self.id, "Model id"))
        object.__setattr__(self, "provider", _nonblank(self.provider, "Model provider"))
        object.__setattr__(
            self,
            "supported_parameters",
            _names(self.supported_parameters, "Model supported_parameters"),
        )
        object.__setattr__(
            self,
            "supported_tools",
            _names(self.supported_tools, "Model supported_tools"),
        )

    def __repr__(self) -> str:
        return (
            f"ModelInfo({self.id!r}, provider={self.provider!r}, "
            f"parameters={len(self.supported_parameters)}, "
            f"tools={len(self.supported_tools)})"
        )


_SCHEMA_TYPES = frozenset({"number", "integer", "string", "boolean", "array", "object"})
_ITEM_TYPES = _SCHEMA_TYPES - {"array"}
_PROVIDER_SUPPORT = frozenset({"supported", "conditional", "unsupported", "unknown"})
_CACHE_BEHAVIORS = frozenset({"keyed", "bypass", "transport_only"})
_PROJECTIONS = frozenset({"direct", "provider_native"})
_AUTH_MODES = frozenset({"api_key", "oauth", "none"})
_TYPE_CHECKS: Mapping[str, Callable[[object], bool]] = MappingProxyType(
    {
        "number": lambda value: isinstance(value, int | float) and not isinstance(value, bool),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "string": lambda value: isinstance(value, str),
        "boolean": lambda value: isinstance(value, bool),
        "array": lambda value: isinstance(value, list),
        "object": lambda value: isinstance(value, dict),
    }
)


@dataclass(frozen=True, slots=True)
class ModelParameterSchema:
    """The bounded value schema AI Gateway applies to one request parameter."""

    type: str | tuple[str, ...]
    minimum: float | None = None
    maximum: float | None = None
    enum: tuple[str, ...] | None = None
    items: str | None = None
    pattern: str | None = None
    max_length: int | None = None

    def __post_init__(self) -> None:
        options = _schema_options(self.type)
        _validate_schema_bounds(self.minimum, self.maximum)
        _validate_schema_items(self.items)
        if self.enum is not None:
            object.__setattr__(self, "enum", _names(self.enum, "Model parameter schema enum"))
        _validate_schema_text(options, self.pattern, self.max_length)
        object.__setattr__(self, "type", options[0] if len(options) == 1 else options)

    def validate(self, value: object) -> None:
        """Raise ``ValueError`` when a value violates this published schema."""

        options = (self.type,) if isinstance(self.type, str) else self.type
        _validate_value_type(value, options)
        _validate_value_number(value, self.minimum, self.maximum)
        _validate_value_string(value, self.pattern, self.max_length)
        _validate_value_enum(value, self.enum)
        _validate_value_items(value, self.items)


@dataclass(frozen=True, slots=True)
class ModelParameter:
    """One profile-specific model parameter, with provider evidence and gateway policy."""

    name: str
    request_path: str
    schema: ModelParameterSchema | None
    provider_support: str
    provider_source: str
    provider_stale: bool
    provider_deprecated: bool | None
    gateway_status: str
    gateway_projection: str | None
    gateway_reason: str | None
    cache_behavior: str
    applicable_auth_modes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("name", "request_path", "provider_support", "provider_source"):
            object.__setattr__(self, name, _nonblank(getattr(self, name), name))
        if self.provider_support not in _PROVIDER_SUPPORT:
            raise ValueError("Model parameter provider_support is invalid")
        if self.gateway_status not in {"enabled", "disabled"}:
            raise ValueError("Model parameter gateway_status must be enabled or disabled")
        if self.gateway_status == "enabled" and self.schema is None:
            raise ValueError("enabled Model parameter must publish a schema")
        _validate_gateway_policy(
            self.gateway_status,
            self.gateway_projection,
            self.gateway_reason,
        )
        if self.cache_behavior not in _CACHE_BEHAVIORS:
            raise ValueError("Model parameter cache_behavior is invalid")
        object.__setattr__(
            self,
            "applicable_auth_modes",
            _names(self.applicable_auth_modes, "Model parameter applicable_auth_modes"),
        )
        if any(mode not in _AUTH_MODES for mode in self.applicable_auth_modes):
            raise ValueError("Model parameter applicable_auth_modes is invalid")

    @property
    def enabled(self) -> bool:
        return self.gateway_status == "enabled"


@dataclass(frozen=True, slots=True)
class ModelCapability:
    """One tool or transport capability in a profile-specific Model contract."""

    provider_support: str
    gateway_status: str
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_support",
            _nonblank(self.provider_support, "Model capability provider_support"),
        )
        if self.provider_support not in _PROVIDER_SUPPORT:
            raise ValueError("Model capability provider_support is invalid")
        if self.gateway_status not in {"enabled", "disabled"}:
            raise ValueError("Model capability gateway_status must be enabled or disabled")


@dataclass(frozen=True, slots=True)
class ModelDetails:
    """Profile-specific parameters and capabilities for one canonical Model id."""

    id: str
    provider: str
    upstream_id: str
    contract_id: str
    scope: str
    auth_mode: str
    context_revision: str
    source_revision: str | None
    parameters: Mapping[str, ModelParameter]
    tools: Mapping[str, ModelCapability]
    transport: Mapping[str, ModelCapability]
    observed_at: datetime | None
    expires_at: datetime | None
    stale: bool
    degraded: bool
    execution_access: Literal["configured", "missing"] | None = None

    def __post_init__(self) -> None:
        for name in (
            "id",
            "provider",
            "upstream_id",
            "contract_id",
            "scope",
            "auth_mode",
            "context_revision",
        ):
            object.__setattr__(self, name, _nonblank(getattr(self, name), f"Model {name}"))
        if self.source_revision is not None:
            object.__setattr__(
                self,
                "source_revision",
                _nonblank(self.source_revision, "Model source_revision"),
            )
        if self.auth_mode not in _AUTH_MODES:
            raise ValueError("Model auth_mode is invalid")
        if self.execution_access not in (None, "configured", "missing"):
            raise ValueError("Model execution_access must be configured, missing, or None")
        _validate_freshness(self.observed_at, self.expires_at, self.stale, self.degraded)
        for name in ("parameters", "tools", "transport"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TypeError(f"Model {name} must be a mapping")
            object.__setattr__(self, name, MappingProxyType(dict(value)))

    def __repr__(self) -> str:
        arguments = [
            repr(self.id),
            f"provider={self.provider!r}",
            f"scope={self.scope!r}",
            f"parameters={len(self.parameters)}",
            f"tools={len(self.tools)}",
            f"transport={len(self.transport)}",
        ]
        # INVARIANT: _validate_freshness makes stale/degraded mutually exclusive, so at most
        # one flag is ever appended; a fresh profile shows neither.
        if self.stale:
            arguments.append("stale=True")
        if self.degraded:
            arguments.append("degraded=True")
        return f"ModelDetails({', '.join(arguments)})"

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import model_details_card_html

        return model_details_card_html(self)


@dataclass(frozen=True, slots=True)
class BenchmarkInfo:
    """The stable identity, revision, and size of one Engine-owned Benchmark."""

    id: str
    revision: str
    case_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _benchmark_id(self.id))
        object.__setattr__(
            self,
            "revision",
            _nonblank(self.revision, "Benchmark revision"),
        )
        if (
            isinstance(self.case_count, bool)
            or not isinstance(self.case_count, int)
            or self.case_count < 1
        ):
            raise ValueError("Benchmark case_count must be a positive integer")

    def _result_dict(self, case_count: int) -> dict[str, object]:
        """Return the pinned subset embedded in a Report."""

        if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 1:
            raise ValueError("Report case_count must be a positive integer")
        if case_count > self.case_count:
            raise ValueError("Report case_count cannot exceed its Benchmark case_count")
        return {
            "id": self.id,
            "revision": self.revision,
            "case_count": case_count,
        }


@dataclass(frozen=True, slots=True)
class Benchmark:
    """Discoverable identity and provenance for one Engine-owned Benchmark."""

    id: str
    title: str
    description: str
    revision: str
    case_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _benchmark_id(self.id))
        for name in ("title", "description", "revision"):
            object.__setattr__(self, name, _nonblank(getattr(self, name), f"Benchmark {name}"))
        if (
            isinstance(self.case_count, bool)
            or not isinstance(self.case_count, int)
            or self.case_count < 1
        ):
            raise ValueError("Benchmark case_count must be a positive integer")

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import benchmark_card_html

        return benchmark_card_html(self)


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _names(values: object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, tuple | list):
        raise TypeError(f"{label} must be a sequence of strings")
    selected = tuple(_nonblank(value, label) for value in values)
    if len(set(selected)) != len(selected):
        raise ValueError(f"{label} must not contain duplicates")
    return selected


def _schema_options(value: str | tuple[str, ...]) -> tuple[str, ...]:
    options = (value,) if isinstance(value, str) else tuple(value)
    if not options or any(option not in _SCHEMA_TYPES for option in options):
        raise ValueError("Model parameter schema type is invalid")
    if len(set(options)) != len(options):
        raise ValueError("Model parameter schema type contains duplicates")
    return options


def _validate_schema_bounds(minimum: float | None, maximum: float | None) -> None:
    for name, value in (("minimum", minimum), ("maximum", maximum)):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise ValueError(f"Model parameter schema {name} must be finite")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Model parameter schema minimum cannot exceed maximum")


def _validate_schema_items(items: str | None) -> None:
    if items is not None and items not in _ITEM_TYPES:
        raise ValueError("Model parameter schema items type is invalid")


def _validate_schema_text(
    options: tuple[str, ...],
    pattern: str | None,
    max_length: int | None,
) -> None:
    if (pattern is not None or max_length is not None) and "string" not in options:
        raise ValueError("Model parameter schema text constraints require a string type")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise ValueError("Model parameter schema pattern must be a string")
        if not (pattern.startswith("^") and pattern.endswith("$")):
            raise ValueError("Model parameter schema pattern must be anchored with ^ and $")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError("Model parameter schema pattern is invalid") from exc
    if max_length is not None and (
        isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1
    ):
        raise ValueError("Model parameter schema max_length must be positive")


def _validate_gateway_policy(
    status: str,
    projection: str | None,
    reason: str | None,
) -> None:
    if status == "enabled":
        if projection not in _PROJECTIONS or reason is not None:
            raise ValueError("enabled Model parameter gateway policy is invalid")
        return
    if projection is not None or not isinstance(reason, str) or not reason.strip():
        raise ValueError("disabled Model parameter gateway policy is invalid")


def _validate_freshness(
    observed_at: datetime | None,
    expires_at: datetime | None,
    stale: bool,
    degraded: bool,
) -> None:
    if not isinstance(stale, bool) or not isinstance(degraded, bool):
        raise TypeError("Model freshness flags must be booleans")
    if (observed_at is None) != (expires_at is None):
        raise ValueError("Model freshness timestamps must both be present or both be null")
    for name, value in (("observed_at", observed_at), ("expires_at", expires_at)):
        if value is not None and (
            not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError(f"Model freshness {name} must be timezone-aware")
    if observed_at is not None and expires_at is not None and expires_at <= observed_at:
        raise ValueError("Model freshness expires_at must follow observed_at")
    if degraded and (stale or observed_at is not None):
        raise ValueError("degraded Model freshness cannot be stale or carry timestamps")
    if stale and observed_at is None:
        raise ValueError("stale Model freshness must carry an observation window")


def _validate_value_type(value: object, options: tuple[str, ...]) -> None:
    if not any(_TYPE_CHECKS[option](value) for option in options):
        raise ValueError(f"expected {' or '.join(options)}")


def _validate_value_number(
    value: object,
    minimum: float | None,
    maximum: float | None,
) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("must be finite")
    if not isinstance(value, int | float) or isinstance(value, bool):
        return
    if minimum is not None and value < minimum:
        raise ValueError(f"must be >= {minimum:g}")
    if maximum is not None and value > maximum:
        raise ValueError(f"must be <= {maximum:g}")


def _validate_value_string(value: object, pattern: str | None, max_length: int | None) -> None:
    if not isinstance(value, str):
        return
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"must be at most {max_length} characters")
    if pattern is not None and re.fullmatch(pattern, value) is None:
        raise ValueError("does not match the required pattern")


def _validate_value_enum(value: object, enum: tuple[str, ...] | None) -> None:
    if enum is not None and value not in enum:
        raise ValueError(f"must be one of {', '.join(repr(item) for item in enum)}")


def _validate_value_items(value: object, items: str | None) -> None:
    if not isinstance(value, list) or items is None:
        return
    if any(not _TYPE_CHECKS[items](item) for item in value):
        raise ValueError(f"array items must be {items}")
    if items == "number" and any(
        isinstance(item, float) and not math.isfinite(item) for item in value
    ):
        raise ValueError("array items must be finite")


__all__ = [
    "Benchmark",
    "BenchmarkInfo",
    "ModelCapability",
    "ModelDetails",
    "ModelInfo",
    "ModelParameter",
    "ModelParameterSchema",
]
