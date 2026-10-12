"""Expansion, binding and the gate of a code-pointer group (contracts C3, C4) — pure.

FEATURE: code-pointer intents run as RDS calls. A direct transcription of the Lean model
(``docs/spec/2026-10-10-url4-rds-code-pointer/formal/``): :func:`expand` is
``Expansion.expandAll``, :func:`bind` is ``Binding.bind`` and :func:`gate_open` is
``Gate.gate``. No I/O and no DAG types, so the property tests check these functions
against the theorems directly (test-plan §2).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from url4.core.code import CodeInput, CodeValue, CodeWeight
from url4.core.errors import ParseError
from url4.core.nodes import Params

SlotKind = Literal["text", "json", "rows", "expand"]
"""How a source's settled payload becomes a :class:`~url4.core.code.CodeValue` (C3).

``text`` keeps the exact string; ``json`` decodes a struct, iteration or broadcast
result; ``rows`` types a map's row list; ``expand`` splits an expansion source into one
input per element. The kind comes from the source's EXPRESSION, never its content.
"""

Quorum = int | Literal["majority"] | None
"""``quorum=N``, ``quorum=majority``, or ``None`` for the default ``all`` (C §12.2)."""

SlotResult = str | list[str] | None
"""A settled source: its text, its elements or rows, or ``None`` when it failed."""


@dataclass(frozen=True, slots=True)
class CodeSlot:
    """One source of a code group, as the lowering knows it."""

    name: str | None
    weight: CodeWeight | None
    required: bool
    kind: SlotKind = "text"


@dataclass(frozen=True, slots=True)
class Settled:
    """One source after expansion (B §5.3.12): Lean ``Expansion.Entry``."""

    position: int
    name: str | None
    weight: CodeWeight | None
    required: bool
    text: str | None  # the resolved text; None = failed
    value: CodeValue = None

    @property
    def resolved(self) -> bool:
        return self.text is not None

    def as_input(self) -> CodeInput:
        return CodeInput(self.position, self.name, self.value, self.weight)


def expand(slots: Sequence[CodeSlot], results: Sequence[SlotResult]) -> list[Settled]:
    """Expand and renumber (B §5.3.12.4–6); Lean ``expandAll``.

    INVARIANT: positions are 1..T after expansion, in source order. An expansion source
    becomes one entry per element, named ``name[i]`` (or ``src[i]`` when unnamed) with
    weight ``declared / N``; a FAILED expansion source stays one failed entry.
    """
    settled: list[Settled] = []
    for slot, result in zip(slots, results, strict=True):
        if slot.kind == "expand" and isinstance(result, list):
            share = _split_weight(slot.weight, len(result))
            for i, element in enumerate(result):
                name = f"{slot.name or 'src'}[{i}]"
                position = len(settled) + 1
                value = _element_value(element)
                settled.append(Settled(position, name, share, slot.required, element, value))
            continue
        text = _text_of(result)
        value = None if result is None else _typed(slot.kind, result)
        settled.append(
            Settled(len(settled) + 1, slot.name, slot.weight, slot.required, text, value)
        )
    return settled


def bind(settled: Sequence[Settled]) -> tuple[CodeInput, ...]:
    """Lean ``bind``: one input per RESOLVED source, at its own position.

    INVARIANT (``find?_pos_bind``, ``payload_bind_reweigh``): a failed source gives no
    input — no key, no ``None``, no placeholder — and weight never filters delivery
    (a weight-``0.0`` source is delivered with its weight).
    """
    return tuple(entry.as_input() for entry in settled if entry.resolved)


def needed(total: int, quorum: Quorum) -> int | None:
    """The resolved count a quorum needs over ``total`` sources, or None for ``all``."""
    if quorum == "majority":
        return total // 2 + 1
    return quorum


def gate_open(settled: Sequence[Settled], quorum: Quorum) -> bool:
    """Lean ``gate``: every required source resolved, and the quorum met (C §12.2).

    Counts are after expansion and include weight-``0.0`` sources. ``all`` (None) asks
    only for the required sources (owner decision Q9), so an all-optional, all-failed
    group is open and runs with no inputs (``gate_all_of_all_optional``).
    """
    if any(entry.required and not entry.resolved for entry in settled):
        return False
    floor = needed(len(settled), quorum)
    return floor is None or sum(entry.resolved for entry in settled) >= floor


def broadcast_calls(
    settled: Sequence[Settled], refs: set[str]
) -> list[tuple[Settled, tuple[CodeInput, ...]]]:
    """Lean ``calls`` for ``!*``: one call per resolved source (B §6.1.2).

    Each call gets its source first (``$current``), then every OTHER resolved source a
    ``$``-reference in the pointer names (by name or position), at its original position.
    """
    resolved = [entry for entry in settled if entry.resolved]
    calls = []
    for current in resolved:
        others = [
            entry.as_input()
            for entry in resolved
            if entry is not current and (entry.name in refs or str(entry.position) in refs)
        ]
        calls.append((current, (current.as_input(), *others)))
    return calls


def pointer_bindings(slots: Sequence[CodeSlot], results: Sequence[SlotResult]) -> dict[str, str]:
    """The ``$name`` / ``$N`` texts a code pointer may reference (B §6.2: the group's own).

    Mirrors the LLM group's gather: positions after expansion; an expansion's name binds
    the JSON array of its elements; a failed source binds nothing.
    """
    bindings: dict[str, str] = {}
    position = 0
    for slot, result in zip(slots, results, strict=True):
        if result is None:
            position += 1
            continue
        if slot.kind == "expand" and isinstance(result, list):
            for element in result:
                position += 1
                bindings[str(position)] = element
            if slot.name is not None:
                bindings[slot.name] = json.dumps([_element_value(e) for e in result])
            continue
        position += 1
        text = _text_of(result) or ""
        bindings[str(position)] = text
        if slot.name is not None:
            bindings[slot.name] = text
    return bindings


def code_quorum(params: Params) -> Quorum:
    """The group's ``quorum=`` param for a code group: ``N``, ``majority`` or ``all``."""
    value = next((value for key, value in params if key == "quorum"), None)
    if value is None or value == "all":
        return None
    if value == "majority":
        return "majority"
    try:
        return int(value)
    except ValueError:
        raise ParseError(
            f"invalid quorum={value!r}; expected an integer, 'all' or 'majority'"
        ) from None


def _text_of(result: SlotResult) -> str | None:
    if result is None or isinstance(result, str):
        return result
    return json.dumps([_element_value(row) for row in result])


def _typed(kind: SlotKind, result: str | list[str]) -> CodeValue:
    """C3 value typing: from the source's form, never from its content."""
    if isinstance(result, list):
        # WHY exact strings: a row is "the per-element result" (B §5.3.8), text by
        # construction; decoding a row that LOOKS like JSON would type it by content.
        return list(result)
    return _json_or_text(result) if kind == "json" else result


def _element_value(element: str) -> CodeValue:
    """An element or row: a visibly structured one (``{…}``/``[…]``) decodes, else text.

    WHY: the collection parser (§5.3.7) hands elements over as strings and JSON-encodes
    structured ones; the same rule types a map's rows (``_rows_to_json``).
    """
    return _json_or_text(element) if element[:1] in "[{" else element


def _json_or_text(text: str) -> CodeValue:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _split_weight(weight: CodeWeight | None, count: int) -> CodeWeight | None:
    """B §5.3.12.6: each of ``count`` elements carries ``declared / count``."""
    if weight is None or count == 0:
        return weight
    if isinstance(weight, Mapping):
        return {key: value / count for key, value in weight.items()}
    return weight / count


__all__ = [
    "CodeSlot",
    "Quorum",
    "Settled",
    "SlotKind",
    "SlotResult",
    "bind",
    "broadcast_calls",
    "code_quorum",
    "expand",
    "gate_open",
    "needed",
    "pointer_bindings",
]
