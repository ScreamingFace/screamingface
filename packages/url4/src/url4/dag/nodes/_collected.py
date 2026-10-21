"""The collected-error row (spec §5.3.6 ``iteration.on_error=collect``).

Split from ``_shared.py`` by reason to change: this is the wire form of a failed row, which
changes with the error contract (``ErrorCause``), not with the nodes' shared plumbing.
"""

from __future__ import annotations

from url4.core.errors import ErrorCause


def collected_error(exc: BaseException) -> dict:
    """One collected row's wire error object (spec §5.3.6 ``collect``).

    Preserves the exception's URL4 diagnostics — ``code`` and ``permanent`` — beside the
    kind/message pair, so a ``collect``-boundary consumer (a benchmark's outcome envelope,
    the SDK report) can render the ORIGINAL upstream failure instead of falling back to a
    default code. ``permanent`` travels as ``retryable`` (its inverse): permanent errors
    must not be retried, and every reader of this payload already keys on retryability
    (``screamingface_engine.benchmarks.aggregation.public_error``).

    Public (``url4.dag.collected_error``): a code handler that runs several steps in process
    records a failed step in this same shape, so a reader of collected rows has one decoder.
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
    cause = getattr(exc, "cause", None)
    if isinstance(cause, ErrorCause):
        # The handler's own failure behind an intent_error (Spec C §13.6), kept for the reader.
        payload["cause"] = {"code": cause.code, "retryable": not cause.permanent}
    return {"error": payload}
