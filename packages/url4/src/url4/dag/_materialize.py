"""Run admission for ``https://`` attachment sources: reachability, one flight, caps.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F1b "Scope of
attachments", review round 7). STORY: as an ensemble author my ``;accept=image/png`` picture is
fetched once, before any model is called, and every model call in the run sees it.

INVARIANT (order of the phase, all before the first model call):
1. static check — an attachment source conditional on a model-derived collection is
   ``x.source_not_static`` before ANY fetch;
2. reachability — each non-model collection an occurrence is conditional on is resolved
   (once, under its OWN descriptor guard policy — ``;retry=`` / ``;t=`` / ``;optional`` — "with
   its normal source semantics"; execution replays the final outcome,
   :meth:`RunFiles.take_prefetched`), outer first, and an occurrence under a collection with
   zero rows (after slicing), or whose collection failed, does no I/O;
3. caps — the reachable REQUIRED identities are counted against the entry cap before any flight
   (:class:`~url4.dag._caps.CapBudget`), and each flight's bytes as it lands, so a breach cancels
   the flights still in progress (owner decision E, 2026-10-27);
4. one flight per identity — every reachable identity is fetched once as bytes under its own
   guard policy, concurrently; a required failure fails the run, an ``;optional`` one is omitted.
INVARIANT: an expression with no attachment source never enters this module (text sources are
byte-identical to today).

AIDEV-NOTE (conservative readings, ledger round 7): a collection this phase cannot resolve
without running the body (a row reference ``$item``, holdings, a templated source, a bound inline
group) is treated as reachable. Every collection's shape comes from the ONE resolver
:mod:`url4.dag._collection_shape` (review finding 2): ``$name`` chains and field paths are followed
to their value, a model anywhere on the chain is ``x.source_not_static``, and a verified blob
collection is read from the run-start cache. A pre-built graph has no AST, so ``run()``
refuses one that names an attachment-capable source (review finding 3, fail closed). An annotated
``http(s)://`` or relative collection IS resolved here, under its own guard policy (review
round 7b). A collection whose guarded admission still fails is final: execution replays that
failure as permanent (never retried, never re-fetched), so the body it gates can never run
later and meet an attachment source missing from the manifest (``x.source_not_static``).
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial

from url4.core.blob_ref import address_of
from url4.core.errors import CollectionError, ErrorCode, ResolutionError, ScopeError, Url4Error
from url4.core.nodes import Expression, Node, RelUrl, Source, Url
from url4.core.url_display import display_url
from url4.io.layer import FetchRequest, FetchResult, fetch_result

from url4.dag.attachment import Attachment  # isort: skip
from url4.dag._caps import MAX_ATTACHMENT_BYTES as MAX_ATTACHMENT_BYTES  # isort: skip
from url4.dag._caps import MAX_ATTACHMENTS as MAX_ATTACHMENTS  # isort: skip
from url4.dag._caps import CapBudget  # isort: skip
from url4.dag._caps import check_caps as check_caps  # isort: skip
from url4.dag._caps import gather_charged  # isort: skip
from url4.dag.attachment_sources import AttachmentIdentity, classify, guard_policy, not_static  # isort: skip
from url4.dag._collection_shape import BLOB, FETCH, INLINE, MODEL, TEXT, CollectionShape  # isort: skip
from url4.dag._collection_shape import resolve_collection  # isort: skip
from url4.dag.attachments import CachedBlob, CollectionGuard, Occurrence, prefetch_key  # isort: skip
from url4.dag.node import RDS_STRICT, DagNode, ExecutionContext, Payload, SourceFailure  # isort: skip
from url4.dag.nodes import GuardNode  # isort: skip
from url4.dag.nodes.blob import collection_text  # isort: skip
from url4.dag.semantics.collection import parse_collection  # isort: skip
from url4.dag.semantics.ensemble import resolve_field_path  # isort: skip

Outcomes = dict[AttachmentIdentity, Attachment | ResolutionError]
Prefetched = dict[tuple, list[FetchResult | Exception]]


@dataclass(frozen=True)
class Admission:
    """The admission phase's result: outcomes, the replay memo, and slot positions.

    ``first_reachable`` holds, per reachable identity, the preorder index (into the scan's
    ``occurrences``) of its FIRST reachable occurrence — where F1b places its one slot.
    """

    outcomes: Outcomes = field(default_factory=dict)
    prefetched: Prefetched = field(default_factory=dict)
    first_reachable: frozenset[int] = frozenset()


def check_static(occurrences: Sequence[Occurrence]) -> None:
    """``x.source_not_static`` for an occurrence under a model-derived collection — no I/O.

    The shape comes from the ONE resolver (:func:`resolve_collection`, review finding 2), so a
    model reached through any chain of ``$name`` aliases or field paths is caught here.
    """
    for identity, guards in occurrences:
        if any(resolve_collection(g.items, g.bound).kind == MODEL for g in guards):
            raise not_static(identity.url)


async def materialize(
    occurrences: Sequence[Occurrence],
    ctx: ExecutionContext,
    budget: CapBudget,
    blobs: Mapping[str, CachedBlob] | None = None,
) -> Admission:
    """Every reachable identity's outcome, the collection fetches made to decide it, and
    the occurrence each identity's slot sits at. ``budget`` carries the caps the run already
    charged (Case attachments, blob refs); the flights charge it too. ``blobs`` is the run's
    verified blob cache: a blob collection's rows are read from it, never fetched again."""
    if not occurrences:
        return Admission()
    check_static(occurrences)
    prefetched: Prefetched = {}
    rows: dict[int, bool] = {}
    reachable: dict[AttachmentIdentity, int] = {}
    reader = _Rows(ctx, prefetched, blobs or {})
    # INVARIANT: preorder walk; an identity's later occurrences are never evaluated once an
    # earlier one is reachable (its slot is fixed, and no extra collection is fetched).
    for index, (identity, guards) in enumerate(occurrences):
        if identity not in reachable and await _all_have_rows(guards, reader, rows):
            reachable[identity] = index
    budget.expect(identity for identity in reachable if not identity.optional)
    flights = await gather_charged(
        budget, (_flight(identity, ctx, budget) for identity in reachable)
    )
    outcomes = dict(zip(reachable, flights, strict=True))
    return Admission(outcomes, prefetched, frozenset(reachable.values()))


