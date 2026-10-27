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
from url4.dag.attachment_sources import AttachmentIdentity  # isort: skip
from url4.dag._materialize import Admission, Outcomes, Prefetched, check_caps, materialize  # isort: skip
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

    slots: tuple[Attachment | str | AttachmentIdentity, ...]
    cache: dict[str, CachedBlob | str] | None = None
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
    A nested ``run()`` resolves nothing: it inherits the outer list and cache verbatim.
    WHY ``https://`` TEXT sources are only slotted here, not fetched (owner decision Q-B,
    kept by round 7): they stay lazy, so they behave exactly as before (D5 exempt).
    """
    if current_run_files() is not None:
        return RunStart(tuple(case))
    ast = _ast_of(target)
    scan = scan_sources(ast) if ast is not None else None
    refs = () if scan is None else scan.refs
    refuse_remote(refs)
    occurrences = () if scan is None else scan.occurrences
    admission: Admission = await materialize(occurrences, run_ctx)
    bodies = await gather_or_cancel(_verify(ref, run_ctx) for ref in refs)
    resolved = {ref.key: _as_attachment(ref, *body) for ref, body in zip(refs, bodies, strict=True)}
    cache: dict[str, CachedBlob | str] = {
        ref.key: CachedBlob(*body) for ref, body in zip(refs, bodies, strict=True)
    }
    # F1b: an identity's slot is its first REACHABLE occurrence, known only after admission.
    order = (
        () if scan is None else reachable_order(scan.order, occurrences, admission.first_reachable)
    )
    slots = attachment_slots(case, resolved, order)
    start = RunStart(slots, cache, admission.outcomes, admission.prefetched)
    check_caps(RunFiles(start.slots, {}, {}, admission.outcomes).attachments)
    return start


async def _verify(ref: FileRef, run_ctx: ExecutionContext) -> tuple[bytes, str | None]:
    return await BlobRefNode(ref.address).verified(run_ctx)


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
