"""Immutable accounting retained for one semantic evaluation operation."""

from __future__ import annotations

from dataclasses import dataclass

from screamingface._report_primitives import Usage, _nonblank_text


@dataclass(frozen=True, slots=True)
class OperationCache:
    """How many consumed responses of one operation the response cache served.

    The four counts sum to the number of model-call responses the owning record
    represents — provider retries folded inside one Gateway response are not
    extra responses. A confirmed hit contributes zero current tokens and cost.
    """

    hits: int
    misses: int
    bypasses: int
    unknown: int

    def __post_init__(self) -> None:
        for name in ("hits", "misses", "bypasses", "unknown"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Operation cache {name} must be a non-negative integer")
        # INVARIANT: the count sum is the represented response count, so a
        # record describing zero responses describes nothing and must not exist.
        if self.hits + self.misses + self.bypasses + self.unknown < 1:
            raise ValueError("operation cache accounting requires at least one response")

    def to_dict(self) -> dict[str, object]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "bypasses": self.bypasses,
            "unknown": self.unknown,
        }


@dataclass(frozen=True, slots=True)
class OperationAccounting:
    """What one semantic operation actually consumed, exactly or not at all.

    FEATURE: OME-901 per-operation accounting — completed Reports can explain
    their authoritative total by stage, model, member, and Case.

    INVARIANT: exact-only. Every field is null unless the Engine observed it
    completely; nothing is divided, inferred from execution order, or defaulted
    to zero. A false zero would read as "this operation was free".

    ``provider_latency_ms`` is summed provider-attempt latency, not operation
    wall time. ``provider_attempts`` makes retry-heavy routes distinguishable
    from slow models. A confirmed cache hit has zero current attempts; an
    incompletely validated attempt list stays null.
    """

    provider: str | None
    request_model: str | None
    response_model: str | None
    usage: Usage
    provider_latency_ms: int | None
    provider_attempts: int | None
    cache: OperationCache

    def __post_init__(self) -> None:
        for name in ("provider", "request_model", "response_model"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self, name, _nonblank_text(value, f"Operation accounting {name}")
                )
        if not isinstance(self.usage, Usage):
            raise TypeError("Operation accounting usage must be an sf.Usage")
        if not isinstance(self.cache, OperationCache):
            raise TypeError("Operation accounting cache must be an sf.OperationCache")
        for name in ("provider_latency_ms", "provider_attempts"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(
                    f"Operation accounting {name} must be a non-negative integer or None"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "request_model": self.request_model,
            "response_model": self.response_model,
            "usage": self.usage.to_dict(),
            "provider_latency_ms": self.provider_latency_ms,
            "provider_attempts": self.provider_attempts,
            "cache": self.cache.to_dict(),
        }
