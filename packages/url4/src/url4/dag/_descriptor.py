"""Descriptor lowering (spec §4.3): a :class:`~url4.core.nodes.Source` wrapper → DAG nodes.

Split out of :mod:`url4.dag._lowering` (module-size cap): the two-axis
descriptor lowers its value, pushes the attribution label into the fan-out
metadata, then wraps outward — :class:`~url4.dag.nodes.ExpandNode` for
``;expand``/``*source``, :class:`~url4.dag.nodes.GuardNode` for
``;optional``/``;t=``/``;retry=``. The value itself lowers through the caller's
registry, so this module names no other lowerer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from url4.core._annotations import checked_retries, checked_timeout
from url4.core.errors import ParseError
from url4.core.nodes import Binding, Node, Source

from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import ExpandNode, GuardNode, RelUrlNode, RemoteFetchNode, WebFetchNode  # isort: skip
from url4.dag.nodes.blob import as_collection  # isort: skip

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
    if node.expand:
        inner = ExpandNode(deps={"inner": as_collection(inner)})  # a blob ref is text (D4)
    if guard is not None:
        optional, timeout, retries = guard
        inner = GuardNode(
            inner, optional=optional, timeout=timeout, retries=retries, deps=dict(edges)
        )
    return inner


def _guard_options(
    ann: dict[str, str | None], node: Source
) -> tuple[bool, float | None, int] | None:
    """Decode ``;optional`` / ``;t=`` / ``;retry=`` — None when no guard is needed."""
    optional = "optional" in ann
    timeout = _annotation_number(ann.get("t"), "t", float, checked_timeout, node)
    retries = _annotation_number(ann.get("retry"), "retry", int, checked_retries, node)
    if not optional and timeout is None and not retries:
        return None
    return optional, timeout, retries or 0


def _annotation_number(raw: str | None, key: str, cast: Callable, check: Callable, node: Source):
    """Cast and range-check one guard value (the shared rule in ``core._annotations``)."""
    if raw is None:
        return None
    try:
        value = cast(raw)
    except ValueError:
        value = None
    where = node.name or node.value
    try:
        if value is None:
            raise ValueError(f"must be {'an integer' if cast is int else 'a number'}")
        return check(value)
    except ValueError as exc:
        raise ParseError(f"invalid ;{key}={raw!r} on source {where!r}: {exc}") from None


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
