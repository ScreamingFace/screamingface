"""The Candidate Result body, written as JSON text one piece at a time.

FEATURE memory fix 3 (OME-1835), unit 1. A Candidate Result body is a head plus one compact
JSON fragment per Case. ``write_result_body`` writes the same bytes as
``compact_json(as_payload())`` without the whole dict tree or one whole str.
INVARIANT: byte identity with ``compact_json(CandidateResult.as_payload())``, including key
order (``inverted_grade`` and ``scores`` come after ``cases``), NaN, and ``ensure_ascii=False``.
Do NOT use world/streamed_json.py (it sets allow_nan=False) or model_dump_json (another encoder).
This module is a leaf (it imports only contract), so grading_endpoints imports it at module level.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from screamingface_engine.benchmarks.contract import CandidateResult


def compact_json(value: object) -> str:
    """Encode a deterministic endpoint result without ASCII loss or padding."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ResultBody(Protocol):
    def head(self) -> dict[str, Any]:
        """The top-level payload in wire key order, with 'cases' == []."""
        ...

    def case_fragments(self) -> Iterator[str]:
        """Each Case as compact JSON, in roll-call order."""
        ...


@dataclass(frozen=True, slots=True)
class HeldResultBody:
    """A finished CandidateResult held in memory (unit 1). Unit 2 adds a parked body."""

    result: CandidateResult

    def head(self) -> dict[str, Any]:
        # WHY model_copy: model_copy does not validate. It shares the other fields and drops
        # only the Case list, so exclude_if on inverted_grade/scores still applies.
        return self.result.model_copy(update={"cases": []}).as_payload()

    def case_fragments(self) -> Iterator[str]:
        for case in self.result.cases:
            yield compact_json(case.model_dump(by_alias=True))


def write_result_body(body: ResultBody, write: Callable[[str], None]) -> None:
    """Write ``body`` as compact JSON text to ``write``, one piece at a time.

    The pieces joined are byte-identical to ``compact_json(as_payload())``: the head keys in
    wire order, with the Case fragments in place of ``cases``.
    """

    write("{")
    for index, (key, value) in enumerate(body.head().items()):
        if index:
            write(",")
        write(compact_json(key))
        write(":")
        if key == "cases":
            _write_cases(body, write)
        else:
            write(compact_json(value))
    write("}")


def _write_cases(body: ResultBody, write: Callable[[str], None]) -> None:
    write("[")
    for index, fragment in enumerate(body.case_fragments()):
        if index:
            write(",")
        write(fragment)
    write("]")


def encode_result_body(body: ResultBody) -> str:
    """The whole body as one str (tests and small callers only)."""

    parts: list[str] = []
    write_result_body(body, parts.append)
    return "".join(parts)


__all__ = [
    "HeldResultBody",
    "ResultBody",
    "compact_json",
    "encode_result_body",
    "write_result_body",
]
