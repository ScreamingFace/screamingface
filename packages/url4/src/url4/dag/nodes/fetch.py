"""The value and fetch nodes: text, web/relative/remote fetches, holdings, structs.

The struct node lives in :mod:`url4.dag.nodes.struct` (module-size cap) and is re-exported
here, so ``url4.dag.nodes.fetch.StructNode`` keeps working.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from url4.core.context import Context
from url4.core.errors import ErrorCode, ResolutionError
from url4.core.nodes import Params
from url4.io.layer import FetchRequest, SupportsHoldings
from url4.wire.subrequest import encode_subrequest

from url4.dag.remote_nodes import check_remote_node  # isort: skip
from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
)


from url4.dag.nodes.web_attach import attach_web_body, cached_web_attachment  # isort: skip
from url4.dag.nodes._shared import (  # isort: skip
    SlotSpec,
    _as_text,
    _fetch,
    _frame,
    _gather,
    _substitute,
    _wire_params,
)

# WHY: redundant aliases re-export the struct node and its private helpers from their
# own module, so every ``url4.dag.nodes.fetch.<name>`` import path keeps working.
from url4.dag.nodes.struct import _NOT_SCALAR as _NOT_SCALAR  # isort: skip
from url4.dag.nodes.struct import StructNode as StructNode  # isort: skip
from url4.dag.nodes.struct import _decode_struct as _decode_struct  # isort: skip
from url4.dag.nodes.struct import _decode_struct_value as _decode_struct_value  # isort: skip
from url4.dag.nodes.struct import _json_scalar as _json_scalar  # isort: skip


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

    FEATURE: image and PDF inputs (``OME-1543`` U3b, spec F1b, owner decision Q-B). Inside a
    ``run()``, an ``http(s)://`` source in scalar position whose body is not text is fetched
    as bytes, attached to the run (:func:`~url4.dag.nodes.web_attach.attach_web_body`) and
    read as its URL text. ``collection`` is set at lowering (D4): a collection is parsed from
    text, so there a non-text body stays ``unsupported_content_type`` (C8).
    """

    url: str
    accept: str | None = None
    collection: bool = False
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        kind = _kind_of(self.url)
        attachable = kind == "http" and not self.collection
        if attachable and cached_web_attachment(self.url):
            return str(self.url)
        request = FetchRequest(self.url, relative=False, kind=kind, accept=self.accept)
        try:
            return await _fetch(ctx, request)
        except ResolutionError as exc:
            # INVARIANT (Q-B): only a body the text path refused as not-text changes route;
            # a text body, and every other failure (the x.source_* guard codes included),
            # is exactly what it was.
            if not attachable or exc.code != ErrorCode.UNSUPPORTED_CONTENT_TYPE:
                raise
            await attach_web_body(ctx, request, exc)
            return str(self.url)


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
    verbatim_intent: bool = False  # a code pointer or named job: never quoted (C9)
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
        # The intent dep's output is final: a TextNode already substituted it once, and a
        # fetched or nested result is data, never interpolated (B §8.2.1; audit A4).
        intent = _as_text(inputs["intent"]) if "intent" in inputs else None
        quote = not self.verbatim_intent
        params = _wire_params(self.params)
        target = encode_subrequest(path, context, intent, params=params, quote=quote)
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
    verbatim_intent: bool = False  # a code pointer or named job: never quoted (C9)
    accept: str | None = None  # the source's ;accept= annotation, sent as the Accept header
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"intent": …} + $refs

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        check_remote_node(self.authority, self.path)  # F1b / C6: refused in a node context
        scope = _frame(inputs, ctx)
        # INVARIANT (`OME-535`): a remote call's q= carries an EXPRESSION the
        # REMOTE node evaluates (canonical form `?q=expression`) — the caller
        # never resolves it. Caller-side source-list resolution applies only
        # to RELATIVE calls, where the caller IS the evaluating node.
        context = _substitute(self.context or "", scope, ctx)
        # The intent dep's output is final: a TextNode already substituted it once, and a
        # fetched or nested result is data, never interpolated (B §8.2.1; audit A4).
        intent = _as_text(inputs["intent"]) if "intent" in inputs else None
        quote = not self.verbatim_intent
        params = _wire_params(self.params)
        rel = encode_subrequest(self.path, context, intent, params=params, quote=quote)
        target = f"url4://{self.authority}{rel}"
        request = FetchRequest(target, relative=False, kind="url4", accept=self.accept)
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
