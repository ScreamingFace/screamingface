"""Run admission for ``https://`` attachment sources: reachability, one flight, caps.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F1b "Scope of
attachments", review round 7). STORY: as an ensemble author my ``;accept=image/png`` picture is
fetched once, before any model is called, and every model call in the run sees it.

INVARIANT (order of the phase, all before the first model call):
1. static check — an attachment source conditional on a model-derived collection is
   ``x.source_not_static`` before ANY fetch;
2. reachability — each non-model collection an occurrence is conditional on is resolved
   (once; execution replays the result, :meth:`RunFiles.take_prefetched`), outer first, and an
   occurrence under a collection with zero rows (after slicing) does no I/O;
3. one flight per identity — every reachable identity is fetched once as bytes under its own
   guard policy, concurrently; a required failure fails the run, an ``;optional`` one is omitted.
INVARIANT: an expression with no attachment source never enters this module (text sources are
byte-identical to today).

AIDEV-NOTE (conservative readings, ledger round 7): a collection this phase cannot resolve
without running the body (a row reference ``$item``, a blob ref, holdings, an annotated or
templated source) is treated as reachable; a pre-built graph has no AST, so it has no manifest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from url4.core.errors import CollectionError, ErrorCode, ResolutionError
from url4.core.nodes import (
    Expression,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    RemoteExpr,
    Source,
    Text,
    Url,
    VarRef,
)
from url4.io.layer import FetchRequest, FetchResult, fetch_result

from url4.dag.attachment import Attachment  # isort: skip
from url4.dag.attachment_sources import AttachmentIdentity, classify, not_static  # isort: skip
from url4.dag.attachments import CollectionGuard, Occurrence, prefetch_key  # isort: skip
from url4.dag.node import DagNode, ExecutionContext, Payload, SourceFailure, gather_or_cancel  # isort: skip
from url4.dag.nodes import GuardNode  # isort: skip
from url4.dag.semantics.collection import parse_collection  # isort: skip

MAX_ATTACHMENTS = 20
MAX_ATTACHMENT_BYTES = 8_000_000

_MODEL = "model"
_UNKNOWN = "unknown"

Outcomes = dict[AttachmentIdentity, Attachment | ResolutionError]
Prefetched = dict[tuple, list[FetchResult | Exception]]


async def materialize(
    occurrences: Sequence[Occurrence], ctx: ExecutionContext
) -> tuple[Outcomes, Prefetched]:
    """Every reachable identity's outcome, and the collection fetches made to decide it."""
    if not occurrences:
        return {}, {}
    for identity, guards in occurrences:
        if any(_kind(guard.items, guard.bound) == _MODEL for guard in guards):
            raise not_static(repr(identity.url))
    prefetched: Prefetched = {}
    rows: dict[int, bool] = {}
    reachable: dict[AttachmentIdentity, None] = {}
    for identity, guards in occurrences:
        if identity not in reachable and await _all_have_rows(guards, ctx, rows, prefetched):
            reachable[identity] = None
    flights = await gather_or_cancel(_flight(identity, ctx) for identity in reachable)
    return dict(zip(reachable, flights, strict=True)), prefetched


async def _all_have_rows(
    guards: Sequence[CollectionGuard],
    ctx: ExecutionContext,
    rows: dict[int, bool],
    prefetched: Prefetched,
) -> bool:
    # Outer first, stopping at the first empty one: an inner collection of a body over zero
    # rows is never resolved (a body over zero rows causes no I/O).
    for guard in guards:
        if id(guard) not in rows:
            rows[id(guard)] = await _has_rows(guard, ctx, prefetched)
        if not rows[id(guard)]:
            return False
    return True


def _unwrap(items: Node, bound: Mapping[str, Node]) -> Node:
    """Follow ``$xs`` to its enclosing binding's value, and a descriptor to its value.

    One step only: a binding whose value is itself a reference is ``unknown`` (reachable).
    """
    if isinstance(items, VarRef) and not items.path and items.name in bound:
        items = bound[items.name]
    while isinstance(items, Source):
        items = items.value
    return items


def _kind(items: Node, bound: Mapping[str, Node]) -> str:
    """``model`` when the collection is a model output, else ``unknown`` or a resolvable shape.

    WHY a call, a remote expression and a nested iteration are ``model``: their rows are a
    model's (or another node's) output, so the body's reachability is unknown until after a
    model call — an attachment source there cannot be frozen first (F1b ``x.source_not_static``).
    """
    items = _unwrap(items, bound)
    kind = _UNKNOWN
    if isinstance(items, Expression):
        kind = "inline" if items.intent is None and not items.broadcast else _MODEL
    elif isinstance(items, (RelExpr, RemoteExpr, Iteration)):
        kind = _MODEL
    elif isinstance(items, Url) and items.value.startswith(("http://", "https://")):
        kind = "fetch"
    elif isinstance(items, RelUrl) and "$" not in items.value:
        kind = "fetch"
    elif isinstance(items, Text):
        kind = "text"
    return kind


