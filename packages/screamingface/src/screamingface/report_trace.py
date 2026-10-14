"""The per-Case trace record and its schema (OME-1289 gap, erd s8).

INVARIANT: the field set of each kind is closed. A new kind or field needs
screamingface.report-trace.v2. The trace never holds member text.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from screamingface._immutable_json import freeze_mapping, thaw_mapping

TRACE_SCHEMA = "screamingface.report-trace.v1"
type TraceKind = Literal["model_call", "extract", "reduce", "budget"]
TRACE_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "model_call": (
            "operation_id",
            "member_id",
            "provider",
            "model",
            "cache",
            "cost_usd",
            "latency_ms",
            "tokens_in",
            "tokens_out",
            "status",
        ),
        "extract": ("operation_id", "member_id", "rule", "raw", "value", "status", "reason"),
        "reduce": (
            "operation_id",
            "op",
            "rule",
            "mode",
            "tally",
            "chosen",
            "signal",
            "result",
            "dropped",
        ),
        # reserved: no E4a producer (BU-D4)
        "budget": (
            "event",
            "operation_id",
            "member_id",
            "stage",
            "amount",
            "estimated",
            "source",
            "remaining_after",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """One block execution of a Case trace (screamingface.report-trace.v1, erd s8)."""

    kind: TraceKind
    data: Mapping[str, object]

    def __post_init__(self) -> None:
        fields = TRACE_FIELDS.get(self.kind) if isinstance(self.kind, str) else None
        if fields is None:
            raise ValueError(
                f"unknown trace kind {self.kind!r}; "
                "a new trace kind needs screamingface.report-trace.v2"
            )
        frozen = freeze_mapping(self.data, "Trace entry data")
        if set(frozen) != set(fields):
            raise ValueError(
                f"a {self.kind} trace entry has exactly the fields {', '.join(fields)}"
            )
        object.__setattr__(self, "data", MappingProxyType({name: frozen[name] for name in fields}))

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, **thaw_mapping(self.data)}


__all__: list[str] = []
