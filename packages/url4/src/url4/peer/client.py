"""The requestor facade — :class:`Client` and the :class:`Url4Result` envelope.

One execution path serves local and remote queries alike: helper methods build
an AST via :mod:`url4.core.builders`, a node target (when set) wraps it into a
:class:`~url4.core.nodes.RemoteExpr` — so the wire hop is just another DAG node —
the tree renders to canonical text, and :func:`url4.dag.run` executes it. The
rendered string is returned as :attr:`Url4Result.request`: the loggable,
shareable, re-runnable audit artifact the protocol is built around (spec §1.2).

Remote encodings (all reparse-verified by the renderer):
- ``query``     → ``(r=url4://node/path(ctx)!intent)!'$r'`` — the binding
  keeps the intent executing on the remote node (bare, the top-level ``!``
  split would hoist it to a local intent), and the all-binding group's ``$r``
  intent is pure interpolation, so no local processor is involved (`OME-508`:
  the old intent-less paren wrap has no grammar form).
- ``broadcast`` → the ``broadcast`` flag rides as a protocol param before
  ``q=``; the remote envelope decode folds it back into ``!*`` (§6.1.1).
- ``iterate(reduce=…)`` → the canonical reduce-over-iteration text
  ``q=(coll*(body)!'per row')!reducer`` (§5.3).

Known grammar limit: multi-valued params (``triggers=1,2``) cannot ride a
*nested* remote expression — a depth-0 comma would split the enclosing source
list — so they raise :class:`~url4.core.errors.RenderError` on remote queries;
local (top-level) queries carry them fine.

Deliberately absent: a module-level async ``query()`` — a global async client
binds an httpx pool to one event loop, a footgun in notebooks and servers.
Construct a :class:`Client` (ideally ``async with``) and own its lifecycle.
:func:`evaluate_sync` is the one module-level convenience, and it avoids the
footgun by owning a fresh client for exactly one call.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from url4.core.builders import ParamsLike, SourceLike, _pairs, _rewrite_reducer_iteration
from url4.core.builders import broadcast as _broadcast
from url4.core.builders import expr as _expr
from url4.core.builders import iterate as _iterate
from url4.core.builders import reduce as _reduce
from url4.core.context import Context
from url4.core.nodes import Expression, Iteration, Node, Params, RemoteExpr, Source, Text
from url4.core.parser import build
from url4.core.render import _render_source, render
from url4.dag import DEFAULT_RUN_CONCURRENCY, ExecutionContext, ProcessFn, default_process, run
from url4.io.layer import IOLayer
from url4.peer._owned import _OwnedIO


@dataclass(frozen=True)
class Url4Result:
    """A url4 evaluation outcome: the result body plus its request provenance.

    ``request`` is the exact canonical expression that ran — log it, share it,
    re-run it. Structured accessors decode the body on demand; the envelope
    fields of spec Part C (per-source attribution, budgets) land here once the
    executor reports them.
    """

    text: str
    request: str

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"Url4Result(request={_trunc(self.request)!r}, text={_trunc(self.text)!r})"

    def _repr_html_(self) -> str:
        import html

        return (
            '<div style="font-family: var(--jp-code-font-family, monospace)">'
            f'<div style="opacity:.6;font-size:85%">{html.escape(self.request)}</div>'
            f'<pre style="margin:.3em 0 0;white-space:pre-wrap">{html.escape(self.text)}</pre>'
            "</div>"
        )

    def json(self) -> Any:
        """The body decoded as JSON; raises ``ValueError`` for non-JSON bodies."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"result body is not JSON (request {self.request!r}): {self.text[:80]!r}"
            ) from exc

    @property
    def elements(self) -> list[Any]:
        """Per-element results of an iteration/broadcast (a JSON array body)."""
        data = self.json()
        if not isinstance(data, list):
            raise ValueError(
                f"result of {self.request!r} is not a JSON list (got {type(data).__name__}) — "
                "elements apply to iteration and broadcast results (spec §5.3.8, §6.1.4)"
            )
        return data


