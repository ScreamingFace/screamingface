"""Decode the AI Gateway model-parameter contract at the Engine seam."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from screamingface._core.wire import mapping as _wire_mapping
from screamingface._core.wire import text as _wire_text
from screamingface._engine.catalog_contract import _invalid, _string_tuple
from screamingface.discovery import (
    ModelCapability,
    ModelDetails,
    ModelParameter,
    ModelParameterSchema,
)


def _decode_model_details(payload: object, expected_model: str) -> ModelDetails:
    root = _wire_mapping(payload, "Model details", _invalid)
    version = root.get("schema_version")
    if isinstance(version, bool) or version != 1:
        _invalid("Model details schema_version must be 1")
    model = _wire_mapping(root.get("model"), "Model details model", _invalid)
    model_id = _wire_text(model.get("id"), "Model id", _invalid)
    if model_id != expected_model:
        _invalid("Model details has the wrong Model id")
    context = _wire_mapping(root.get("context"), "Model details context", _invalid)
    freshness = _wire_mapping(root.get("freshness"), "Model details freshness", _invalid)
    try:
        return ModelDetails(
            id=model_id,
            provider=_wire_text(model.get("gateway_provider"), "Model provider", _invalid),
            upstream_id=_wire_text(model.get("upstream_id"), "Model upstream_id", _invalid),
            contract_id=_wire_text(root.get("contract_id"), "Model contract_id", _invalid),
            scope=_wire_text(context.get("scope"), "Model context scope", _invalid),
            auth_mode=_wire_text(context.get("auth_mode"), "Model context auth_mode", _invalid),
            execution_access=_execution_access(context),
            context_revision=_wire_text(
                context.get("revision"), "Model context revision", _invalid
            ),
            source_revision=_optional_text(
                context.get("source_revision"), "Model context source_revision"
            ),
            parameters=_decode_model_parameters(root.get("parameters")),
            tools=_decode_capabilities(root.get("tools"), "Model tools"),
            transport=_decode_capabilities(root.get("transport"), "Model transport"),
            observed_at=_optional_timestamp(
                freshness.get("observed_at"), "Model freshness observed_at"
            ),
            expires_at=_optional_timestamp(
                freshness.get("expires_at"), "Model freshness expires_at"
            ),
            stale=_boolean(freshness.get("stale"), "Model freshness stale"),
            degraded=_boolean(freshness.get("degraded"), "Model freshness degraded"),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc))


def _execution_access(context: Mapping[str, object]) -> Literal["configured", "missing"] | None:
    # INVARIANT: omission means an older Gateway, not missing provider access.
    # Explicit malformed values retain the discovery-error path.
    if "execution_access" not in context:
        return None
    value = context["execution_access"]
    if value == "configured":
        return "configured"
    if value == "missing":
        return "missing"
    _invalid("Model execution_access must be configured or missing")


def _decode_model_parameters(value: object) -> dict[str, ModelParameter]:
    rows = _wire_mapping(value, "Model parameters", _invalid)
    parameters: dict[str, ModelParameter] = {}
    for name, raw in rows.items():
        if not isinstance(name, str) or not name.strip():
            _invalid("Model parameter name must be a non-empty string")
        parameters[name] = _decode_model_parameter(name, raw)
    return parameters


def _decode_model_parameter(name: str, value: object) -> ModelParameter:
    item = _wire_mapping(value, f"Model parameter {name!r}", _invalid)
    request_path = _wire_text(
        item.get("request_path"), f"Model parameter {name!r} request_path", _invalid
    )
    if request_path != name:
        _invalid(f"Model parameter {name!r} has a mismatched request_path")
    provider = _wire_mapping(item.get("provider"), f"Model parameter {name!r} provider", _invalid)
    gateway = _wire_mapping(item.get("gateway"), f"Model parameter {name!r} gateway", _invalid)
    try:
        parameter = ModelParameter(
            name=name,
            request_path=request_path,
            schema=_decode_parameter_schema(item.get("schema"), name),
            provider_support=_wire_text(
                provider.get("support"), f"Model parameter {name!r} provider support", _invalid
            ),
            provider_source=_wire_text(
                provider.get("source"), f"Model parameter {name!r} provider source", _invalid
            ),
            provider_stale=_boolean(
                provider.get("stale"), f"Model parameter {name!r} provider stale"
            ),
            provider_deprecated=_optional_boolean(
                provider.get("deprecated"), f"Model parameter {name!r} provider deprecated"
            ),
            gateway_status=_wire_text(
                gateway.get("status"), f"Model parameter {name!r} gateway status", _invalid
            ),
            gateway_projection=_optional_text(
                gateway.get("projection"), f"Model parameter {name!r} gateway projection"
            ),
            gateway_reason=_optional_text(
                gateway.get("reason"), f"Model parameter {name!r} gateway reason"
            ),
            cache_behavior=_wire_text(
                gateway.get("cache_behavior"),
                f"Model parameter {name!r} cache_behavior",
                _invalid,
            ),
            applicable_auth_modes=_string_tuple(
                gateway.get("applicable_auth_modes"),
                f"Model parameter {name!r} applicable_auth_modes",
            ),
        )
        return parameter
    except (TypeError, ValueError) as exc:
        _invalid(f"Model parameter {name!r}: {exc}")


def _decode_parameter_schema(value: object, name: str) -> ModelParameterSchema | None:
    if value is None:
        return None
    schema = _wire_mapping(value, f"Model parameter {name!r} schema", _invalid)
    try:
        return ModelParameterSchema(
            type=_schema_type(schema.get("type"), name),
            minimum=_optional_number(
                schema.get("minimum"), f"Model parameter {name!r} schema minimum"
            ),
            maximum=_optional_number(
                schema.get("maximum"), f"Model parameter {name!r} schema maximum"
            ),
            enum=(
                None
                if schema.get("enum") is None
                else _string_tuple(schema.get("enum"), f"Model parameter {name!r} schema enum")
            ),
            items=_schema_items(schema.get("items"), name),
            pattern=_optional_text(
                schema.get("pattern"), f"Model parameter {name!r} schema pattern"
            ),
            max_length=_optional_positive_int(
                schema.get("maxLength"), f"Model parameter {name!r} schema maxLength"
            ),
        )
    except (TypeError, ValueError) as exc:
        _invalid(f"Model parameter {name!r} schema type or constraint is invalid: {exc}")


def _schema_type(value: object, name: str) -> str | tuple[str, ...]:
    if isinstance(value, str):
        return value
    return _string_tuple(value, f"Model parameter {name!r} schema type")


def _schema_items(value: object, name: str) -> str | None:
    if value is None:
        return None
    item_schema = _wire_mapping(value, f"Model parameter {name!r} schema items", _invalid)
    return _wire_text(
        item_schema.get("type"), f"Model parameter {name!r} schema items type", _invalid
    )


def _decode_capabilities(value: object, label: str) -> dict[str, ModelCapability]:
    rows = _wire_mapping(value, label, _invalid)
    capabilities: dict[str, ModelCapability] = {}
    for name, raw in rows.items():
        if not isinstance(name, str) or not name.strip():
            _invalid(f"{label} name must be a non-empty string")
        item = _wire_mapping(raw, f"{label} {name!r}", _invalid)
        try:
            capabilities[name] = ModelCapability(
                provider_support=_wire_text(
                    item.get("provider_support"),
                    f"{label} {name!r} provider_support",
                    _invalid,
                ),
                gateway_status=_wire_text(
                    item.get("gateway_status"),
                    f"{label} {name!r} gateway_status",
                    _invalid,
                ),
                reason=_optional_text(item.get("reason"), f"{label} {name!r} reason"),
            )
        except (TypeError, ValueError) as exc:
            _invalid(f"{label} {name!r}: {exc}")
    return capabilities


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _wire_text(value, label, _invalid)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        _invalid(f"{label} must be a boolean")
    return value


def _optional_boolean(value: object, label: str) -> bool | None:
    return None if value is None else _boolean(value, label)


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        _invalid(f"{label} must be a number")
    return float(value)


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _invalid(f"{label} must be a positive integer")
    return value


def _optional_timestamp(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    raw = _wire_text(value, label, _invalid)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        _invalid(f"{label} must be an ISO 8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _invalid(f"{label} must include a timezone")
    return parsed


__all__: list[str] = []
