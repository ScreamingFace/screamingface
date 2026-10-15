"""Declared signal sources of a Fusion (E4b part 3): sf.Verbalized; unit 4 adds Logprob, Entropy.

FEATURE: a Fusion names a number that each member answer carries (ans:Q1).
STORY: as a benchmark author, I declare signals={"conf": sf.Verbalized(r"Confidence: ([0-9]+)")}
and weight a vote with sf.signal("conf").
INVARIANT: a source compiles to one entry of the combine spec ``signals`` map, and ``_from_spec``
rebuilds an equal source from that entry (url4 → Python).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from screamingface._regex_rule import check_signal_pattern


class SignalSource(ABC):
    """Non-constructible umbrella type for the sources a Fusion declares in ``signals=``."""

    source: ClassVar[str]  # the wire word: "verbalized" (unit 4: "logprob", "entropy")

    @abstractmethod
    def _spec(self) -> dict[str, object]:
        """The combine-spec entry, for example {"source": "verbalized", "pattern": "..."}."""

    @classmethod
    @abstractmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> SignalSource:
        """Rebuild an equal source from its spec entry; ValueError when this SDK did not write
        it."""

    def _python(self) -> str:
        return f"sf.{self!r}"


@dataclass(frozen=True, slots=True, init=False)
class Verbalized(SignalSource):
    """A number that the member states in its text, for example ``Confidence: 90`` (ans:Q9).

    The pattern has exactly one capture group (RE2 syntax). The Engine reads the last 65,536
    characters of the reply, takes the LAST match, strips spaces, and keeps the group only when it
    is an ASCII decimal number (``-3``, ``87.5``); else the value is missing. No scale is applied:
    ask every member for the same scale.
    """

    source: ClassVar[str] = "verbalized"
    pattern: str
    ignore_case: bool

    def __init__(self, pattern: str, *, ignore_case: bool = False) -> None:
        check_signal_pattern(pattern, ignore_case, "sf.Verbalized")
        object.__setattr__(self, "pattern", pattern)
        object.__setattr__(self, "ignore_case", ignore_case)

    def __repr__(self) -> str:
        extra = ", ignore_case=True" if self.ignore_case else ""
        return f"Verbalized({self.pattern!r}{extra})"

    def _spec(self) -> dict[str, object]:
        entry: dict[str, object] = {"source": "verbalized", "pattern": self.pattern}
        if self.ignore_case:
            entry["ignore_case"] = True  # WHY only when set: one spelling per declaration (DS-1)
        return entry

    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Verbalized:
        if entry.get("source") != "verbalized" or not set(entry) <= {
            "source",
            "pattern",
            "ignore_case",
        }:
            raise ValueError(_CANNOT_REBUILD)
        if "ignore_case" in entry and entry["ignore_case"] is not True:
            raise ValueError(_CANNOT_REBUILD)  # this SDK writes ignore_case only as true
        pattern = entry.get("pattern")
        if not isinstance(pattern, str):
            raise ValueError(_CANNOT_REBUILD)
        return cls(pattern, ignore_case="ignore_case" in entry)


_CANNOT_REBUILD = "URL4 Candidate has a signals declaration this SDK version cannot rebuild"
# wire word -> class; unit 4 adds "logprob" and "entropy"
_SOURCES: Mapping[str, type[SignalSource]] = MappingProxyType({"verbalized": Verbalized})


def declared_from_spec(entries: object) -> dict[str, SignalSource] | None:
    """The declaration of a decoded combine spec (its ``signals`` value), or None when absent."""
    if entries is None:
        return None
    if not isinstance(entries, Mapping) or not entries:
        raise ValueError(_CANNOT_REBUILD)
    declared: dict[str, SignalSource] = {}
    for name, entry in entries.items():
        source = entry.get("source") if isinstance(entry, Mapping) else None
        kind = _SOURCES.get(source) if isinstance(source, str) else None
        if not isinstance(name, str) or kind is None or not isinstance(entry, Mapping):
            raise ValueError(_CANNOT_REBUILD)
        try:
            declared[name] = kind._from_spec(entry)
        except (TypeError, ValueError) as exc:
            raise ValueError(_CANNOT_REBUILD) from exc
    return declared


def python_signals(declared: Mapping[str, SignalSource]) -> str:
    """``{'conf': sf.Verbalized('...')}``: the ``signals=`` text of ``Url4.to_python``."""
    return (
        "{" + ", ".join(f"{name!r}: {source._python()}" for name, source in declared.items()) + "}"
    )


__all__ = ["SignalSource", "Verbalized"]
