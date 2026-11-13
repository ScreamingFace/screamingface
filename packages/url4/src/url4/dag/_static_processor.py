"""Compute a Form-3 processor expression before the run, when nothing in it needs the run.

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a reduce whose processor expression is plain text computing a
``url4://`` URI (``(p:0:'url4://n2/v1')!'$p'``) is refused before any member of the reduce runs.

INVARIANT: :func:`static_processor_value` returns the value the run WOULD compute, or ``None``
when it cannot know it without running something. It knows it only for a graph of inline text
(:class:`TextNode` with no edges) under text-intent groups (:class:`ProcessNode` with an
``intent_template``) merged by :func:`default_process`, where every ``$`` reference resolves to the
group's own slots. Anything else (a fetch, a reference to an outer binding, a custom ``process``
merge hook, a strict field-path error) is ``None``; the run-time check still covers it.
WHY strict and bound here: a reference the static pass cannot resolve means the run's scope would
decide it, so the value is dynamic, not a guess.
"""

from __future__ import annotations

from url4.core.context import Context
from url4.core.errors import Url4Error
from url4.core.parser import build
from url4.dag._context import default_process
from url4.dag.compiler import LoweringRegistry, compile_expression
from url4.dag.node import DagNode, ProcessFn
from url4.dag.nodes import ProcessNode, TextNode
from url4.dag.nodes._shared import _check_quorum, _gather
from url4.dag.semantics.ensemble import interpolate


async def static_processor_value(
    expression: str, registry: LoweringRegistry | None, process: ProcessFn
) -> str | None:
    """The value a Form-3 ``expression`` computes, or ``None`` when only the run can tell."""
    if process is not default_process:
        return None  # WHY: a custom merge hook (a model call) is run-time work
    try:
        build(expression)  # INVARIANT: the same grammar gate `processor._evaluate` applies
        sink = compile_expression(expression, registry=registry, bare_root_ok=True).sink
        value = await _value(sink)
    except Url4Error:
        return None  # an expression the run would reject is the run's error to report
    return None if value is None else value.strip()


async def _value(node: DagNode) -> str | None:
    if isinstance(node, TextNode) and not node.deps:
        return _interpolate(node.template, Context())
    if isinstance(node, ProcessNode) and node.intent_template is not None:
        return await _group_value(node, node.intent_template)
    return None


async def _group_value(node: ProcessNode, intent_template: str) -> str | None:
    """``ProcessNode.resolve`` with the default merge, over slots that are all static."""
    inputs: dict[str, str] = {}
    for role, dep in node.deps.items():
        value = await _value(dep)
        if value is None:
            return None
        inputs[role] = value
    g = _gather(inputs, node.slots)
    _check_quorum(g, node.quorum)
    bindings = {str(i + 1): value for i, value in enumerate(g.positional)} | g.named
    scope = Context(bindings=bindings)
    intent = _interpolate(intent_template, scope)
    return await default_process("\n".join(g.sources), intent, scope)


def _interpolate(template: str, scope: Context) -> str:
    return interpolate(template, scope, strict=True, bound=True)


__all__ = ["static_processor_value"]
