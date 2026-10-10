"""Cross-row reduction: ``(src*(body))!reducer`` over a :class:`~.iteration.MapNode`'s rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import RelExpr as AstRelExpr
from url4.core.parser import split_intent
from url4.dag.semantics.ensemble import substitute_env_vars
from url4.wire.subrequest import encode_subrequest

from url4.dag.node import DagNode, ExecutionContext, Payload  # isort: skip
from url4.dag.nodes._shared import _as_text, _rows_to_json  # isort: skip


@dataclass(eq=False)
class ReduceNode:
    """``(src*(body))!reducer`` — reduce all rows through the reducer template.

    The reducer is parsed lazily, here at resolve time: a relative-expression
    reducer (``/reduce(all)``) is fetched with the JSON row array as its intent
    (``/reduce?q=(all)!<array>``); any other reducer merges via ``ctx.process``
    with the *raw* reducer text.
    """

    rds_scope: ClassVar[bool] = False  # a prompt group: lenient (C6)

    reducer: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"rows": MapNode}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        rows = inputs["rows"]
        rows = rows if isinstance(rows, list) else [_as_text(rows)]
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
