"""Run-start file resolution for :func:`url4.dag.run`: the run's fixed ``attachments[]``.

Split from :mod:`url4.dag._run` (module-size cap) by reason to change: this module changes
when file-ref resolution (spec F2 / D1 / D5) changes; ``_run`` changes when the public
``run()`` API grows. ``url4.dag._run`` re-exports every name here, so no import path moves.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence

from url4.core.errors import ParseError
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import Node as AstNode

from url4.dag.attachment import OCTET_STREAM, Attachment  # isort: skip
from url4.dag.attachments import (  # isort: skip
    CachedBlob,
    FileRef,
    attachment_slots,
    current_run_files,
    scan_sources,
    refuse_remote,
)
from url4.dag.compiler import Graph  # isort: skip
from url4.dag.node import DagNode, ExecutionContext, gather_or_cancel  # isort: skip
from url4.dag.nodes.blob import BlobRefNode  # isort: skip


async def _run_files(
    target: str | AstNode | Graph | DagNode,
    case: Sequence[Attachment],
    run_ctx: ExecutionContext,
) -> tuple[tuple[Attachment | str, ...], dict[str, CachedBlob | str] | None]:
    """The run's fixed ``attachments[]`` and file cache, resolved BEFORE the first node runs.

    INVARIANT (F2 / D5): every file ref the AST names is fetched once (through the run's
    bounded io) and sha256-verified here; any failure — a ``;optional`` source included —
    fails the run before any model call. A ``url4://`` blob ref fails first, with no I/O (D1).
    A nested ``run()`` resolves nothing: it inherits the outer list and cache verbatim.
    WHY ``https://`` sources are only slotted here, not fetched (owner decision Q-B): they stay
    lazy, so a text body and a failed ``;optional`` source behave exactly as before (D5 exempt).
    """
    if current_run_files() is not None:
        return tuple(case), None
    ast = _ast_of(target)
    scan = scan_sources(ast) if ast is not None else None
    refs = () if scan is None else scan.refs
    refuse_remote(refs)
    bodies = await gather_or_cancel(_verify(ref, run_ctx) for ref in refs)
    resolved = {ref.key: _as_attachment(ref, *body) for ref, body in zip(refs, bodies, strict=True)}
    cache: dict[str, CachedBlob | str] = {
        ref.key: CachedBlob(*body) for ref, body in zip(refs, bodies, strict=True)
    }
    order = () if scan is None else scan.order
    return attachment_slots(case, resolved, order), cache


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


__all__ = ["_as_attachment", "_ast_of", "_run_files", "_verify"]