async def _all_have_rows(
    guards: Sequence[CollectionGuard], reader: _Rows, rows: dict[int, bool]
) -> bool:
    # Outer first, stopping at the first empty one: an inner collection of a body over zero
    # rows is never resolved (a body over zero rows causes no I/O).
    for guard in guards:
        if id(guard) not in rows:
            rows[id(guard)] = await reader.has_rows(guard)
        if not rows[id(guard)]:
            return False
    return True


@dataclass(frozen=True)
class _Rows:
    """Decides whether a collection yields rows, reading it exactly as execution will."""

    ctx: ExecutionContext
    prefetched: Prefetched
    blobs: Mapping[str, CachedBlob]

    async def has_rows(self, guard: CollectionGuard) -> bool:
        shape = resolve_collection(guard.items, guard.bound)
        read = await self._read(shape)
        if shape.cycle:
            has = False  # a binding cycle: execution raises before any body runs (round 10)
        elif isinstance(read, _Reachable):
            has = True  # unknown before the body runs: conservatively reachable
        elif read is None:
            has = False  # the collection failed: execution fails or omits it; no body runs
        elif isinstance(read, list):
            has = _sliced(read, guard)
        else:
            has = _rows_of(read, shape, guard, self.ctx)
        return has

    async def _read(self, shape: CollectionShape) -> _Read:
        """The collection as execution will see it: elements, (body, media type), or neither."""
        value = shape.value
        read: _Read = _REACHABLE
        if shape.kind == INLINE and isinstance(value, Expression):
            read = list(value.sources)
        elif shape.kind == TEXT and shape.text is not None:
            read = (shape.text, None)
        elif shape.kind == FETCH and isinstance(value, (Url, RelUrl)):
            read = await _fetched_rows(value, shape.descriptor, self.ctx, self.prefetched)
        elif shape.kind == BLOB and (cached := _cached(value, self.blobs)) is not None:
            read = _blob_rows(cached)
        return read


