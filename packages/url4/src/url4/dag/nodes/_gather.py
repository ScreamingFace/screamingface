"""The group gather: a group's resolved slots, flattened into values and sources.

Split out of :mod:`url4.dag.nodes._shared`: gathering a group's slots (skipping
failures, splicing ``;expand`` lists, renumbering positions), the quorum check
over that result, and the slot shape the gather reads are their own reason to
change. :mod:`url4.dag.nodes._shared` re-exports every name here, so the node
modules keep importing them from ``_shared``.

This module imports nothing from ``_shared``. The dependency is one-directional,
so the re-export creates no cycle at import time.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from url4.core.errors import ErrorCode, ResolutionError

from url4.dag.node import (  # isort: skip
    Payload,
    SourceFailure,
)


SlotSpec = tuple[str | None, bool]
"""One group slot: ``(name, instrumental)``. ABNF conformance (`OME-534`):
EVERY listed source contributes to the packed context — name-only descriptors
(``a: v`` / ``a=v``) included. The bool marks a scalar-``weight 0.0``
INSTRUMENTAL source: resolved and ``$name``-referenceable, excluded from the
packed sources (the replacement for the old reference-only-Binding concept)."""


def _maybe_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


@dataclass
class _Gathered:
    """The flattened view of a group's slots after failures and expansion."""

    positional: list[str]  # $N values, renumbered post-expansion
    named: dict[str, str]  # $name values (RAW — scope substitution needs them unlabeled)
    sources: list[str]  # the packed source values, in order (named → "name: value")


def _gather(
    inputs: Mapping[str, Payload], slots: tuple[SlotSpec, ...], prefix: str = "src"
) -> _Gathered:
    """Flatten group slots: skip failures, splice expansions, renumber positions.

    WHY the ``name:`` label rides only ``sources``: the packed context a
    processor sees keeps the author's key labels (`OME-534` owner decision),
    while ``named`` feeds ``$name`` substitution and must stay the raw value.
    ``prefix`` selects the dep-key family — ``src:i`` for group slots,
    ``ctx:i`` for a call's context source-list (`OME-535`).
    """
    g = _Gathered([], {}, [])
    for i, (name, instrumental) in enumerate(slots):
        value = inputs[f"{prefix}:{i}"]
        if isinstance(value, SourceFailure):
            continue
        if isinstance(value, list):
            _gather_expanded(g, value, name, instrumental)
            continue
        g.positional.append(value)
        if name is not None:
            g.named[name] = value
        if not instrumental:
            g.sources.append(f"{name}: {value}" if name is not None else value)
    return g


def _gather_expanded(
    g: _Gathered, elements: list[str], name: str | None, instrumental: bool
) -> None:
    """Expanded elements each take a position; the name binds the JSON array,
    so a ``$name[i]`` field path selects one element (spec §5.3.12.5). The
    elements pack BARE — the name labels the array binding, not each element."""
    g.positional.extend(elements)
    if name is not None:
        g.named[name] = json.dumps([_maybe_json(e) for e in elements])
    if not instrumental:
        g.sources.extend(elements)


def _raise_if_quorum_not_met(resolved: int, quorum: int | None, *, permanent: bool = False) -> None:
    """Raise ``quorum_not_met`` when fewer than ``quorum`` sources resolved (spec §9.1).

    WHY: one definition for the LLM groups and the code pointer. Only the code pointer's miss is
    permanent (contracts C7), so the flag is the caller's.
    """
    if quorum is not None and resolved < quorum:
        raise ResolutionError(
            f"quorum not met: {resolved} of {quorum} required sources resolved",
            code=ErrorCode.QUORUM_NOT_MET,
            permanent=permanent,
        )


def _check_quorum(g: _Gathered, quorum: int | None) -> None:
    # The contributing count IS len(sources) — every append above is a contribution.
    _raise_if_quorum_not_met(len(g.sources), quorum)
