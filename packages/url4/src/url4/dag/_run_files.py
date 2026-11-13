"""Run-start file resolution for :func:`url4.dag.run`: the run's fixed ``attachments[]``.

Split from :mod:`url4.dag._run` (module-size cap) by reason to change: this module changes
when file-ref resolution (spec F2 / D1 / D5) changes; ``_run`` changes when the public
``run()`` API grows. ``url4.dag._run`` re-exports every name here, so no import path moves.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial

from url4.core.errors import ParseError
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import Node as AstNode
from url4.core.parser import build

from url4.dag.attachment import OCTET_STREAM, Attachment  # isort: skip
from url4.dag.attachment_sources import AttachmentIdentity, not_static  # isort: skip
from url4.dag._caps import CapBudget, gather_charged  # isort: skip
from url4.dag._materialize import Admission, Outcomes, Prefetched, check_caps, check_static  # isort: skip
from url4.dag._materialize import materialize  # isort: skip
from url4.dag.source_scan import SourceScan, reachable_order, refuse_malformed  # isort: skip
from url4.dag.attachments import (  # isort: skip
    CachedBlob,
    FileRef,
    RunFiles,
    attachment_slots,
    current_run_files,
    scan_sources,
    refuse_remote,
)
from url4.dag.compiler import Graph, LoweringRegistry  # isort: skip
from url4.dag.node import DagNode, ExecutionContext  # isort: skip
from url4.dag.nodes.blob import BlobRefNode  # isort: skip
from url4.dag.remote_nodes import precheck_remote_nodes, remote_policy_active  # isort: skip
from url4.dag._static_processor import static_processor_value  # isort: skip
from url4.dag.processor import classify_processor, remote_processor_hop  # isort: skip
from url4.dag._graph_admission import prebuilt_remote_calls, refuse_prebuilt  # isort: skip


@dataclass(frozen=True)
class RunStart:
    """What :func:`url4.dag.run` binds: slots, cache, manifest outcomes, replay memo."""

    slots: tuple[Attachment | AttachmentIdentity, ...]
    cache: dict[str, CachedBlob] | None = None
    manifest: Outcomes = field(default_factory=dict)
    prefetched: Prefetched = field(default_factory=dict)


async def _run_start(
    target: str | AstNode | Graph | DagNode,
    case: Sequence[Attachment],
    run_ctx: ExecutionContext,
    registry: LoweringRegistry | None = None,
) -> RunStart:
    """The run's fixed ``attachments[]``, resolved and capped BEFORE the first node runs.

    INVARIANT (F2 / D5): every file ref the AST names is fetched once (through the run's
    bounded io) and sha256-verified here; any failure — a ``;optional`` source included —
    fails the run before any model call. A ``url4://`` blob ref fails first, with no I/O (D1).
    INVARIANT (F1b round 7): every reachable ``https://`` attachment source is materialized
    here too (:mod:`url4.dag._materialize`), then the whole list is capped and frozen.
    INVARIANT (owner decision E, 2026-10-27): ONE :class:`CapBudget` sees every adding path in
    order — Case attachments, then blob refs (counted before their I/O, bytes as verified),
    then attachment-source flights — so a breach stops the remaining I/O; :func:`check_caps`
    re-checks the final list. Order of refusals: ``malformed_source`` (an unparseable
    call-context segment beside an attachment opt-in), ``x.remote_blob_unsupported``,
    ``x.remote_node_unsupported`` (a node context; every run — text-only, nested and pre-built
    too), then
    ``x.source_not_static`` (a non-literal attachment target, or one under a model-derived
    collection; both before any I/O), then the caps and fetch failures.
    A nested ``run()`` resolves nothing: it inherits the outer list and cache verbatim (only
    its remote-call precheck runs).
    INVARIANT (PR #1587 review finding 3, owner 2026-11-04 — FAIL CLOSED): a pre-built
    ``Graph`` / ``DagNode`` has no AST to admit its files from, so one naming any
    attachment-capable source is refused first, with no I/O
    (:func:`~url4.dag._graph_admission.refuse_prebuilt`); a text-only graph runs as before.
    WHY text sources are not touched here: they are never attached (owner decision A) and
    stay lazy, so they behave exactly as before (D5 exempt).
    """
    _refuse_before_io(target, run_ctx.processor)
    ast = _ast_of(target)
    scan = scan_sources(ast) if ast is not None else None
    if current_run_files() is not None:
        # INVARIANT (PR #1587 review round 15, F1b): a nested run reuses the outer files but
        # still refuses its own structural remote calls before any of its members run.
        await _precheck_remote(scan, run_ctx, target, registry)
        return RunStart(tuple(case))
    refs = () if scan is None else scan.refs
    if scan is not None:
        refuse_malformed(scan)  # owner 2026-11-02: before any I/O, ahead of every refusal
    refuse_remote(refs)
    # INVARIANT (PR #1587 review round 14, F1b): EVERY run — text-only too — so no local
    # endpoint, model or sibling runs before a structurally known remote call refuses.
    await _precheck_remote(scan, run_ctx, target, registry)
    if scan is not None and scan.non_literal:  # owner decision C: before any I/O
        raise not_static(scan.non_literal[0])
    occurrences = () if scan is None else scan.occurrences
    check_static(occurrences)
    budget = CapBudget(case)
    budget.expect(ref.key for ref in refs if not ref.collection)
    bodies = await _verify_all(refs, case, run_ctx, budget)
    cache: dict[str, CachedBlob] = {
        ref.key: CachedBlob(*body) for ref, body in zip(refs, bodies, strict=True)
    }
    # WHY the cache goes in: a verified blob collection's rows decide reachability (finding 2).
    admission: Admission = await materialize(occurrences, run_ctx, budget, cache)
    resolved = {ref.key: _as_attachment(ref, *body) for ref, body in zip(refs, bodies, strict=True)}
    # F1b: an identity's slot is its first REACHABLE occurrence, known only after admission.
    order = (
        () if scan is None else reachable_order(scan.order, occurrences, admission.first_reachable)
    )
    slots = attachment_slots(case, resolved, order)
    start = RunStart(slots, cache, admission.outcomes, admission.prefetched)
    check_caps(RunFiles(start.slots, manifest=admission.outcomes).attachments)
    return start


def _refuse_before_io(target: str | AstNode | Graph | DagNode, processor: str | None) -> None:
    """The run-start refusals that need no scan of the run's own expression."""
    if isinstance(target, (Graph, DagNode)):
        refuse_prebuilt(target)  # finding 3 (owner 2026-11-04): fail closed, before any I/O
    _refuse_processor_files(processor)  # round 13: a Form-3 processor's files, before any I/O


async def _precheck_remote(
    scan: SourceScan | None,
    run_ctx: ExecutionContext,
    target: str | AstNode | Graph | DagNode,
    registry: LoweringRegistry | None,
) -> None:
    """C6 (finding 4): a node context refuses a remote-node call before ANY I/O — so before the
    attachment phase and before any member, not when the call executes. The run's literal
    ``url4://`` reduce processor (a run option or a node default) is the same remote-node call,
    checked here too (owner 2026-11-04). WHY every run (review round 14): a text-only run once
    executed a local endpoint before its remote sibling or remote processor refused.
    WHY the pre-built walk (review round 15): a ``Graph`` / ``DagNode`` has no AST (``scan`` is
    ``None``), so its ``RemoteFetchNode`` s and the remote calls in its kept text are collected
    from the graph itself; a precompiled mixed graph once ran a local endpoint first.
    """
    processor = await _processor_hop(run_ctx, registry)
    if scan is not None:
        calls = scan.remote_nodes
    elif isinstance(target, (Graph, DagNode)):
        calls = prebuilt_remote_calls(target)
    else:
        calls = ()  # unparseable text: compiling it raises the real error, with no I/O
    precheck_remote_nodes(
        (
            *calls,
            *_processor_expression_calls(run_ctx.processor),
        ),
        maybe=() if processor is None else (processor,),  # called only on a reduce
    )


async def _processor_hop(
    run_ctx: ExecutionContext, registry: LoweringRegistry | None
) -> tuple[str, str] | None:
    """The ``url4://`` call the run's reduce processor makes, when it is known before the run.

    A literal ``url4://`` URI, or (OME-1811 review) a Form-3 expression whose value needs no run
    (:func:`~url4.dag._static_processor.static_processor_value`, e.g.
    ``(p:0:'url4://n2/v1')!'$p'``). Any other Form-3 value is computed at reduce time and checked
    there (``processor._check_remote_processor``).
    WHY policy-gated: the static evaluation compiles the expression; outside a node context the
    precheck refuses nothing, so it is skipped.
    """
    value = run_ctx.processor
    if value is None or classify_processor(value) != "expression" or not remote_policy_active():
        return remote_processor_hop(value)
    return remote_processor_hop(await static_processor_value(value, registry, run_ctx.process))


def _processor_scan(value: str | None) -> SourceScan | None:
    """The structural scan of a Form-3 (expression-valued) processor; ``None`` for any other form.

    INVARIANT (PR #1587 review round 14, FAIL CLOSED): a Form-3 value that fails the grammar its
    resolve-time gate applies (:func:`~url4.core.parser.build`) raises that same permanent
    ``ParseError`` here, at run start; once it was left to reduce time, after members had run.
    """
    if value is None or classify_processor(value) != "expression":
        return None
    build(value)
    ast = _ast_of(value.strip())
    return None if ast is None else scan_sources(ast)


def _processor_expression_calls(value: str | None) -> tuple[tuple[str, str], ...]:
    """The structural ``url4://`` calls inside a Form-3 (expression-valued) processor.

    INVARIANT (PR #1587 review round 10, owner 2026-11-05): an expression processor is parsed
    and given the SAME structural remote-call scan as the run's own expression, so a remote call
    in its AST is refused before any run-start I/O; only its computed FINAL value stays checked
    when it resolves.
    """
    scan = _processor_scan(value)
    return () if scan is None else scan.remote_nodes


def _refuse_processor_files(value: str | None) -> None:
    """A Form-3 processor that names an attachment source or an attached blob ref is refused
    ``x.source_not_static`` at run start, before any I/O.

    INVARIANT (PR #1587 round 13, FAIL CLOSED): the processor's files are never admitted into the
    run's manifest. Without this the run paid for every member call and failed only when the
    processor resolved, or read its blob uncapped and attached nothing. A collection-only blob
    ref is not an attachment (D4) and is left to its lazy, verified read.
    """
    scan = _processor_scan(value)
    if scan is None:
        return
    files = (
        *scan.non_literal,
        *(identity.url for identity, _guards in scan.occurrences),
        *(ref.address.ref for ref in scan.refs if not ref.collection),
    )
    if files:
        raise not_static(files[0])


async def _verify_all(
    refs: Sequence[FileRef],
    case: Sequence[Attachment],
    run_ctx: ExecutionContext,
    budget: CapBudget,
) -> list[tuple[bytes, str | None]]:
    """Every blob ref's verified bytes, read concurrently; a Case digest reuses the Case bytes."""
    held = {attachment.digest: attachment for attachment in case}
    return await gather_charged(budget, (_verify(ref, run_ctx, budget, held) for ref in refs))


async def _verify(
    ref: FileRef,
    run_ctx: ExecutionContext,
    budget: CapBudget,
    held: Mapping[str, Attachment],
) -> tuple[bytes, str | None]:
    """One blob ref's verified bytes; an attached (non-collection) one is charged to the caps.

    INVARIANT (PR #1587 review finding 1, owner 2026-11-04): an attached blob read draws from
    the run's ONE live budget chunk by chunk (``on_chunk``), bounded by the bytes the settled
    entries leave (``max_bytes``) — exactly as an attachment-source flight does — so concurrent
    blob reads never hold more than about the cap plus one chunk each. A failed read gives its
    bytes back at once.
    A collection blob is not an attachment (D4) and is never charged.
    INVARIANT (review round 11, decision B, owner 2026-11-05): a held ``str`` draws its exact
    size first (``on_declared`` → :meth:`CapBudget.reserve`); any other whole-body read (a
    whole-body provider, a text-only io) reports ``None`` and is refused
    ``x.attachments_too_large`` unread.
    INVARIANT (review round 10 1(a), owner 2026-11-05): a ref whose digest is a verified Case
    attachment's (``held``) reuses those bytes and never reads the store copy — one resident copy,
    no I/O, nothing past the cap (the Case bytes are already counted).
    """
    case_file = held.get(ref.key)
    if case_file is not None:
        return case_file.body, case_file.media_type
    node = BlobRefNode(ref.address)
    if ref.collection:
        return await node.verified(run_ctx)
    budget.release(ref.key)
    try:
        body, media_type = await node.verified(
            run_ctx,
            max_bytes=budget.ceiling(ref.key),
            on_chunk=partial(budget.charge_bytes, ref.key),
            on_declared=partial(budget.reserve, ref.key),
        )
    except BaseException:
        budget.release(ref.key)
        raise
    budget.charge(ref.key, len(body))
    return body, media_type


def _as_attachment(ref: FileRef, body: bytes, media_type: str | None) -> Attachment:
    return Attachment(ref.key, media_type or OCTET_STREAM, body)


def _ast_of(target: str | AstNode | Graph | DagNode) -> AstNode | None:
    """The parse tree to collect file refs from; ``None`` for a pre-built graph or node.

    A text that does not parse yields ``None`` here: compiling it raises the real error.
    """
    ast: AstNode | None = None
    if isinstance(target, str):
        with contextlib.suppress(ParseError):
            ast = grammar_parse(target)
    elif not isinstance(target, (Graph, DagNode)):  # parse-tree nodes have no resolve
        ast = target
    return ast


__all__ = ["RunStart", "_as_attachment", "_ast_of", "_run_start", "_verify"]