class _Reachable:
    """A collection admission cannot read before the body runs: conservatively reachable."""


_REACHABLE = _Reachable()
_Read = _Reachable | list[Node] | tuple[str, str | None] | None


def _rows_of(
    read: tuple[str, str | None],
    shape: CollectionShape,
    guard: CollectionGuard,
    ctx: ExecutionContext,
) -> bool:
    body: str | None
    body, media_type = read
    if shape.via_ref:
        # A ``$name`` collection is a TextNode payload: each hop's path, no media type.
        body, media_type = _selected(body, shape.paths, ctx), None
    return body is not None and _parsed(body, media_type, guard)


def _selected(body: str, paths: Sequence[str], ctx: ExecutionContext) -> str | None:
    """``body`` read through each hop's field path as execution's substitution reads it.

    ``None`` when strict field mode refuses a path: execution raises there, so no body runs.
    """
    strict = ctx.strict_fields or RDS_STRICT.get()
    try:
        for path in paths:
            body = resolve_field_path(body, path, strict=strict, ref="$collection")
    except ScopeError:
        return None
    return body


def _cached(value: Node, blobs: Mapping[str, CachedBlob]) -> CachedBlob | None:
    """The run-start verified blob ``value`` names; ``None`` (unknown: reachable) otherwise."""
    address = address_of(value)
    return None if address is None else blobs.get(f"sha256:{address.digest}")


def _blob_rows(cached: CachedBlob) -> tuple[str, str | None] | None:
    """A verified blob collection's text and media type, read as execution reads it (D4)."""
    try:
        # WHY a fixed label: only whether the read is refused (C8) matters here, never the text.
        text = collection_text("blob collection", cached.body, cached.media_type)
    except ResolutionError:
        return None  # C8 at execution: the body never runs
    return str(text), cached.media_type


def _collection_request(items: Url | RelUrl, accept: str | None) -> FetchRequest:
    # INVARIANT: the very request the lowered collection node sends (``;accept=`` included,
    # ``_descriptor._push_label``), so execution's fetch finds this one in the replay memo.
    if isinstance(items, RelUrl):
        return FetchRequest(items.value, relative=True, kind="relative", accept=accept)
    return FetchRequest(items.value, relative=False, kind="http", accept=accept)


async def _fetched_rows(
    items: Url | RelUrl,
    descriptor: Source | None,
    ctx: ExecutionContext,
    prefetched: Prefetched,
) -> tuple[str, str | None] | None:
    """Resolve one collection under its own guard policy; record the FINAL outcome for replay.

    Returns the body and media type, or ``None`` when the collection failed or was omitted.
    WHY final, and a failure made permanent: admission already spent the source's policy
    (its retries and its ``;t=`` deadline). Execution's own guard must not spend it again —
    a fresh retry that succeeded there would run a body admission judged unreachable.
    """
    ann = {} if descriptor is None else dict(descriptor.annotations)
    request = _collection_request(items, ann.get("accept"))
    pending = prefetched.setdefault(prefetch_key(request), [])
    leaf = _CollectionFetchNode(request)
    policy = None if descriptor is None else guard_policy(ann, descriptor)
    try:
        if policy is None:
            await leaf.resolve({}, ctx)
        else:
            optional, timeout, retries = policy
            guarded = GuardNode(leaf, optional=optional, timeout=timeout, retries=retries)
            outcome = await guarded.resolve({}, ctx)
            if isinstance(outcome, SourceFailure):  # an omitted ;optional collection
                pending.append(ResolutionError(outcome.message, code=outcome.code, permanent=True))
                return None
    except Exception as exc:  # replayed by execution, which fails exactly as it does today
        pending.append(_final(exc))
        return None
    if leaf.result is None:  # resolve returns only after it stored the result
        shown = display_url(request.target)
        raise RuntimeError(f"collection admission for {shown!r} stored nothing")
    pending.append(leaf.result)
    return leaf.result.body, leaf.result.media_type