class Client:
    """The requestor-side entry point for evaluating url4 expressions.

    ``io`` is the outbound :class:`~url4.io.layer.IOLayer` — or, string-first,
    a node target: ``Client("url4://host/v1")`` is ``Client(node=...)`` with
    an owned httpx adapter. With ``io`` omitted, that adapter is created
    lazily and owned (closed by :meth:`aclose` / ``async with``). ``node``
    sets a default remote target (``"url4://host/path"`` / ``"host"``);
    without one, expressions evaluate locally against ``io``. ``processor``
    is the endpoint local intent execution dispatches to (spec: the node's
    intent processor) — unset, it resolves to the io world's first declared
    route (:class:`~url4.io.layer.SupportsDefaultRoute`); ``process_fn`` is
    the callable that executes it.
    """

    def __init__(
        self,
        io: IOLayer | str | None = None,
        *,
        node: str | None = None,
        path: str = "/v1",
        processor: str | None = None,
        process_fn: ProcessFn = default_process,
        concurrency: int | None = DEFAULT_RUN_CONCURRENCY,
        strict_fields: bool = False,
    ) -> None:
        if isinstance(io, str):
            if node is not None:
                raise ValueError("pass the node target once — positionally or as node=, not both")
            io, node = None, io
        self._owned = _OwnedIO(io)
        self._node = node
        self._path = path
        self._processor = processor
        self._process = process_fn
        self._concurrency = concurrency
        self._strict_fields = strict_fields

    # --- lifecycle -----------------------------------------------------------

    async def aclose(self) -> None:
        """Close the lazily-owned io adapter, if any (injected io is left alone)."""
        await self._owned.aclose()

    async def __aenter__(self) -> Client:
        await self._owned.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._owned.__aexit__(*exc_info)

    def _effective_io(self) -> IOLayer:
        return self._owned.outbound()

    # --- the query surface ------------------------------------------------------

    async def query(
        self,
        *sources: SourceLike,
        intent: str | Node | None = None,
        env: Mapping[str, object] | None = None,
        node: str | None = None,
        path: str | None = None,
        quorum: int | None = None,
        triggers: tuple[int, ...] | list[int] | None = None,
        t: float | int | None = None,
        fmt: str | None = None,
        params: ParamsLike = (),
    ) -> Url4Result:
        """``(sources)!intent`` — the core request; everything else is sugar."""
        proto = _proto_params(quorum, triggers, t, fmt, params)
        return await self.evaluate(
            _expr(*sources, intent=intent), env=env, node=node, path=path, params=proto
        )

    async def broadcast(
        self,
        *sources: SourceLike,
        intent: str | Node,
        env: Mapping[str, object] | None = None,
        node: str | None = None,
        path: str | None = None,
        params: ParamsLike = (),
    ) -> Url4Result:
        """``(sources)!*intent`` — apply the intent per source (§6.1)."""
        return await self.evaluate(
            _broadcast(*sources, intent=intent), env=env, node=node, path=path, params=params
        )

    async def iterate(
        self,
        collection: SourceLike | list[SourceLike] | tuple[SourceLike, ...],
        body: str | Node | list[SourceLike] | tuple[SourceLike, ...] = "",
        *,
        intent: str | Node | None = None,
        reduce: str | Node | None = None,
        env: Mapping[str, object] | None = None,
        node: str | None = None,
        path: str | None = None,
        concurrency: int | None = None,
        on_error: str | None = None,
        slice: tuple[int, int] | None = None,
        fmt_result: str | None = None,
    ) -> Url4Result:
        """``collection*(body)!intent`` — evaluate per element (§5.3)."""
        root = _iterate(
            collection,
            body,
            intent=intent,
            reduce=reduce,
            concurrency=concurrency,
            on_error=on_error,
            slice=slice,
            fmt_result=fmt_result,
        )
        return await self.evaluate(root, env=env, node=node, path=path)

    async def reduce(
        self,
        *calls: SourceLike,
        intent: str | Node,
        env: Mapping[str, object] | None = None,
        node: str | None = None,
        path: str | None = None,
        params: ParamsLike = (),
    ) -> Url4Result:
        """``(call1, call2, …)!intent`` — fan-out/reduce sugar (§2)."""
        return await self.evaluate(
            _reduce(*calls, intent=intent), env=env, node=node, path=path, params=params
        )

    async def evaluate(
        self,
        expression: str | Node,
        *,
        env: Mapping[str, object] | None = None,
        node: str | None = None,
        path: str | None = None,
        params: ParamsLike = (),
    ) -> Url4Result:
        """Evaluate url4 text or an AST — the front door every helper routes through.

        A node target (``node=`` here, or the client default) wraps the
        expression in a remote sub-request; otherwise it evaluates locally
        against ``io``. ``env`` seeds the lexical scope: ``$name`` references
        in the expression resolve against it. ``params`` are protocol params
        merged onto the expression.

        A tree passed as ``Node`` must come from
        :func:`~url4.core.parser.build` or the builder functions — a tree is
        rendered with the round-trip re-parse skipped (``check=False``, ~15x
        the render), so a hand-built tree is rendered *without* round-trip
        verification and may render to text that reparses differently near a
        grammar boundary (spec §8.1.2).
        """
        target = node or self._node
        proto = _pairs(params)
        # WHY check=False: every tree rendered here is parser- or
        # builder-produced (build() above or the builders) — the exact class
        # the renderer's round-trip property tests pin — and the verified
        # re-parse costs ~15x the render on this front-door path.
        if target is None and not proto:
            request = expression if isinstance(expression, str) else render(expression, check=False)
        else:
            root = _as_composite(build(expression) if isinstance(expression, str) else expression)
            if target is None:
                request = render(_with_params(root, proto), check=False)
            else:
                request = render(
                    _passthrough(_as_remote(root, target, path or self._path, proto)),
                    check=False,
                )
        ctx = ExecutionContext(
            self._effective_io(),
            processor=self._processor,
            process=self._process,
            scope=Context(bindings=dict(env)) if env else None,
            strict_fields=self._strict_fields,
        )
        text = await run(request, ctx=ctx, concurrency=self._concurrency)
        return Url4Result(text=text, request=request)


