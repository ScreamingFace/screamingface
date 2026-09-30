"""The chat route's capture helpers (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - a traced chat call leaves one capture row with its outcome: one row per
call, written at the route exit.

INVARIANT (CV-D5): only the INBOUND ``traceparent`` header selects a call for capture. The
call-id middleware MINTS ``request.state.trace_id`` for an untraced call, so that value is never
used here; an untraced call must not be recorded.

INVARIANT (CV-3): capture never changes the chat response. ``begin_capture`` and ``record_capture``
never raise, and neither logs a prompt, a response, the key material or a full key hash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, assert_never

from fastapi import Request

from ..core.cache_versions import CaptureKey, CaptureOutcome, build_capture_key, capture_record
from ..core.plugin_base import ProviderPluginBase
from ..w3c_trace import parse_trace_id
from .chat_cache_stage import CacheStatus, WriteStatus

logger = logging.getLogger(__name__)

_TRACE_PREFIX_LENGTH = 8

# Which source answered the call: the frozen version, the live global cache, or the provider
# (a streamed answer is its own source, because it is never stored and has no body to keep).
AnsweredBy = Literal["version", "global_cache", "provider", "provider_stream"]


@dataclass(frozen=True, slots=True)
class CaptureContext:
    account_id: str
    trace_id: str
    key: CaptureKey | None


def begin_capture(
    request: Request, *, account_id: str, body: dict[str, Any], plugin: ProviderPluginBase
) -> CaptureContext | None:
    """The capture context of a traced call, or ``None`` when the call is not captured."""
    if not request.app.state.settings.cache_versions_enabled:
        return None
    trace_id = parse_trace_id(request.headers.get("traceparent"))
    if trace_id is None:
        return None
    try:
        key = build_capture_key(body=body, plugin=plugin)
    except Exception:
        # Defence: `build_capture_key` is total, but a capture bug must not cost a reply.
        key = None
    return CaptureContext(account_id=account_id, trace_id=trace_id, key=key)


async def record_capture(
    request: Request,
    ctx: CaptureContext | None,
    outcome: CaptureOutcome,
    *,
    response: object | None = None,
) -> None:
    """Write the capture row of a call. Never raises."""
    if ctx is None:
        return
    state = request.app.state
    try:
        record = capture_record(
            account_id=ctx.account_id,
            trace_id=ctx.trace_id,
            outcome=outcome,
            key=ctx.key,
            response=response,
        )
        await state.capture_sink.record(record)
    except Exception as exc:
        # The exception TYPE only: its text can carry SQL parameters, i.e. the prompt.
        logger.warning(
            "cache capture failed (%s) trace=%s…",
            type(exc).__name__,
            ctx.trace_id[:_TRACE_PREFIX_LENGTH],
        )
        state.capture_stats.failures += 1
        return
    state.capture_stats.rows[outcome] += 1


def capture_outcome(
    answered_by: AnsweredBy, *, cache_status: CacheStatus | None, write_status: WriteStatus | None
) -> CaptureOutcome:
    """The capture outcome of an answered call. Pure and total over its inputs.

    WHY `race_lost` is `unstored`: the live row then holds the OTHER caller's answer.
    WHY a provider answer with no write and no bypass is `unstored` too: the live cache holds no
    row for this call, so the capture row must carry the answer itself.
    """
    match answered_by:
        case "version":
            return "version_hit"
        case "global_cache":
            return "hit"
        case "provider_stream":
            return "bypass"
        case "provider":
            if write_status == "stored":
                return "stored"
            if write_status is not None:
                return "unstored"
            return "bypass" if cache_status == "bypass" else "unstored"
        case _:
            assert_never(answered_by)
