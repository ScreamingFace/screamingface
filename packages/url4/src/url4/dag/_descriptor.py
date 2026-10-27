"""Descriptor lowering (spec §4.3): a :class:`~url4.core.nodes.Source` wrapper → DAG nodes.

Split out of :mod:`url4.dag._lowering` (module-size cap): the two-axis
descriptor lowers its value, pushes the attribution label into the fan-out
metadata, then wraps outward — :class:`~url4.dag.nodes.ExpandNode` for
``;expand``/``*source``, :class:`~url4.dag.nodes.GuardNode` for
``;optional``/``;t=``/``;retry=``. The value itself lowers through the caller's
registry, so this module names no other lowerer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from url4.core.nodes import Binding, Node, Source

from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import ExpandNode, GuardNode, RelUrlNode, RemoteFetchNode, WebFetchNode  # isort: skip
from url4.dag.nodes.blob import as_collection  # isort: skip

# WHY: the guard-policy decoding moved to :mod:`url4.dag.attachment_sources` (OME-1543 round
# 7), the one decoding an attachment identity shares with its GuardNode; re-exported here.
from url4.dag.attachment_sources import _annotation_number as _annotation_number  # isort: skip
from url4.dag.attachment_sources import guard_policy as _guard_options  # isort: skip
from url4.dag.attachment_sources import identity_of  # isort: skip

if TYPE_CHECKING:  # the registry type only — this module never constructs one
    from url4.dag._lowering import LoweringRegistry
    from url4.dag._wiring import Edges


def _lower_source(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    """Lower a two-axis descriptor (spec §4.3): label, expand, then guard.

    A guarded subtree is lowered without edges — the guard carries them and
    hands the resolved values to the isolated sub-execution as a scope frame
    (see the :mod:`url4.dag._lowering` docstring). Everything else keeps edges
    on the value.
    """
    assert isinstance(node, Source)
    ann = dict(node.annotations)
    guard = _guard_options(ann, node)
    inner = registry.lower(node.value, {} if guard is not None else edges)
    _push_label(inner, node, ann)
    if isinstance(inner, WebFetchNode):
        inner.attachment = identity_of(node)  # None for every text source (F1b round 7)
    if node.expand:
        inner = ExpandNode(deps={"inner": as_collection(inner)})  # a blob ref is text (D4)
    if guard is not None:
        optional, timeout, retries = guard
        inner = GuardNode(
            inner, optional=optional, timeout=timeout, retries=retries, deps=dict(edges)
        )
    return inner


def _push_label(inner: DagNode, node: Source, ann: dict[str, str | None]) -> None:
    """Attach the descriptor's attribution label / ``;accept=`` to the fetch node."""
    if isinstance(inner, RelUrlNode) and inner.is_expr:
        inner.name = node.name
        inner.weight = _scalar_weight(node.weight)
    if isinstance(inner, (RelUrlNode, WebFetchNode, RemoteFetchNode)) and "accept" in ann:
        inner.accept = ann["accept"]


def _scalar_weight(weight: float | dict | None) -> float | None:
    """A structured weight's fan-out label scalar: ``_default`` or none (§4.1.1.8)."""
    if isinstance(weight, dict):
        default = weight.get("_default")
        return float(default) if isinstance(default, (int, float)) else None
    return weight


def slot_identity(ast: Node) -> tuple[str | None, bool, float | dict | None]:
    """The slot's ``(name, instrumental, weight)`` — ABNF contribution semantics.

    WHY Binding is never instrumental (`OME-534`): the name-only forms
    (``a: v`` / ``a=v``) are contributing sources under the ABNF; the ONLY
    instrumental marker is an explicit scalar ``weight 0.0`` on a Source.
    """
    if isinstance(ast, Binding):
        return ast.name, False, None
    if isinstance(ast, Source):
        return ast.name, _is_instrumental_weight(ast.weight), ast.weight
    return None, False, None


def _is_instrumental_weight(weight: object) -> bool:
    """True for the explicit scalar ``0.0`` (structured weights never qualify)."""
    return (
        isinstance(weight, (int, float)) and not isinstance(weight, bool) and float(weight) == 0.0
    )
