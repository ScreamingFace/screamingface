"""The value and fetch nodes: text, web/relative/remote fetches, holdings, structs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from url4.core._scan import skip_quoted, split_top_level
from url4.core.context import Context
from url4.core.ensemble import (
    substitute_env_vars,
)
from url4.core.errors import CollectionError, ErrorCode, ResolutionError
from url4.core.nodes import Params
from url4.core.subrequest import encode_subrequest
from url4.io.layer import FetchRequest, SupportsHoldings

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
)


from url4.dag.nodes._shared import (  # isort: skip
    SlotSpec,
    _as_text,
    _fetch,
    _frame,
    _gather,
    _substitute,
    _wire_params,
)


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
            code = (
                ErrorCode.SELF_REF_ON_NON_URL4
                if self.identity is None
                else ErrorCode.IDENTITY_REF_ON_NON_URL4
            )
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
            raise CollectionError(f"malformed struct field {fld!r}")
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
