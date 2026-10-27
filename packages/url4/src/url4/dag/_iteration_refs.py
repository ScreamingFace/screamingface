"""The one reading of an iteration's template strings: its body/intent references.

Split from :mod:`url4.dag._lowering` (module-size cap) by reason to change: this module
changes when the reserved per-row names or the body-reference wiring change; ``_lowering``
changes when a lowerer changes. ``url4.dag._lowering`` re-exports every name here, so no
import path moves.
"""

from __future__ import annotations

from url4.dag.semantics.ensemble import find_references

from url4.dag._wiring import Edges  # isort: skip
from url4.dag.node import DagNode  # isort: skip

_ROW_NAMES = frozenset({"item", "current", "index"})
"""Reserved per-row names, including the SDK index extension.

Both text and AST iteration bodies exclude these from enclosing dependency capture.
Ordinary AST references still retain `index`, which is only reserved inside iteration.
"""


def _body_intent_refs(body: str, intent: str | None) -> set[str]:
    """The `$name`s an iteration's body and per-row intent mention, minus the reserved row names.

    INVARIANT: the ONE reading of an iteration's template strings. Both compilation paths need
    it — `_body_ref_edges` at lowering time and `_refs_of_ast` when collecting a slot's
    references — and if they ever disagree about which names an iteration rebinds for itself,
    the AST path silently stops wiring an outer binding while the text path keeps working. That
    divergence is invisible: the reference substitutes VERBATIM and the run still succeeds.
    """
    return (find_references(body) | (find_references(intent) if intent else set())) - _ROW_NAMES


def _body_ref_edges(body: str, intent: str | None, edges: Edges) -> dict[str, DagNode]:
    """Reference edges for the `$name`s an iteration's body and per-row intent mention.

    INVARIANT: ``item``, ``current`` and ``index`` are reserved row names, excluded here.
    They are rebound by :class:`~url4.dag.nodes.MapNode`; wiring one to an enclosing binding of
    the same name would let an outer value capture the row and silently iterate the wrong data.

    An edge is added only for a name the enclosing group actually declares, so a body that
    references nothing gains no dependency and keeps its previous concurrency.
    """
    wired: dict[str, DagNode] = {}
    for ref in sorted(_body_intent_refs(body, intent)):
        key = f"pos:{ref}" if ref.isdigit() else f"bind:{ref}"
        if key in edges:
            wired[key] = edges[key]
    return wired


__all__ = ["_ROW_NAMES", "_body_intent_refs", "_body_ref_edges"]
