"""Immutable public local diagnostic receipt."""

from __future__ import annotations

import json
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from typing import Any


class DiagnosticReceipt:
    """One privacy-safe local record of a failed ScreamingFace operation."""

    __slots__ = ("_document",)

    def __init__(self) -> None:
        raise TypeError("DiagnosticReceipt values are created by ScreamingFace operations")

    @classmethod
    def _from_frozen(cls, document: Mapping[str, object]) -> DiagnosticReceipt:
        value = object.__new__(cls)
        object.__setattr__(value, "_document", document)
        return value

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DiagnosticReceipt values are immutable")

    @property
    def diagnostic_id(self) -> str:
        return _string_field(self._document, "diagnostic_id")

    @property
    def session_id(self) -> str:
        return _string_field(self._document, "session_id")

    @property
    def outcome(self) -> str:
        return _string_field(self._document, "outcome")

    def to_dict(self) -> dict[str, Any]:
        return {key: _thaw(value) for key, value in self._document.items()}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def export(self, path: str | PathLike[str] = "diagnostic.json") -> Path:
        """Write this receipt after an explicit caller action and return its path."""

        selected = Path(path)
        if selected.suffix.lower() != ".json":
            raise ValueError("Diagnostic export path must be a .json file")
        selected.parent.mkdir(parents=True, exist_ok=True)
        selected.write_text(self.to_json(), encoding="utf-8")
        return selected

    def __repr__(self) -> str:
        return f"DiagnosticReceipt({self.diagnostic_id!r}, outcome={self.outcome!r})"


def _string_field(document: Mapping[str, object], name: str) -> str:
    value = document[name]
    if not isinstance(value, str):
        raise AssertionError(f"Diagnostic {name} must remain a string")
    return value


def _thaw(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


__all__ = ["DiagnosticReceipt"]
