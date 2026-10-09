"""The reduce step: ``(src*(body))!reducer`` — one reducer over all rows.

:class:`ReduceNode` owns the reducer: a relative-expression reducer (``/reduce(all)``,
fetched with the JSON row array as its intent), a code-pointer reducer (one call with the
rows as ``$1``), or the ``process`` hook for any other reducer text.

Split out of :mod:`url4.dag.nodes.iteration`: the reduce step carries the code-pointer call
and the relative-expression fetch, which are their own reason to change, while expansion
and per-row mapping stay there. The dependency is one-directional: this module imports
nothing from :mod:`url4.dag.nodes.iteration`, and :mod:`url4.dag.nodes` re-exports the
class from here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.grammar import parse as grammar_parse
from url4.core.intent import CodePointer
from url4.core.nodes import RelExpr as AstRelExpr
from url4.core.parser import split_intent
from url4.dag.semantics.ensemble import substitute_env_vars
from url4.wire.subrequest import encode_subrequest

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
)
from url4.dag.nodes._shared import (  # isort: skip
    _as_text,
    _rows_to_json,
)
from url4.dag.nodes.code_pointer import call_reducer_code_pointer  # isort: skip


@dataclass(eq=False)
class ReduceNode:
    """``(src*(body))!reducer`` — reduce all rows through the reducer template.

    The reducer is classified once, when the node is lowered. A URI reducer (``/reduce``
    or ``url4://n/reduce``) is one code-pointer call with the rows as ``$1`` (PRD D8), and
    ``pointer`` holds it. A relative-expression reducer (``/reduce(all)``) is fetched with
    the JSON row array as its intent (``/reduce?q=(all)!<array>``); any other reducer merges
    via ``ctx.process`` with the *raw* reducer text.
    """

    reducer: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"rows": MapNode}
    pointer: CodePointer | None = None

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        rows = inputs["rows"]
        rows = rows if isinstance(rows, list) else [_as_text(rows)]
        if self.pointer is not None:
            return await call_reducer_code_pointer(ctx, self.pointer, rows)
        array_json = _rows_to_json(rows)
        reducer_src, _, _ = split_intent(self.reducer)
        node = grammar_parse(reducer_src)
        if isinstance(node, AstRelExpr):
            return await self._dispatch(node, array_json, ctx)
        return await ctx.process(array_json, self.reducer, ctx.scope)

    async def _dispatch(self, expr: AstRelExpr, array_json: str, ctx: ExecutionContext) -> str:
        context = substitute_env_vars(expr.context or "", ctx.scope, strict=ctx.strict_fields)
        # WHY: array_json is the row data, not a template: pass it through verbatim.
        # Running $-substitution over it would collapse a row's literal "$$" or
        # replace a "$1" that happens to match an in-scope binding — corrupting
        # the very data the reducer is meant to see. encode_subrequest wire-escapes
        # it, so quotes/newlines survive the URL without any JSON pre-escaping.
        return await ctx.io.fetch(encode_subrequest(expr.path, context, array_json), relative=True)
