"""The immutable set of combine operators the endpoint can resolve.

FEATURE: one source of truth for which operator ids exist (OME-1289 E4a). The endpoint resolves
spec steps through it, and ``GET /v1/operators`` (unit 3) lists exactly the same entries, so the
catalog and the endpoint cannot disagree (FW-D7).

INVARIANT: construction IS registration. There is no mutable ``register()``; a duplicate id stops
the process when the registry is built (FW-D5). Imitates ``benchmarks/registry.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType

from screamingface_engine.combine.ports import (
    OperatorDescriptor,
    OperatorUnknown,
    SpecInvalid,
    Stage,
)


class OperatorRegistry:
    """One immutable set of combine operators (built once at import, in combine/builtins.py)."""

    __slots__ = ("_by_id",)

    def __init__(self, descriptors: Iterable[OperatorDescriptor] = ()) -> None:
        selected: dict[str, OperatorDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.id in selected:
                raise ValueError(f"duplicate combine operator id {descriptor.id!r}")
            selected[descriptor.id] = descriptor
        self._by_id: Mapping[str, OperatorDescriptor] = MappingProxyType(selected)

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[OperatorDescriptor]:
        for op_id in sorted(self._by_id):
            yield self._by_id[op_id]

    def __contains__(self, op_id: object) -> bool:
        return op_id in self._by_id

    def resolve(self, op_id: str, stage: Stage) -> OperatorDescriptor:
        """The descriptor for ``op_id`` at ``stage``; never echoes anything but the id."""
        descriptor = self._by_id.get(op_id)
        if descriptor is None:
            raise OperatorUnknown(f"combine operator {op_id!r} is not registered")
        if descriptor.stage != stage:
            raise SpecInvalid(
                f"combine operator {op_id!r} is a {descriptor.stage} operator, not {stage}"
            )
        return descriptor

    def describe(self) -> list[dict[str, object]]:
        """The catalog entries, sorted by id."""
        return [descriptor.catalog_entry() for descriptor in self]


__all__ = ["OperatorRegistry"]
