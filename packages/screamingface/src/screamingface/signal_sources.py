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
from typing import ClassVar


class SignalSource(ABC):
    """Non-constructible umbrella type for the sources a Fusion declares in ``signals=``."""

    source: ClassVar[str]  # the wire word: "verbalized" (unit 4: "logprob", "entropy")

    @abstractmethod
    def _spec(self) -> dict[str, object]:
        """The combine-spec entry, for example {"source": "verbalized", "pattern": "..."}."""

    @classmethod
    @abstractmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> SignalSource:
        """Rebuild an equal source from its spec entry; ValueError when this SDK did not write."""

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
        raise NotImplementedError("E4b part 3 unit 2")

    def _spec(self) -> dict[str, object]:
        raise NotImplementedError("E4b part 3 unit 2")

    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Verbalized:
        raise NotImplementedError("E4b part 3 unit 2")


def declared_from_spec(entries: object) -> dict[str, SignalSource] | None:
    """The declaration of a decoded combine spec (its ``signals`` value), or None when absent."""
    raise NotImplementedError("E4b part 3 unit 2")


def python_signals(declared: Mapping[str, SignalSource]) -> str:
    """``{'conf': sf.Verbalized('...')}``: the ``signals=`` text of ``Url4.to_python``."""
    raise NotImplementedError("E4b part 3 unit 2")


__all__ = ["SignalSource", "Verbalized"]