# --- the sync convenience ---------------------------------------------------------


def evaluate_sync(
    expression: str | Node,
    io: IOLayer | str | None = None,
    *,
    env: Mapping[str, object] | None = None,
    node: str | None = None,
    path: str = "/v1",
) -> Url4Result:
    """Evaluate one expression from synchronous code — scripts and REPLs.

    Owns a fresh :class:`Client` for exactly one call (created, run, closed),
    so no event-loop or lifecycle management leaks into the caller. Inside
    async code, construct a :class:`Client` and ``await`` it instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "evaluate_sync() cannot run inside an event loop — "
            "use 'await Client(...).evaluate(...)' there"
        )

    async def go() -> Url4Result:
        async with Client(io, node=node, path=path) as client:
            return await client.evaluate(expression, env=env)

    return asyncio.run(go())


# --- routing helpers -------------------------------------------------------------


def _trunc(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _as_composite(node: Node) -> Expression | Iteration:
    """Routing and params need the composite forms; shield anything else."""
    return node if isinstance(node, (Expression, Iteration)) else _expr(node)


def _proto_params(
    quorum: int | None,
    triggers: tuple[int, ...] | list[int] | None,
    t: float | int | None,
    fmt: str | None,
    extra: ParamsLike,
) -> Params:
    named = (
        ("quorum", quorum),
        ("triggers", None if triggers is None else ",".join(str(n) for n in triggers)),
        ("t", t),
        ("fmt", fmt),
    )
    return _pairs([(k, v) for k, v in named if v is not None]) + _pairs(extra)


def _with_params(root: Expression | Iteration, params: Params) -> Expression | Iteration:
    if not params:
        return root
    if isinstance(root, Iteration):
        # WHY: the iteration envelope has no params slot: "coll*(b)!i;quorum=2" would
        # silently DROP quorum on decode (IterationEnvelope keeps directives only).
        raise ValueError(
            "protocol params cannot ride a local iteration — the envelope decode "
            "drops them; wrap it in expr(...) or send it to a node"
        )
    return Expression(
        sources=root.sources,
        intent=root.intent,
        broadcast=root.broadcast,
        params=root.params + params,
    )


def _passthrough(node: RemoteExpr) -> Expression:
    """Wrap a lone remote call in the grammar's passthrough group.

    ``(r:0:<call>)!'$r'`` — the group's intent is mandatory (`OME-508`), and
    under the ABNF contribution semantics (`OME-534`) the weight-0.0
    INSTRUMENTAL descriptor is what keeps the wrapper out of the packed
    context AND out of the fan-out gate, so the wrapper adds no processor
    hop: the intent's ``$r`` interpolation IS the remote call's result.
    """
    return Expression(sources=(Source(node, name="r", weight=0.0),), intent=Text("$r"))


def _as_remote(
    root: Expression | Iteration, target: str, default_path: str, proto: Params
) -> RemoteExpr:
    """Wrap ``root`` as a remote expression addressed to ``target``.

    The remote node evaluates the full ``q=(context)!intent`` — sources resolve
    THERE (spec §5.6.3 pass-through), the intent dispatches to its processor.
    """
    authority, path = _split_target(target, default_path)
    if isinstance(root, Iteration):
        rewritten = _rewrite_reducer_iteration(root)
        # a reducer iteration becomes its (iteration)!reducer group; a plain
        # one becomes the group's single source
        root = rewritten if isinstance(rewritten, Expression) else _expr(rewritten)
    if root.broadcast:
        # !* has no slot in the canonical q=(ctx)!intent form; the broadcast
        # param is its spec-equivalent and folds back on the remote decode (§6.1.1).
        proto = proto + (("broadcast", None),)
    context = ", ".join(_render_source(s) for s in root.sources)
    return RemoteExpr(
        authority=authority,
        path=path,
        context=context or None,
        intent=root.intent,
        params=root.params + proto,
    )


def _split_target(target: str, default_path: str) -> tuple[str, str]:
    stripped = target.removeprefix("url4://").strip("/") or ""
    authority, sep, path = stripped.partition("/")
    if not authority:
        raise ValueError(f"invalid node target {target!r} — expected 'url4://host[/path]'")
    return authority, f"/{path}" if sep else default_path


__all__ = ["Client", "Url4Result", "evaluate_sync"]
