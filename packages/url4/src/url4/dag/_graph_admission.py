"""``run(Graph | DagNode)`` fails closed on any attachment-capable source, before any I/O.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 3,
owner decision Sergey 2026-11-04: FAIL CLOSED).
STORY: as an engine caller passing a pre-built graph, a graph that names a file or picture is
refused with a clear permanent error and zero fetches — instead of running with the files silently
missing (``attachments=()``) or a malformed opt-in context shipped raw to the route.

INVARIANT: a pre-built graph has no source AST, so admission cannot build its frozen manifest
(:mod:`url4.dag._run_files`). Any attachment-capable source anywhere in it is refused: an attachment
opt-in (``WebFetchNode.attachment``), a blob ref (``BlobRefNode``, a ``url4://`` one as
``x.remote_blob_unsupported``), a non-literal attachment target (``NotStaticNode``), and — in raw
text a node keeps for later (a verbatim call context, an iteration body, a lazy group) — whatever
the run-start scan would admit or refuse. Everything else is ``malformed_source``, permanent —
except an attachment opt-in or a non-literal target, which keep the ``x.source_not_static`` a pre-
built graph's attachment source already failed with (pinned since round 7), now before any I/O. A
text-only graph is untouched.
AIDEV-NOTE: the text forms are scanned with the very scan ``run(text)`` uses
(:mod:`url4.dag.source_scan`), so the two entry points cannot disagree on what counts.
"""

from __future__ import annotations

from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import RelExpr
from url4.core.url_display import display_url

from url4.dag.attachment_sources import not_static  # isort: skip
from url4.dag.compiler import Graph  # isort: skip
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import LazyExprNode, MapNode, RelUrlNode, RemoteFetchNode  # isort: skip
from url4.dag.nodes import WebFetchNode  # isort: skip
from url4.dag.nodes.blob import BlobRefNode  # isort: skip
from url4.dag.nodes.web_attach import NotStaticNode  # isort: skip
from url4.dag.source_scan import FileRef, SourceScan, holds_holdings_ref  # isort: skip
from url4.dag.source_scan import refuse_malformed, refuse_remote, scan_source_list  # isort: skip
from url4.dag.source_scan import scan_sources  # isort: skip


def refuse_prebuilt(target: Graph | DagNode) -> None:
    """Raise, with no I/O, when the pre-built ``target`` names any attachment-capable source."""
    graph = target if isinstance(target, Graph) else Graph(target)
    for node in graph.walk():
        _refuse_node(node)


def prebuilt_remote_calls(target: Graph | DagNode) -> tuple[tuple[str, str], ...]:
    """Every ``(authority, path)`` remote-node call the pre-built ``target`` makes structurally.

    FEATURE: PR #1587 review round 15 (F1b) — the run-start remote precheck's input for a target
    with no AST. INVARIANT: the same calls ``run(text)``'s scan records — each ``RemoteFetchNode``
    reachable through ``node_children`` (``Graph.walk``), plus those in text a node keeps for
    later — and none inside a remote context (that text runs at the remote node).
    """
    graph = target if isinstance(target, Graph) else Graph(target)
    calls: list[tuple[str, str]] = []
    for node in graph.walk():
        if isinstance(node, RemoteFetchNode):
            calls.append((node.authority, node.path))
        scan = _text_scan(node)
        if scan is not None:
            calls.extend(scan.remote_nodes)
    return tuple(calls)


def _refuse_node(node: DagNode) -> None:
    if isinstance(node, BlobRefNode):
        refuse_remote((FileRef(node.address),))
        raise _prebuilt(node.address.ref)
    if isinstance(node, NotStaticNode):
        raise not_static(node.target)
    if isinstance(node, WebFetchNode) and node.attachment is not None:
        # WHY not_static: the code a pre-built graph's attachment source already failed with
        # (rounds 7/8, pinned by tests) — now raised before any I/O instead of at execution.
        raise not_static(node.attachment.url)
    scan = _text_scan(node)
    if scan is not None:
        _refuse_scan(scan)


def _text_scan(node: DagNode) -> SourceScan | None:
    """The scan of url4 text ``node`` keeps for later: a verbatim context, a body, a lazy group."""
    scan = None
    if isinstance(node, RelUrlNode) and node.context and node.ctx_slots is None:
        # A context the lowering shipped verbatim (prose, or a holdings ref): judged exactly as
        # ``run(text)`` judges it — a holdings context stays the route's business (§5.6.3).
        if not holds_holdings_ref(node.context):
            scan = scan_sources(RelExpr(node.path, context=node.context))
    elif isinstance(node, MapNode):
        scan = scan_source_list(node.body)
    elif isinstance(node, LazyExprNode):
        try:
            scan = scan_sources(grammar_parse(node.text))
        except ParseError:
            scan = None  # it fails to compile when it runs; it names no source we can see
    return scan


def _refuse_scan(scan: SourceScan) -> None:
    """The run-start refusals, in ``run(text)``'s order; then fail closed on anything left."""
    refuse_malformed(scan)
    refuse_remote(scan.refs)
    if scan.non_literal:
        raise not_static(scan.non_literal[0])
    if scan.occurrences:
        raise not_static(scan.occurrences[0][0].url)
    if scan.refs:
        raise _prebuilt(scan.refs[0].address.ref)


def _prebuilt(source: str) -> ParseError:
    return ParseError(
        f"a pre-built graph names the attachment-capable source {display_url(source)!r}, but it "
        "has no source text to admit its files from; pass the expression text to run() instead",
        code=ErrorCode.MALFORMED_SOURCE,
        permanent=True,
    )


__all__ = ["prebuilt_remote_calls", "refuse_prebuilt"]
