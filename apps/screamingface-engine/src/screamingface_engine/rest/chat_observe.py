"""The metrics and the one log line of each POST /v1/chat/completions request.

FEATURE: OpenAI-compatible Engine API (prd/chat-completion.md §3.4 Metrics, §4 Observability).
Each request counts once by outcome, is timed once, and writes one INFO line at its end.

INVARIANT: the line holds only codes, numbers, digests and ids: never message content, tool
arguments, recipe text or an identity value.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from starlette.requests import Request

__all__ = ["RequestFacts", "observe"]

_logger = logging.getLogger(__name__)


@dataclass
class RequestFacts:
    """What one request has learned by the time it ends; None when its stage was not reached.

    INVARIANT: the topic of the run is not here. A topic gives access to the events of its run,
    so the request line names the run by its trace id only.
    """

    trace_id: str | None = None
    digest: str | None = None
    size: int | None = None
    messages: int | None = None


def _dash(value: object | None) -> str:
    return "-" if value is None else str(value)


def observe(
    request: Request, facts: RequestFacts, outcome: str, status: int, seconds: float
) -> None:
    """Q8: screamingface_engine_chat_requests_total{outcome}, the duration histogram, and the
    log line of the request."""
    metrics = request.app.state.metrics
    if metrics.chat_requests is not None:
        metrics.chat_requests.labels(outcome=outcome).inc()
    if metrics.chat_request_duration is not None:
        metrics.chat_request_duration.observe(seconds)
    _logger.info(
        "chat request outcome=%s status=%d duration_s=%.3f trace_id=%s digest=%s "
        "size=%s messages=%s",
        outcome,
        status,
        seconds,
        _dash(facts.trace_id),
        "-" if facts.digest is None else "sha256:" + facts.digest,
        _dash(facts.size),
        _dash(facts.messages),
    )
