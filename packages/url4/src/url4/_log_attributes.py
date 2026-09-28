"""Immutable observation snapshots with ordinary detached serialization."""

from collections.abc import Iterator, Mapping
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Self


class _LogAttributes[T](Mapping[str, T]):
    __slots__ = ("_values",)
    _values: Mapping[str, T]

    def __init__(self, values: Mapping[str, T]) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Log attributes are immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Log attributes are immutable")

    def __getitem__(self, key: str) -> T:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return repr(dict(self._values))

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, T]:
        # WHY: asdict deep-copies non-dict mappings field-by-field, bypassing Log's
        # reducer. Its detached result must be a normal dict for JSON consumers.
        return deepcopy(dict(self._values), memo)

    def __reduce__(self) -> tuple[type[Self], tuple[dict[str, T]]]:
        return type(self), (dict(self._values),)
