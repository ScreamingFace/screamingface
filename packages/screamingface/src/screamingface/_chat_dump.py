"""The dump methods of the chat reply types, named as the OpenAI objects (contracts C1.7, D24)."""

from __future__ import annotations

import json
from typing import Any


def _without_none(value: Any) -> Any:
    """A copy of the value with no dict key whose value is None, at each depth."""

    if isinstance(value, dict):
        return {key: _without_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


class OpenAIDump:
    """The base of the reply types, with the dump methods of the OpenAI objects (C1.7)."""

    __slots__ = ()

    def to_dict(self) -> dict[str, object]:
        """The object as a new JSON-ready dict with the OpenAI keys."""

        raise NotImplementedError

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, object]:
        """The dict of to_dict(), with no None values when exclude_none is True."""

        if exclude_none:
            return _without_none(self.to_dict())
        return self.to_dict()

    def model_dump_json(self, *, indent: int | None = None, exclude_none: bool = False) -> str:
        """The JSON text of model_dump(), compact when indent is None."""

        return json.dumps(
            self.model_dump(exclude_none=exclude_none),
            indent=indent,
            separators=(",", ":") if indent is None else None,
            ensure_ascii=False,
        )

    def to_json(self, *, indent: int | None = 2) -> str:
        """The JSON text of the object, indented by 2 spaces by default."""

        return self.model_dump_json(indent=indent)
