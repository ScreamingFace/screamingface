"""Strict retained accounting shared by Candidate operations and grading Evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from decimal import Decimal, localcontext

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FIXED_POINT_USD = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class _StrictAccountingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OperationUsage(_StrictAccountingModel):
    """Six independently optional usage fields for one retained operation."""

    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    cache_read_tokens: int | None = Field(ge=0)
    cache_creation_tokens: int | None = Field(ge=0)
    reasoning_tokens: int | None = Field(ge=0)
    cost_usd: str | None

    @field_validator("cost_usd")
    @classmethod
    def _validate_cost(cls, value: str | None) -> str | None:
        if value is not None and _FIXED_POINT_USD.fullmatch(value) is None:
            raise ValueError("cost_usd must be non-negative fixed-point text or null")
        return value


class OperationCache(_StrictAccountingModel):
    """Consumed response-cache outcomes represented by one semantic operation."""

    hits: int = Field(ge=0)
    misses: int = Field(ge=0)
    bypasses: int = Field(ge=0)
    unknown: int = Field(ge=0)

    @model_validator(mode="after")
    def _require_response(self) -> OperationCache:
        if self.hits + self.misses + self.bypasses + self.unknown < 1:
            raise ValueError("operation cache accounting requires at least one response")
        return self


class OperationAccounting(_StrictAccountingModel):
    """Exact-only current-run accounting retained on one semantic operation."""

    provider: str | None
    request_model: str | None
    response_model: str | None
    usage: OperationUsage
    provider_latency_ms: int | None = Field(ge=0)
    cache: OperationCache

    @field_validator("provider", "request_model", "response_model")
    @classmethod
    def _validate_optional_identity(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("operation identity fields must be non-blank text or null")
        return value


def combine_operation_accounting(
    records: Sequence[OperationAccounting],
) -> OperationAccounting | None:
    """Strictly combine consumed calls that implement one semantic operation."""

    if not records:
        return None
    usage = OperationUsage(
        input_tokens=_sum_int(record.usage.input_tokens for record in records),
        output_tokens=_sum_int(record.usage.output_tokens for record in records),
        cache_read_tokens=_sum_int(record.usage.cache_read_tokens for record in records),
        cache_creation_tokens=_sum_int(record.usage.cache_creation_tokens for record in records),
        reasoning_tokens=_sum_int(record.usage.reasoning_tokens for record in records),
        cost_usd=_sum_cost(record.usage.cost_usd for record in records),
    )
    return OperationAccounting(
        provider=_agreed(record.provider for record in records),
        request_model=_agreed(record.request_model for record in records),
        response_model=_agreed(record.response_model for record in records),
        usage=usage,
        provider_latency_ms=_sum_int(record.provider_latency_ms for record in records),
        cache=OperationCache(
            hits=sum(record.cache.hits for record in records),
            misses=sum(record.cache.misses for record in records),
            bypasses=sum(record.cache.bypasses for record in records),
            unknown=sum(record.cache.unknown for record in records),
        ),
    )


def _agreed(values: Iterable[str | None]) -> str | None:
    rows = tuple(values)
    first = rows[0]
    return first if all(value == first for value in rows[1:]) else None


def _sum_int(values: Iterable[int | None]) -> int | None:
    rows = tuple(values)
    return sum(value for value in rows if value is not None) if None not in rows else None


def _sum_cost(values: Iterable[str | None]) -> str | None:
    rows = tuple(values)
    if any(value is None for value in rows):
        return None
    texts = tuple(value for value in rows if value is not None)
    amounts = tuple(Decimal(value) for value in texts)
    integer_digits = max((len(value.partition(".")[0]) for value in texts), default=1)
    fractional_digits = max((len(value.partition(".")[2]) for value in texts), default=0)
    # INVARIANT: retained money is exact fixed-point text. Decimal addition obeys the ambient
    # context, so precision must cover every integer/fractional digit plus a possible carry from
    # summing N calls rather than silently rounding a long provider-authored amount.
    with localcontext() as context:
        context.prec = integer_digits + fractional_digits + len(str(max(len(amounts), 1)))
        return format(sum(amounts, start=Decimal(0)), "f")


__all__ = [
    "OperationAccounting",
    "OperationCache",
    "OperationUsage",
    "combine_operation_accounting",
]