def _final(exc: Exception) -> Exception:
    """``exc`` as a terminal failure: a transient url4 error is copied as permanent."""
    if isinstance(exc, Url4Error) and not exc.permanent:
        exc = copy.copy(exc)
        exc.permanent = True
    return exc


@dataclass(eq=False)
class _CollectionFetchNode:
    """The leaf a collection's admission guard runs: one text fetch, result kept on the node.

    WHY stored, not returned: a DAG payload is text; the parse needs the media type too.
    """

    request: FetchRequest
    deps: Mapping[str, DagNode] = field(default_factory=dict)
    result: FetchResult | None = None

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        self.result = await fetch_result(ctx.io, self.request)
        return self.result.body


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
    identity: AttachmentIdentity, ctx: ExecutionContext, budget: CapBudget
) -> Attachment | ResolutionError:
    """One binary-safe fetch of ``identity`` under its own guard policy (F1b one flight).

    INVARIANT: the bytes are charged to ``budget`` OUTSIDE the guard — a cap breach is the
    run's refusal, never a source failure an ``;optional`` guard could swallow or retry. The
    live draw happens inside it (as bytes arrive), so a breach an ``;optional`` guard swallowed
    is re-raised here (:meth:`CapBudget.raise_if_refused`); permanent, so never retried.
    """
    leaf = _AttachmentFetchNode(identity, budget)
    if not (identity.optional or identity.timeout is not None or identity.retries):
        await leaf.resolve({}, ctx)
    else:
        guard = GuardNode(
            leaf, optional=identity.optional, timeout=identity.timeout, retries=identity.retries
        )
        outcome = await guard.resolve({}, ctx)
        if isinstance(outcome, SourceFailure):
            budget.raise_if_refused()
            ctx.log(
                "WARN",
                f"optional attachment source {display_url(identity.url)!r} omitted",
                attributes={"code": outcome.code},
            )
            return ResolutionError(outcome.message, code=outcome.code, permanent=True)
    if leaf.fetched is None:  # resolve returns only after it stored the attachment
        raise RuntimeError(f"attachment flight for {display_url(identity.url)!r} stored nothing")
    budget.charge(identity, len(leaf.fetched.body))
    return leaf.fetched


@dataclass(eq=False)
class _AttachmentFetchNode:
    """The leaf a flight's guard runs: ``fetch_bytes`` through the run's io, then classify.

    WHY the attachment is stored on the node, not returned: a DAG payload is text (D2); the
    leaf returns the URL text, the same payload the source contributes at execution.
    """

    identity: AttachmentIdentity
    budget: CapBudget
    deps: Mapping[str, DagNode] = field(default_factory=dict)
    fetched: Attachment | None = None

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        identity = self.identity
        fetch = getattr(ctx.io, "fetch_bytes", None)
        if fetch is None:
            # WHY unsupported_mode, not unsupported_content_type: the io lacks a capability (as
            # a code pointer on an io without SupportsCode does); no body's type was ever seen.
            raise ResolutionError(
                f"attachment source {display_url(identity.url)!r} needs a binary-safe io layer "
                "(fetch_bytes)",
                code=ErrorCode.UNSUPPORTED_MODE,
                permanent=True,
            )
        # WHY release first: a retried attempt reads its body again from the start.
        self.budget.release(identity)
        request = FetchRequest(
            identity.url,
            relative=False,
            kind="http",
            accept=identity.accept,
            max_bytes=self.budget.remaining(),
            on_chunk=partial(self.budget.charge_bytes, identity),
        )
        try:
            got = await fetch(request)
            media_type = classify(identity, got.media_type)
        except BaseException:
            # INVARIANT: a failed (or cancelled) attempt gives its live bytes back at once —
            # before a sibling flight draws again — so a failed source consumes no budget.
            self.budget.release(identity)
            raise
        body: bytes = got.body
        digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
        self.fetched = Attachment(digest, media_type, body)
        return identity.url


__all__ = [
    "MAX_ATTACHMENTS",
    "MAX_ATTACHMENT_BYTES",
    "Admission",
    "check_caps",
    "check_static",
    "materialize",
]
