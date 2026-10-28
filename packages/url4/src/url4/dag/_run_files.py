"""Run-start file resolution for :func:`url4.dag.run`: the run's fixed ``attachments[]``.

Split from :mod:`url4.dag._run` (module-size cap) by reason to change: this module changes
when file-ref resolution (spec F2 / D1 / D5) changes; ``_run`` changes when the public
``run()`` API grows. ``url4.dag._run`` re-exports every name here, so no import path moves.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from url4.core.errors import ParseError
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import Node as AstNode

from url4.dag.attachment import OCTET_STREAM, Attachment  # isort: skip
from url4.dag.attachment_sources import AttachmentIdentity, not_static  # isort: skip
from url4.dag._caps import CapBudget  # isort: skip
from url4.dag._materialize import Admission, Outcomes, Prefetched, check_caps, check_static  # isort: skip
from url4.dag._materialize import materialize  # isort: skip
from url4.dag.source_scan import reachable_order  # isort: skip
from url4.dag.attachments import (  # isort: skip
    CachedBlob,
    FileRef,
    RunFiles,
    attachment_slots,
    current_run_files,
    scan_sources,
    refuse_remote,
)
from url4.dag.compiler import Graph  # isort: skip
from url4.dag.node import DagNode, ExecutionContext, gather_or_cancel  # isort: skip
from url4.dag.nodes.blob import BlobRefNode  # isort: skip


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
    re-checks the final list. Order of refusals: ``x.remote_blob_unsupported``, then
    ``x.source_not_static`` (a non-literal attachment target, or one under a model-derived
    collection; both before any I/O), then the caps and fetch failures.
    A nested ``run()`` resolves nothing: it inherits the outer list and cache verbatim.
    WHY text sources are not touched here: they are never attached (owner decision A) and
    stay lazy, so they behave exactly as before (D5 exempt).
    """
    if current_run_files() is not None:
        return RunStart(tuple(case))
    ast = _ast_of(target)
    scan = scan_sources(ast) if ast is not None else None
    refs = () if scan is None else scan.refs
    refuse_remote(refs)
    if scan is not None and scan.non_literal:  # owner decision C: before any I/O
        raise not_static(repr(scan.non_literal[0]))
    occurrences = () if scan is None else scan.occurrences
    check_static(occurrences)
    budget = CapBudget(case)
    budget.expect(ref.key for ref in refs if not ref.collection)
    bodies = await gather_or_cancel(_verify(ref, run_ctx, budget) for ref in refs)
    admission: Admission = await materialize(occurrences, run_ctx, budget)
    resolved = {ref.key: _as_attachment(ref, *body) for ref, body in zip(refs, bodies, strict=True)}
    cache: dict[str, CachedBlob] = {
        ref.key: CachedBlob(*body) for ref, body in zip(refs, bodies, strict=True)
    }
    # F1b: an identity's slot is its first REACHABLE occurrence, known only after admission.
    order = (
        () if scan is None else reachable_order(scan.order, occurrences, admission.first_reachable)
    )
    slots = attachment_slots(case, resolved, order)
    start = RunStart(slots, cache, admission.outcomes, admission.prefetched)
    check_caps(RunFiles(start.slots, manifest=admission.outcomes).attachments)
    return start


async def _verify(
    ref: FileRef, run_ctx: ExecutionContext, budget: CapBudget
) -> tuple[bytes, str | None]:
    """One blob ref's verified bytes; an attached (non-collection) one is charged to the caps."""
    body, media_type = await BlobRefNode(ref.address).verified(run_ctx)
    if not ref.collection:
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
