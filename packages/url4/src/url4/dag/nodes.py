"""The built-in executable node vocabulary.

Each class here is one Strategy: the piece of url4 execution logic it owns,
behind the uniform :class:`~url4.dag.node.DagNode` interface. Nodes hold their
*template* data (raw text fragments, paths, directives) and perform their own
substitution / dispatch / dynamic compilation at ``resolve`` time — this is
where "the whole expression is not parsed upfront" lives: :class:`LazyExprNode`
compiles its fragment on demand, :class:`MapNode` re-compiles its body per
collection row, and :class:`ReduceNode` parses its reducer only when the rows
exist.

All I/O flows through ``ctx.io`` (the port); every ``$`` substitution
reuses the pure helpers in :mod:`url4.core.ensemble`. Reference-edge inputs use the
``bind:<name>`` / ``pos:<N>`` role convention — :func:`_frame` turns them into
a :class:`~url4.core.context.Context` frame chained onto ``ctx.scope``.

Terminal-state additions (spec Part A / §10): :class:`GuardNode` wraps a
source's subtree with the per-source execution disposition (``;optional``,
``;t=``, ``;retry=``) and converts a tolerated failure into a
:class:`~url4.dag.node.SourceFailure` *value*; :class:`ExpandNode` splices a
collection-valued source into N sibling values (§5.3.12); the group nodes
(:class:`GatherNode` / :class:`ProcessNode`) skip failures, flatten
expansions, and enforce ``quorum=N``.

Classes are ``@dataclass(eq=False)``: node identity is object identity, which
is what lets the executor memoize shared nodes (diamond dependencies) by
construction.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from url4.core._scan import skip_quoted, split_top_level
from url4.core.context import Context
from url4.core.ensemble import (
    FanoutResponse,
    build_reducer_input,
    substitute_env_vars,
    substitute_item,
    substitute_response_vars,
)
from url4.core.errors import CollectionError, ResolutionError, ScopeError, Url4Error
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import IterationDirectives, Params
from url4.core.nodes import RelExpr as AstRelExpr
from url4.core.parser import split_intent
from url4.core.subrequest import encode_subrequest, strip_transport_params
from url4.dag.processor import resolve_processor_target
from url4.io.layer import FetchRequest, SupportsHoldings, fetch_result, parse_collection

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
    reraise_first,
)


def _as_text(value: Payload) -> str:
    if isinstance(value, SourceFailure):
        return ""
    return value if isinstance(value, str) else "\n".join(value)


def _frame(inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Context:
    """Turn ``bind:``/``pos:`` reference-edge inputs into a scope frame.

    A :class:`SourceFailure` dependency contributes no binding — the failed
    optional source's ``$name`` stays unbound and substitutes verbatim.
    """
    bindings: dict[str, str] = {}
    for role, value in inputs.items():
        if isinstance(value, SourceFailure):
            continue
        if role.startswith("bind:"):
            bindings[role[5:]] = _as_text(value)
        elif role.startswith("pos:"):
            bindings[role[4:]] = _as_text(value)
    return Context(bindings=bindings, parent=ctx.scope) if bindings else ctx.scope


# WHY: the current collection row is bound into the spawned scope under this
# reserved key rather than substituted into the expression text — a row value carrying a
# stray "(" or "!" would otherwise desync the paren/intent scanners when the row
# expression is re-compiled. The NUL prefix keeps it out of the $name namespace.
_ITEM_KEY = "\x00item"

# WHY: the default per-MapNode fan-out cap when ``;iteration.concurrency`` is not
# given. Without a default bound, a collection with no directive spawns one
# concurrent sub-executor PER ROW (thousands, for a large collection) before any
# backpressure exists — an accidental-explosion hazard against whatever backend
# the rows' fetches hit. ``;iteration.concurrency=N`` overrides this; there is
# currently no "explicitly unbounded" escape hatch — name one if a real use case
# needs it.
DEFAULT_MAP_CONCURRENCY = 8


def _current_item(scope: Context) -> str | None:
    """The row bound by an enclosing :class:`MapNode`, or None outside a map."""
    try:
        return scope.lookup(_ITEM_KEY)
    except ScopeError:
        return None


def _substitute(text: str, scope: Context, ctx: ExecutionContext) -> str:
    """Resolve a leaf's ``$item`` (row) then ``$name``/``$N`` (scope) references.

    ``$item`` is applied first so its ``$$item`` escape still sees the raw
    template and so a row value is treated as opaque data, not re-scanned for
    ``$name``. Outside a map (no bound row) this is just
    :func:`substitute_env_vars`. ``ctx.strict_fields`` selects the spec
    §5.3.4.1 field-path error mode.
    """
    item = _current_item(scope)
    if item is not None:
        text = substitute_item(text, item, strict=ctx.strict_fields)
    return substitute_env_vars(text, scope, strict=ctx.strict_fields)


def _maybe_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _rows_to_json(rows: list[str]) -> str:
    """Serialize iteration rows as the protocol-default JSON array (spec §5.3.8).

    A visibly structured row (a JSON object or array — error objects, structured
    results) is embedded structurally; every other row, including scalar-looking
    text (``"1"``, ``"true"``), stays a JSON string — a row is prose unless it is
    visibly structured. Shared by :class:`CollectNode` and :class:`ReduceNode`
    so both consumers of a :class:`MapNode`'s rows type them identically.
    """
    return json.dumps([_maybe_json(r) if r[:1] in "[{" else r for r in rows])


class FetchedText(str):
    """A fetched body that also carries the adapter-reported media type.

    It *is* the body string — every ``str`` operation and ``isinstance(x, str)``
    check treats it as plain text — but a downstream :class:`MapNode` /
    :class:`ExpandNode` reads :attr:`media_type` to parse the collection by its
    declared Content-Type (spec §5.3.7) instead of sniffing. The media type is
    consulted only at the fetch→collection boundary, where the payload passes
    from the producer node to the consumer unchanged; any string transformation
    (``join``, slicing) yields a plain ``str`` that correctly falls back to
    sniffing, since it is no longer the adapter's own body.
    """

    media_type: str | None

    def __new__(cls, body: str, media_type: str | None) -> FetchedText:
        text = super().__new__(cls, body)
        text.media_type = media_type
        return text


async def _fetch(ctx: ExecutionContext, request: FetchRequest) -> FetchedText:
    """Resolve ``request`` through the port, preserving the media type (§5.3.7)."""
    result = await fetch_result(ctx.io, request)
    return FetchedText(result.body, result.media_type)


def _media_type_of(payload: Payload) -> str | None:
    """The Content-Type a fetch attached to ``payload``, or None when unknown."""
    return getattr(payload, "media_type", None)


def _error_payload(exc: BaseException) -> dict:
    """One collected row's wire error object (spec §5.3.6 ``collect``).

    Preserves the exception's URL4 diagnostics — ``code`` and ``permanent`` — beside the
    kind/message pair, so a ``collect``-boundary consumer (a benchmark's outcome envelope,
    the SDK report) can render the ORIGINAL upstream failure instead of falling back to a
    default code. ``permanent`` travels as ``retryable`` (its inverse): permanent errors
    must not be retried, and every reader of this payload already keys on retryability
    (``screamingface_engine.benchmarks.aggregation.public_error``).
    """
    payload: dict[str, object] = {
        "kind": type(exc).__name__,
        "message": str(exc) or repr(exc),
    }
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        payload["code"] = code
    permanent = getattr(exc, "permanent", None)
    if isinstance(permanent, bool):
        payload["retryable"] = not permanent
    return {"error": payload}


def _wire_params(params: Params) -> list[tuple[str, str]]:
    """Protocol params for the sub-request codec; a valueless flag emits ``k=``.

    # INVARIANT: transport-only params (spec §11.6.3) are stripped here, using
    # the codec's single definition — an expression authored with ``resume=``/
    # ``rid=`` must not smuggle them onto the next hop (`OME-501`).
    """
    pairs = [(key, value if value is not None else "") for key, value in params]
    return strip_transport_params(pairs)


@dataclass(eq=False)
class TextNode:
    """Inline text / a prompt template: pure ``$`` substitution.

    Quotes are delimiters at the grammar layer (spec §5.1), so the template
    arrives already unquoted — there is no quote handling here.
    """

    template: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return _substitute(self.template, _frame(inputs, ctx), ctx)


@dataclass(eq=False)
class WebFetchNode:
    """An absolute-URI fetch through the I/O layer port.

    The scheme classifies the request (spec §3.5): ``url4://`` targets expect
    URL4 protocol semantics from the adapter, ``http(s)://`` is a raw read,
    anything else (``s3://``, …) is adapter-defined. ``accept`` carries the
    per-source ``;accept=`` annotation.
    """

    url: str
    accept: str | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        request = FetchRequest(
            self.url, relative=False, kind=_kind_of(self.url), accept=self.accept
        )
        return await _fetch(ctx, request)


def _kind_of(url: str) -> Literal["http", "url4", "other"]:
    if url.startswith("url4://"):
        return "url4"
    if url.startswith(("http://", "https://")):
        return "http"
    return "other"


@dataclass(eq=False)
class RelUrlNode:
    """A relative ``/path`` reference resolved against the current node (localhost).

    Both shapes are a single fetch through the port:

    - a bare relative URI ``/api/x`` (``is_expr=False``) → ``fetch("/api/x")``,
      a plain data read;
    - a relative *expression* ``/claude(context)!intent`` (``is_expr=True``) →
      a fetch of the encoded sub-request ``/claude?[params&]q=(context)!intent``,
      which the local node evaluates. ``name`` / ``weight`` come from the
      enclosing :class:`~url4.core.nodes.Source` descriptor and let the ensemble
      reducer format and weight this source.
    """

    path: str
    context: str | None = None
    is_expr: bool = False
    name: str | None = None
    weight: float | None = None
    params: Params = ()
    accept: str | None = None
    ctx_slots: tuple[SlotSpec, ...] | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"intent": …, "ctx:i": …} + $refs

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        scope = _frame(inputs, ctx)
        # The path template may embed dot-path references (/api/$item, spec
        # §8.2.3 — bare-value embedding), so it substitutes like the context.
        path = _substitute(self.path, scope, ctx)
        if not self.is_expr:
            request = FetchRequest(path, relative=True, kind="relative", accept=self.accept)
            return await _fetch(ctx, request)
        context = _resolved_context(self.context, self.ctx_slots, inputs, scope, ctx)
        intent = (
            substitute_env_vars(_as_text(inputs["intent"]), scope, strict=ctx.strict_fields)
            if "intent" in inputs
            else None
        )
        target = encode_subrequest(path, context, intent, params=_wire_params(self.params))
        request = FetchRequest(target, relative=True, kind="relative", accept=self.accept)
        return await _fetch(ctx, request)


def _resolved_context(
    context: str | None,
    ctx_slots: tuple[SlotSpec, ...] | None,
    inputs: Mapping[str, Payload],
    scope: Context,
    ctx: ExecutionContext,
) -> str:
    """A call's dispatched context: packed source-list, or the raw-text fallback.

    ABNF conformance (`OME-535`): with ``ctx_slots`` the caller RESOLVED the
    paren source-list — pack it per the `OME-534` rules (named →
    ``name: value``, instrumental excluded). The packed text is opaque
    resolved data: it is NOT re-substituted (a ``$`` inside fetched content
    must stay literal). Without slots (prose, an unparseable list) the legacy
    raw-text path substitutes ``$item``/``$name`` templates as before.
    """
    if ctx_slots is None:
        return _substitute(context or "", scope, ctx)
    return "\n".join(_gather(inputs, ctx_slots, prefix="ctx").sources)


@dataclass(eq=False)
class RemoteFetchNode:
    """A remote expression ``url4://authority/path?[params&]q=(context)!intent``.

    The :class:`RelUrlNode` expression shape addressed to another node: the
    same canonical sub-request encoding, prefixed with the ``url4://`` scheme
    and authority so the adapter applies URL4 protocol semantics (spec §3.5 —
    the transport translation to ``https://`` is the adapter's concern).
    """

    authority: str
    path: str
    context: str | None = None
    params: Params = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"intent": …} + $refs

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        scope = _frame(inputs, ctx)
        # INVARIANT (`OME-535`): a remote call's q= carries an EXPRESSION the
        # REMOTE node evaluates (canonical form `?q=expression`) — the caller
        # never resolves it. Caller-side source-list resolution applies only
        # to RELATIVE calls, where the caller IS the evaluating node.
        context = _substitute(self.context or "", scope, ctx)
        intent = (
            substitute_env_vars(_as_text(inputs["intent"]), scope, strict=ctx.strict_fields)
            if "intent" in inputs
            else None
        )
        rel = encode_subrequest(self.path, context, intent, params=_wire_params(self.params))
        request = FetchRequest(f"url4://{self.authority}{rel}", relative=False, kind="url4")
        return await _fetch(ctx, request)


@dataclass(eq=False)
class HoldingsNode:
    """``@`` / ``@identity[/collection]`` — the holdings port (spec §5.6).

    Dispatches to the adapter's optional ``fetch_holdings`` capability. An
    adapter without it has no concept of policy-governed holdings — the spec's
    non-URL4 source case, a permanent error (§5.6.6).
    """

    identity: str | None = None
    collection: str | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        if not isinstance(ctx.io, SupportsHoldings):
            code = "self_ref_on_non_url4" if self.identity is None else "identity_ref_on_non_url4"
            ref = "@" if self.identity is None else f"@{self.identity}"
            raise ResolutionError(
                f"{ref} requires a URL4-aware adapter (no fetch_holdings port; spec §5.6.6)",
                code=code,
                permanent=True,
            )
        # A bare `@` carries no collection (spec §5.6.2: `self-ref = "@"`); the
        # run's path qualifier supplies it (§5.6.3.1). An identity-ref keeps its
        # own `@name/collection` — the qualifier scopes the NODE context, the
        # identity-collection scopes within the principal's holdings (§5.6.2).
        collection = self.collection
        if self.identity is None and collection is None:
            collection = ctx.self_collection
        return await ctx.io.fetch_holdings(self.identity, collection)


@dataclass(eq=False)
class StructNode:
    """An inline ``{key: value, …}`` structured object (spec §5.3.11.3).

    The raw balanced-brace text is decoded at resolve time — after ``$``
    substitution of its string values — and re-emitted as canonical JSON, so a
    downstream ``$name.field`` path or RDS consumer sees a real object.
    """

    raw: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        scope = _frame(inputs, ctx)
        return json.dumps(_decode_struct(self.raw, scope, ctx))


def _decode_struct(raw: str, scope: Context, ctx: ExecutionContext) -> dict:
    result: dict[str, object] = {}
    for fld in split_top_level(raw.strip()[1:-1], ","):
        key, sep, value = fld.partition(":")
        if not sep:
            raise CollectionError(f"malformed struct field {fld!r}", code="malformed_source")
        result[key.strip()] = _decode_struct_value(value.strip(), scope, ctx)
    return result


_NOT_SCALAR = object()


def _json_scalar(token: str) -> object:
    """A bare struct token's JSON scalar value (number/bool/null), or _NOT_SCALAR.

    Backs :class:`StructNode`'s "canonical JSON" guarantee (spec §5.3.11.3): a
    literal ``30`` becomes the number 30, ``true`` the boolean, ``null`` None.
    A bare word, a non-finite float, or anything else is not a scalar and stays
    a string.
    """
    try:
        parsed = json.loads(token)
    except (json.JSONDecodeError, ValueError):
        return _NOT_SCALAR
    # bool is an int subclass, so isinstance(_, int) covers true/false; a
    # non-finite float (NaN/Infinity) is not canonical JSON and stays a string.
    is_scalar = (
        parsed is None
        or isinstance(parsed, int)
        or (isinstance(parsed, float) and math.isfinite(parsed))
    )
    return parsed if is_scalar else _NOT_SCALAR


def _decode_struct_value(value: str, scope: Context, ctx: ExecutionContext) -> object:
    if value.startswith("{"):
        return _decode_struct(value, scope, ctx)
    quoted = False
    if value.startswith("'"):
        end = skip_quoted(value, 0)
        if end >= 2 and end == len(value):
            value = value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
            quoted = True
    # WHY: a bare literal keeps its JSON scalar type (canonical JSON); a quoted value
    # is always a string, and a value carrying a $reference stays the substituted
    # string so a resolved id like "007" is never silently renumbered to 7.
    if not quoted and "$" not in value:
        scalar = _json_scalar(value)
        if scalar is not _NOT_SCALAR:
            return scalar
    return _substitute(value, scope, ctx)


@dataclass(eq=False)
class BindingNode:
    """``name=value`` / ``name:value`` — a named passthrough other nodes edge to."""

    name: str
    kind: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"value": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return inputs["value"]


@dataclass(eq=False)
class LazyExprNode:
    """A Virtual Proxy over an unparsed url4 fragment.

    The fragment is compiled and executed only when this node resolves —
    the mechanism behind distributed / on-demand parsing. Reference-edge
    inputs become the scope frame the spawned sub-graph sees.
    """

    text: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return await ctx.spawn(self.text, _frame(inputs, ctx))


@dataclass(eq=False)
class GuardNode:
    """The per-source execution disposition (spec §10.1): retry, timeout, optional.

    ``inner`` is deliberately an *attribute*, not a dependency edge. A
    dependency's exception propagates through the run's shared TaskGroup and
    cancels every sibling before this node could catch it — so the guarded
    subtree executes via ``ctx.execute_node`` on an isolated sub-executor
    (its own TaskGroup), the same containment boundary ``spawn`` gives lazy
    fragments. The cost is a separate memo for the subtree; the compiler keeps
    shared bindings OUT of the subtree (they flow in as this node's reference
    edges → scope frame), so diamond deps still resolve exactly once.

    Failure handling: a permanent error (``Url4Error.permanent``) never
    retries; a transient one retries up to ``retries`` extra attempts; a
    timeout (``;t=``) is transient. A source that still fails is terminal —
    ``required`` (default) raises, ``optional`` returns a
    :class:`~url4.dag.node.SourceFailure` value for the group to tolerate.
    """

    inner: DagNode
    optional: bool = False
    timeout: float | None = None
    retries: int = 0
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # $ref edges only

    def children(self) -> list[DagNode]:
        """``inner`` is an attribute, not an edge — declare it so the structural
        traversals (cycle detection, :meth:`Graph.walk`) still see through the
        isolation boundary. See :func:`~url4.dag.node.node_children`."""
        return [*self.deps.values(), self.inner]

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        scope = _frame(inputs, ctx)
        try:
            return await self._attempt(scope, ctx)
        except Exception as exc:  # control-flow signals (CancelledError) propagate
            if not self.optional:
                raise
            code = exc.code if isinstance(exc, Url4Error) else "resolution_failed"
            return SourceFailure(code, str(exc) or type(exc).__name__)

    async def _attempt(self, scope: Context, ctx: ExecutionContext) -> Payload:
        last: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return await self._once(scope, ctx)
            except Url4Error as exc:
                if exc.permanent:
                    raise
                last = exc
        assert last is not None  # the loop always runs at least once
        raise last

    async def _once(self, scope: Context, ctx: ExecutionContext) -> Payload:
        if self.timeout is None:
            return await ctx.execute_node(self.inner, scope)
        try:
            async with asyncio.timeout(self.timeout):
                return await ctx.execute_node(self.inner, scope)
        except TimeoutError as exc:
            raise ResolutionError(
                f"source timed out after {self.timeout:g}s (;t=)", code="timeout"
            ) from exc


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
                f"expansion source is not iterable: {exc}", code="expansion_not_iterable"
            ) from exc


@dataclass(eq=False)
class BarrierNode:
    """Pass ``inner`` through after every ``wait:*`` dependency has resolved.

    Used to make a non-substituting intent (a URL fetch) structurally depend
    on all sources, preserving the reference engine's sources-then-intent
    resolution order.
    """

    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"inner": …, "wait:i": …}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return inputs["inner"]


SlotSpec = tuple[str | None, bool]
"""One group slot: ``(name, instrumental)``. ABNF conformance (`OME-534`):
EVERY listed source contributes to the packed context — name-only descriptors
(``a: v`` / ``a=v``) included. The bool marks a scalar-``weight 0.0``
INSTRUMENTAL source: resolved and ``$name``-referenceable, excluded from the
packed sources (the replacement for the old reference-only-Binding concept)."""


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


def _check_quorum(g: _Gathered, quorum: int | None) -> None:
    # The contributing count IS len(sources) — every append above is a contribution.
    resolved = len(g.sources)
    if quorum is not None and resolved < quorum:
        raise ResolutionError(
            f"quorum not met: {resolved} of {quorum} required sources resolved",
            code="quorum_not_met",
        )


@dataclass(eq=False)
class GatherNode:
    """An intent-less group — join the contributing sources (`OME-534`).

    AST-only (`OME-508`): the surface grammar's expression always carries an
    intent, so this node is reached via hand-built ``Expression(intent=None)``
    trees and the engine's own internal wrappers, never from user text.
    A pure-instrumental group falls back to joining every slot value.
    ``quorum`` (spec §9.1) gates on the post-expansion resolved-source count.
    """

    slots: tuple[SlotSpec, ...] = ()
    quorum: int | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        g = _gather(inputs, self.slots)
        _check_quorum(g, self.quorum)
        return "\n".join(g.sources) or "\n".join(g.positional)


@dataclass(eq=False)
class InlineCollectionNode:
    """An inline parenthesized collection ``(e1, e2, …)`` feeding ``*`` (§5.3.11).

    Each authored element (a scalar, URI, sub-expression, or ``{}`` structured
    object) is ONE collection element. Unlike :class:`GatherNode` — which
    newline-joins a bare group into a single text blob for the §5.3.7
    content-sniffer — this preserves the elements as a real ordered ``list[str]``
    payload, which the enclosing :class:`MapNode` consumes directly *without*
    routing back through body sniffing. That distinction is what makes a
    one-element inline collection iterable at all: a lone scalar joined-to-text
    is a single line the sniffer rejects as a non-iterable scalar (§5.3.9), and a
    lone ``{}`` element is rejected as a JSON object (§5.3.7) — both are
    structurally impossible to represent as one collection element through the
    text path. Elements keep their serialized shape (a scalar stays scalar text;
    a ``{}`` element stays canonical JSON, so a per-row ``$item.field`` path
    resolves). A ``;expand`` element still splices into consecutive positions
    (§5.3.12); a failed ``;optional`` element contributes no element.
    """

    slots: tuple[SlotSpec, ...] = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        # Every comma-entry's value, in order, post-expansion and post-failure —
        # the authored element list, NOT a joined blob (contrast GatherNode).
        return _gather(inputs, self.slots).positional


@dataclass(eq=False)
class ProcessNode:
    """The ``(sources)!intent`` base case — merge via the ``ctx.process`` hook.

    The scope handed to ``process`` is populated with every slot value (by
    ``$N`` position — renumbered after expansion, §5.3.12.4 — and by name for
    bindings and named sources), mirroring the reference engine's
    fully-resolved list context.

    A *text* intent arrives as ``intent_template`` and substitutes HERE,
    against the populated post-gather scope — this is what keeps ``$N``
    references correct after expansion renumbers the positions (a
    pre-substituted intent node would only ever see pre-expansion slots). A
    *fetch* intent stays an ``intent`` dependency behind the barrier.
    """

    slots: tuple[SlotSpec, ...] = ()
    quorum: int | None = None
    intent_template: str | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": …, ["intent": …]}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        g = _gather(inputs, self.slots)
        _check_quorum(g, self.quorum)
        bindings = {str(i + 1): value for i, value in enumerate(g.positional)}
        bindings.update(g.named)
        scope = Context(bindings=bindings, parent=ctx.scope)
        if self.intent_template is not None:
            intent = _substitute(self.intent_template, scope, ctx)
        else:
            intent = _as_text(inputs["intent"])
        return await ctx.process("\n".join(g.sources), intent, scope)


@dataclass(eq=False)
class MergeNode:
    """One broadcast application (spec §6.1.2): merge a single source with the intent.

    ``$current`` is bound to this source's resolved data in the scope handed to
    ``process``. A *text* intent arrives as ``intent_template`` and is
    substituted here — once per source, with ``current`` in scope — rather than
    as a shared pre-substituted node; a *fetch* intent stays a shared ``intent``
    dependency (resolved exactly once) and carries no ``$current``.
    """

    intent_template: str | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"source": …, ["intent": …]}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        source = _as_text(inputs["source"])
        scope = Context(bindings={"current": source}, parent=ctx.scope)
        if self.intent_template is not None:
            # WHY: _substitute (not bare substitute_env_vars) so a broadcast intent
            # nested inside an iteration resolves $item too, exactly as the
            # non-broadcast ProcessNode path does — $current still resolves via
            # the substitute_env_vars pass _substitute ends with.
            intent = _substitute(self.intent_template, scope, ctx)
        else:
            intent = _as_text(inputs["intent"]) if "intent" in inputs else ""
        return await ctx.process(source, intent, scope)


@dataclass(eq=False)
class BroadcastCollectNode:
    """Assemble per-source broadcast results into the §6.1.4 collection shape.

    A JSON array of ``{"source_position", "source_name", "result"}`` objects,
    ordered by source position (1-based). A failed optional source's part is
    omitted — broadcast applies across *resolved* sources (§6.1.3) — while the
    surviving parts keep their original positions.
    """

    names: tuple[str | None, ...] = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"part:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        rows = [
            {
                "source_position": i + 1,
                "source_name": self.names[i] if i < len(self.names) else None,
                "result": _as_text(inputs[role]),
            }
            for i, role in enumerate(self.deps)
            if not isinstance(inputs[role], SourceFailure)
        ]
        return json.dumps(rows)


@dataclass(eq=False)
class JoinNode:
    """Join ordered parts with a separator; flattens ``list[str]`` payloads."""

    sep: str = "\n"
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"part:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        parts: list[str] = []
        for role in self.deps:
            value = inputs[role]
            if isinstance(value, SourceFailure):
                continue
            parts.extend(value) if isinstance(value, list) else parts.append(value)
        return self.sep.join(parts)


@dataclass(eq=False)
class CollectNode:
    """Serialize iteration rows as the protocol-default JSON array (spec §5.3.8).

    A row that is itself a JSON *container* (an object or array — error
    objects, structured results) is embedded structurally; every other row is
    a JSON string. Scalar-looking text (``"1"``, ``"true"``) stays a string —
    a row is prose unless it is visibly structured. Row order is element order
    — the Map contract already preserves it.
    """

    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"rows": MapNode}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        rows = inputs["rows"]
        rows = rows if isinstance(rows, list) else [_as_text(rows)]
        return _rows_to_json(rows)


@dataclass(eq=False)
class FanoutReduceNode:
    """Fan-out + reduce: label the parallel relative-expression responses, reduce.

    The N sources (each a relative expression, ``call:i``) resolve in parallel;
    ``meta[i]`` carries the i-th one's ``(name, weight)`` label. The formatted
    reducer input (:func:`~url4.core.ensemble.build_reducer_input`) is then fetched
    from the configured ``ctx.processor`` route as ``processor?q=()!<input>`` —
    the reduce step is itself a localhost fetch. A failed optional call is
    excluded from the reducer input (it is not a resolved response).
    """

    meta: tuple[tuple[str | None, float | None], ...] = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"intent": …, "call:i": …}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        entries = [
            FanoutResponse(text=_as_text(inputs[f"call:{i}"]), name=name, weight=weight)
            for i, (name, weight) in enumerate(self.meta)
            if not isinstance(inputs[f"call:{i}"], SourceFailure)
        ]
        instruction = substitute_response_vars(_as_text(inputs.get("intent", "")), entries)
        # ABNF conformance (`OME-534`): a scalar weight 0.0 marks the call
        # INSTRUMENTAL — its response is $name-substitutable above but forms no
        # labeled section of the reducer input.
        contributing = [e for e in entries if e.weight != 0.0]
        reducer_input = build_reducer_input(contributing, instruction)
        if ctx.processor is None:
            # INVARIANT: the core hardcodes no processor route — with nothing
            # declared (SupportsDefaultRoute) and nothing passed, the reduce
            # cannot dispatch; fail with the fix in the message.
            raise ResolutionError(
                "fan-out reduce has no processor route — the io layer declares no "
                "routes and none was set; pass processor= (run/Client) or register "
                "a route/endpoint on the node"
            )
        # §27.3: the processor may be an id, a URI, a route path, or an
        # expression that computes one — url4.dag.processor owns that classification.
        scope = _frame(inputs, ctx)
        base, relative = await resolve_processor_target(
            ctx.processor, io=ctx.io, spawn=lambda text: ctx.spawn(text, scope)
        )
        target = encode_subrequest(base, "", reducer_input)
        return await ctx.io.fetch(target, relative=relative)


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


__all__ = [
    "DEFAULT_MAP_CONCURRENCY",
    "BarrierNode",
    "BindingNode",
    "BroadcastCollectNode",
    "CollectNode",
    "ExpandNode",
    "FanoutReduceNode",
    "GatherNode",
    "GuardNode",
    "HoldingsNode",
    "InlineCollectionNode",
    "JoinNode",
    "LazyExprNode",
    "MapNode",
    "MergeNode",
    "ProcessNode",
    "ReduceNode",
    "RelUrlNode",
    "RemoteFetchNode",
    "SlotSpec",
    "StructNode",
    "TextNode",
    "WebFetchNode",
]