async def _has_rows(guard: CollectionGuard, ctx: ExecutionContext, prefetched: Prefetched) -> bool:
    items = _unwrap(guard.items, guard.bound)
    has_rows = True  # unknown before the body runs: conservatively reachable
    if isinstance(items, Expression) and _kind(items, {}) == "inline":
        has_rows = _sliced(list(items.sources), guard)
    elif isinstance(items, Text):
        has_rows = _parsed(items.value, None, guard)
    elif isinstance(items, (Url, RelUrl)) and _kind(items, {}) == "fetch":
        has_rows = await _fetched_rows(_collection_request(items), ctx, guard, prefetched)
    return has_rows


def _collection_request(items: Url | RelUrl) -> FetchRequest:
    # INVARIANT: the very request the lowered collection node sends, so execution's fetch
    # finds this one in the replay memo (see ``_lower_collection`` / ``WebFetchNode``).
    if isinstance(items, RelUrl):
        return FetchRequest(items.value, relative=True, kind="relative")
    return FetchRequest(items.value, relative=False, kind="http")


async def _fetched_rows(
    request: FetchRequest, ctx: ExecutionContext, guard: CollectionGuard, prefetched: Prefetched
) -> bool:
    pending = prefetched.setdefault(prefetch_key(request), [])
    try:
        result = await fetch_result(ctx.io, request)
    except Exception as exc:  # replayed by execution, which fails exactly as it does today
        pending.append(exc)
        return False
    pending.append(result)
    return _parsed(result.body, result.media_type, guard)


def _parsed(body: str, media_type: str | None, guard: CollectionGuard) -> bool:
    try:
        return _sliced(parse_collection(body, media_type), guard)
    except CollectionError:
        return False  # execution raises the same error; nothing in the body runs


def _sliced(items: list, guard: CollectionGuard) -> bool:
    if guard.slice is not None:
        start, end = guard.slice
        items = items[start:end]
    return bool(items)


async def _flight(
    identity: AttachmentIdentity, ctx: ExecutionContext
) -> Attachment | ResolutionError:
    """One binary-safe fetch of ``identity`` under its own guard policy (F1b one flight)."""
    leaf = _AttachmentFetchNode(identity)
    if not (identity.optional or identity.timeout is not None or identity.retries):
        await leaf.resolve({}, ctx)
    else:
        guard = GuardNode(
            leaf, optional=identity.optional, timeout=identity.timeout, retries=identity.retries
        )
        outcome = await guard.resolve({}, ctx)
        if isinstance(outcome, SourceFailure):
            ctx.log(
                "WARN",
                f"optional attachment source {identity.url!r} omitted",
                attributes={"code": outcome.code},
            )
            return ResolutionError(outcome.message, code=outcome.code, permanent=True)
    if leaf.fetched is None:  # resolve returns only after it stored the attachment
        raise RuntimeError(f"attachment flight for {identity.url!r} stored nothing")
    return leaf.fetched


@dataclass(eq=False)
class _AttachmentFetchNode:
    """The leaf a flight's guard runs: ``fetch_bytes`` through the run's io, then classify.

    WHY the attachment is stored on the node, not returned: a DAG payload is text (D2); the
    leaf returns the URL text, the same payload the source contributes at execution.
    """

    identity: AttachmentIdentity
    deps: Mapping[str, DagNode] = field(default_factory=dict)
    fetched: Attachment | None = None

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        identity = self.identity
        fetch = getattr(ctx.io, "fetch_bytes", None)
        if fetch is None:
            raise ResolutionError(
                f"attachment source {identity.url!r} needs a binary-safe adapter (fetch_bytes)",
                code=ErrorCode.UNSUPPORTED_CONTENT_TYPE,
                permanent=True,
            )
        request = FetchRequest(identity.url, relative=False, kind="http", accept=identity.accept)
        got = await fetch(request)
        media_type = classify(identity, got.media_type)
        body: bytes = got.body
        digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
        self.fetched = Attachment(digest, media_type, body)
        return identity.url


def check_caps(attachments: Sequence[Attachment]) -> None:
    """F1b per-run caps over the WHOLE list: 20 entries, 8,000,000 decoded bytes."""
    if len(attachments) > MAX_ATTACHMENTS:
        raise ResolutionError(
            f"the run has {len(attachments)} attachments; at most {MAX_ATTACHMENTS} are allowed",
            code=ErrorCode.ATTACHMENTS_TOO_MANY,
            permanent=True,
        )
    total = sum(len(attachment.body) for attachment in attachments)
    if total > MAX_ATTACHMENT_BYTES:
        raise ResolutionError(
            f"the run's attachments hold {total} bytes; at most {MAX_ATTACHMENT_BYTES} are allowed",
            code=ErrorCode.ATTACHMENTS_TOO_LARGE,
            permanent=True,
        )


__all__ = ["MAX_ATTACHMENTS", "MAX_ATTACHMENT_BYTES", "check_caps", "materialize"]
