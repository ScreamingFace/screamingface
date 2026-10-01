"""Private immutable collections with position and domain-name lookup."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from types import MappingProxyType
from typing import Protocol, overload


class _Named(Protocol):
    @property
    def name(self) -> str: ...


def _require_unique_names(names: Iterable[str], *, duplicate_label: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"duplicate {duplicate_label} name {name!r}")
        seen.add(name)


class _NamedValues[Value: _Named](Sequence[Value]):
    """Preserve declared order while offering strict lookup by unique name."""

    __slots__ = ("_items", "_names")

    def __init__(
        self,
        values: Sequence[Value],
        *,
        empty_message: str,
        item_type: type[Value],
        type_message: str,
        duplicate_label: str,
    ) -> None:
        items = tuple(values)
        if not items:
            raise ValueError(empty_message)
        if any(not isinstance(item, item_type) for item in items):
            raise TypeError(type_message)
        _require_unique_names((item.name for item in items), duplicate_label=duplicate_label)
        self._items = items
        self._names = MappingProxyType({item.name: item for item in items})

    @overload
    def __getitem__(self, index: int) -> Value: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Value, ...]: ...

    @overload
    def __getitem__(self, index: str) -> Value: ...

    def __getitem__(self, index: int | slice | str) -> Value | tuple[Value, ...]:
        if isinstance(index, str):
            try:
                return self._names[index]
            except KeyError:
                raise KeyError(f"unknown {self._item_label} {index!r}") from None
        return self._items[index]

    @property
    def _item_label(self) -> str:
        return type(self).__name__.removeprefix("_").removesuffix("s")

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Value]:
        return iter(self._items)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _NamedValues):
            return self._items == other._items
        if isinstance(other, Sequence):
            return self._items == tuple(other)
        return NotImplemented

    def __repr__(self) -> str:
        return repr(self._items)

    @property
    def only(self) -> Value:
        if len(self._items) != 1:
            raise ValueError(
                f"{type(self).__name__.removeprefix('_')}.only requires exactly one value"
            )
        return self._items[0]


__all__: list[str] = []
