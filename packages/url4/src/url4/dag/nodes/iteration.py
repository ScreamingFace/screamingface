"""The collection nodes: expansion, per-row mapping, and cross-row reduction."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.context import Context
from url4.core.ensemble import (
    substitute_env_vars,
)
from url4.core.errors import CollectionError, ErrorCode
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import IterationDirectives
from url4.core.nodes import RelExpr as AstRelExpr
from url4.core.parser import split_intent
from url4.core.subrequest import encode_subrequest
from url4.io.layer import parse_collection

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    reraise_first,
)


from url4.dag.nodes._shared import (  # isort: skip
    DEFAULT_MAP_CONCURRENCY,
    _ITEM_KEY,
    _as_text,
    _error_payload,
    _frame,
    _media_type_of,
    _rows_to_json,
)


@dataclass(eq=False)
class ExpandNode:
    """``*source`` / ``;expand`` — splice a collection into N sources (§5.3.12).

    Resolves the inner value, parses it into elements, and returns them as a
    ``list[str]`` payload; the enclosing group node flattens the list into
    consecutive source positions (renumbering ``$N``, §5.3.12.4). A resolved
    value that is not a collection fails with ``expansion_not_iterable``.
    """

    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"inner": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        inner = inputs["inner"]
        try:
            return parse_collection(_as_text(inner), _media_type_of(inner))
        except CollectionError as exc:
            raise CollectionError(
                f"expansion source is not iterable: {exc}", code=ErrorCode.EXPANSION_NOT_ITERABLE
            ) from exc


@dataclass(eq=False)
class MapNode:
    """``src*(body)`` — evaluate ``body`` once per collection row (spec §5.3).

    Returns ``list[str]`` (the internal Map→Collect/Reduce contract) so row
    boundaries survive rows that contain newlines. Each row spawns
    ``({body})!{intent}`` as an independent sub-graph — per-row parsing happens
    here, at resolve time. The row value is bound into the spawned scope (not
    substituted into the expression text), so ``$item`` resolves at the leaves
    and a row containing ``(``/``!`` can't corrupt the re-parse.

    Spec semantics: an empty collection resolves to zero rows (success,
    §5.3.9); ``iteration.slice`` selects the half-open element range before
    evaluation; ``iteration.on_error`` picks the per-row failure policy —
    ``collect`` (default) embeds error objects, ``skip`` omits failed rows,
    ``fail`` aborts the whole map on the first error (§5.3.6).
    """

    body: str
    intent: str | None = None
    directives: IterationDirectives = field(default_factory=IterationDirectives)
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"collection": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        items = self._items(inputs["collection"])
        if not items:
            return []
        # WHY the frame is built ONCE here, not per row: it is row-invariant (the enclosing
        # group's bindings), and it is what makes an outer `$name` visible inside the body —
        # the same reference-edges-become-a-scope-frame move `LazyExprNode` makes. Without it
        # the body's parent scope is the run scope, so a sibling binding is unreachable and
        # substitutes verbatim.
        frame = _frame(inputs, ctx)
        # `concurrency <= 0` (only reachable by constructing the directives
        # directly — the surface `;iteration.concurrency` syntax rejects n < 1)
        # means "use the default", not "unbounded": a falsy directive must never
        # silently disable the bound.
        concurrency = self.directives.concurrency
        if concurrency is None or concurrency <= 0:
            concurrency = DEFAULT_MAP_CONCURRENCY
        sem = asyncio.Semaphore(concurrency)
        # Row-invariant: built once here rather than per row, since it is also
        # the spawn cache key and would otherwise be re-concatenated and
        # re-hashed len(items) times.
        expr = f"({self.body})!{self.intent}" if self.intent else f"({self.body})"
        if self.directives.on_error == "fail":
            return await self._run_all(items, expr, sem, ctx, frame)
        rows = [self._row(item, expr, sem, ctx, frame) for item in items]
        raw = await asyncio.gather(*rows, return_exceptions=True)
        return self._skip(raw) if self.directives.on_error == "skip" else self._collect(raw, ctx)

    def _items(self, collection: Payload) -> list[str]:
        # An inline parenthesized collection (§5.3.11) arrives pre-materialized as
        # a real element list from InlineCollectionNode — used verbatim, one row
        # per element. A fetched/URI collection arrives as body text parsed by
        # declared or sniffed content type (§5.3.7).
        if isinstance(collection, list):
            items = collection
        else:
            items = parse_collection(_as_text(collection), _media_type_of(collection))
        if self.directives.slice is not None:
            start, end = self.directives.slice
            items = items[start:end]
        return items

    async def _run_all(
        self,
        items: list[str],
        expr: str,
        sem: asyncio.Semaphore,
        ctx: ExecutionContext,
        frame: Context,
    ) -> list[str]:
        # TaskGroup so the first failing row cancels its in-flight siblings.
        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(self._row(item, expr, sem, ctx, frame)) for item in items]
        except BaseExceptionGroup as group:
            reraise_first(group)
        return [task.result() for task in tasks]

    async def _row(
        self,
        item: str,
        expr: str,
        sem: asyncio.Semaphore,
        ctx: ExecutionContext,
        frame: Context,
    ) -> str:
        # WHY: the body is spawned verbatim (with $item still in it) and the row is
        # bound into scope, so arbitrary row data never enters the re-parse.
        # INVARIANT: the row shadows `frame` rather than merging into it — an enclosing binding
        # named `item` must never capture the row, which is why the row key is NUL-prefixed and
        # `_body_ref_edges` refuses to wire the reserved row names.
        scope = Context(bindings={_ITEM_KEY: item}, parent=frame)
        async with sem:
            return await ctx.spawn(expr, scope)

    def _skip(self, raw: list) -> list[str]:
        # skip omits failed elements (spec §5.3.6); control-flow signals
        # (CancelledError, KeyboardInterrupt — BaseException but not Exception)
        # are never a row outcome and must propagate.
        results: list[str] = []
        for item in raw:
            if isinstance(item, BaseException) and not isinstance(item, Exception):
                raise item
            if not isinstance(item, Exception):
                results.append(item)
        return results

    def _collect(self, raw: list, ctx: ExecutionContext) -> list[str]:
        results: list[str] = []
        for item in raw:
            # collect captures per-row *errors* as data; control-flow signals
            # propagate exactly as in _skip.
            if isinstance(item, BaseException) and not isinstance(item, Exception):
                raise item
            if isinstance(item, Exception):
                ctx.record_collected_error()
                results.append(json.dumps(_error_payload(item)))
            else:
                results.append(item)
        return results


@dataclass(eq=False)
class ReduceNode:
    """``(src*(body))!reducer`` — reduce all rows through the reducer template.

    The reducer is parsed lazily, here at resolve time: a relative-expression
    reducer (``/reduce(all)``) is fetched with the JSON row array as its intent
    (``/reduce?q=(all)!<array>``); any other reducer merges via ``ctx.process``
    with the *raw* reducer text.
    """

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
