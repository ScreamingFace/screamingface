"""The internal nodes, for tests that work below the public surface (not a test module; unit 7).

D7-4: a custom ``Reducer`` (``_reducer_fixtures``) is not a step, so a test that drives one builds
the internal ``FusionNode`` with ``fusion_node``. An equality row on an internal value
(``lower(chain) == ...``) names the node classes re-exported here. This is the only test file with
``synthesizer=``.
D7-5: ``frozen_url4(row)`` is the url4 that today's form of a unit 2-6 parity row compiled to
before the swap (``data/surface_parity.json``, written once in step 7d-0; never regenerate it).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any, Literal

from screamingface._surface.lowering import lower
from screamingface.blocks import ReduceNode
from screamingface.fields import MergeNode, PickNode
from screamingface.fusion import FusionNode
from screamingface.gate import GateNode
from screamingface.judge import JudgeNode
from screamingface.recipe import Recipe
from screamingface.reducer import MeanNode, MedianNode, Reducer, VoteNode
from screamingface.selection import ConcatNode, FilterNode, RankNode
from screamingface.signal_sources import SignalSource

__all__ = [
    "ConcatNode",
    "FilterNode",
    "FusionNode",
    "GateNode",
    "JudgeNode",
    "MeanNode",
    "MedianNode",
    "MergeNode",
    "PickNode",
    "RankNode",
    "ReduceNode",
    "VoteNode",
    "frozen_url4",
    "fusion_node",
    "lowered",
]

_SURFACE_PARITY = Path(__file__).parent / "data" / "surface_parity.json"


def fusion_node(
    members: Sequence[str | Recipe],
    reducer: str | Recipe | Reducer,
    *,
    name: str | None = None,
    signals: Mapping[str, SignalSource] | None = None,
    quorum: int | Literal["all"] = "all",
    optional: bool = False,
) -> FusionNode:
    """The internal node of one block: ``members`` fanned out, then ``reducer`` (or a writer)."""

    return FusionNode(
        members, name=name, signals=signals, synthesizer=reducer, quorum=quorum, optional=optional
    )


def lowered(value: object) -> Any:
    """The internal node a chain lowers to, typed ``Any`` for a field read (``.synthesizer``).

    WHY: since the swap (7e) ``to_python()`` builds a chain; a test that checks the reducer a url4
    is recovered as reads it on the lowered node.
    """

    assert isinstance(value, Recipe)
    return lower(value)


@cache
def _frozen() -> Mapping[str, str]:
    rows = json.loads(_SURFACE_PARITY.read_text(encoding="utf-8"))
    assert isinstance(rows, dict)
    return rows


def frozen_url4(row: str) -> str:
    """The url4 that today's form of ``row`` compiled to (``<test file>:<case>``)."""

    return _frozen()[row]
