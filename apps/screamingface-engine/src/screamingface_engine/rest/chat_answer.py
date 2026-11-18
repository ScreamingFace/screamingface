"""Stage 7 of POST /v1/chat/completions: the answer from the run's frames.

The terminal table of prd/chat-completion.md §3.2 maps (state, raw code) to the HTTP status,
the body code and x-should-retry. The body message comes only from `_sanitized_error`, or from
the fixed message of the body code. A succeeded run answers with the CHAT_RESULT, inline or from
the artifact store, and with usage and cost from the root cost-usage frame (contracts C9).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi.responses import JSONResponse

from screamingface_engine.artifacts.ports import ArtifactContent, ArtifactReader, LocalFile
from screamingface_engine.chat.result import (
    CHAT_RESULT_MEDIA_TYPE,
    ChatResult,
    ChatResultError,
    FinalStep,
    decode_chat_result,
)
from screamingface_engine.chat.wire import (
    ChatCompletionResponse,
    Choice,
    FinalStepInfo,
    ResponseMessage,
    ScreamingFaceInfo,
    Usage,
)
from screamingface_engine.rest.chat_errors import ChatError
from screamingface_engine.rest.chat_frames import RunFrames
from screamingface_engine.rest.routes import _sanitized_error
from screamingface_engine.world.accounting import UNPRICED
from url4.streaming.protocol import ResultEvent, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.trace import parse_traceparent

__all__ = [
    "answer",
    "completion_id",
    "completion_parts",
    "failure",
    "missing_root_frame_usage",
    "read_result",
    "usage_and_cost",
]

_logger = logging.getLogger(__name__)

_SCRUBBED = "internal_error"

type _Row = tuple[int, str, bool]

# INVARIANT: (state, raw code) -> (HTTP status, body code, x-should-retry), the fixed rows of
# the terminal table.
_CODE_ROWS: dict[tuple[str, str | None], _Row] = {
    ("failed", "fail_closed"): (422, "fail_closed", False),
    ("failed", "chat_input_unavailable"): (500, "chat_input_unavailable", False),
    ("failed", "chat_input_invalid"): (500, "chat_input_invalid", False),
    ("failed", "final_step_ambiguous"): (502, "final_step_ambiguous", False),
    ("failed", "memory_budget_exceeded"): (503, "run_failed", False),
    ("failed", "oom_killed"): (503, "run_failed", True),
    ("failed", "killed"): (503, "run_failed", True),
    ("failed", "child_exited"): (503, "run_failed", True),
    ("stopped", "worker_draining"): (503, "worker_draining", True),
}
# INVARIANT: the rows of a state, whatever its code.
_STATE_ROWS: dict[str, _Row] = {
    "stopped": (503, "run_failed", True),
    "timed_out": (504, "timeout", False),
}


async def answer(frames: RunFrames, model: str, store: ArtifactReader | None) -> JSONResponse:
    """The 200 answer of a succeeded run, or the ChatError of its terminal row."""
    result = await read_result(frames, store)
    return JSONResponse(_completion(result, frames, model).model_dump(mode="json"))


async def read_result(frames: RunFrames, store: ArtifactReader | None) -> ChatResult:
    """The CHAT_RESULT of a succeeded run; the ChatError of its terminal row otherwise."""
    if frames.terminated.data.status != "succeeded":
        raise failure(frames.terminated)
    return await _chat_result(frames.result, store)


def completion_id() -> str:
    """A new completion id."""
    # INVARIANT: never the topic, which is a bearer secret (prd §4 Security).
    return "chatcmpl-" + uuid.uuid4().hex


def completion_parts(result: ChatResult, frames: RunFrames) -> tuple[Usage, ScreamingFaceInfo]:
    """C9: the usage and the screamingface object of an answer."""
    trace_id = parse_traceparent(frames.terminated.traceparent)
    usage, cost_usd = usage_and_cost(frames.root_cost, trace_id)
    info = ScreamingFaceInfo(
        status=result.status,
        abstain_reason=result.abstain_reason,
        cost_usd=cost_usd,
        trace_id=trace_id,
        final_step=_final_step(result.final_step),
    )
    return usage, info


def failure(terminated: TerminatedEvent) -> ChatError:
    """The terminal table row of a run that did not succeed."""
    error = terminated.data.error
    raw = error.code if error is not None else None
    code, message, permanent = _sanitized_error(error)
    status, body_code, should_retry = _row(terminated.data.status, raw, code, permanent)
    # WHY only for the same code: a remapped body code (run_failed) gets its own fixed message.
    shown = message if body_code == code and message else None
    return ChatError(status, body_code, shown, should_retry=should_retry)


def _row(state: str, raw: str | None, code: str | None, permanent: bool | None) -> _Row:
    row = _CODE_ROWS.get((state, raw)) or _STATE_ROWS.get(state)
    if row is not None:
        return row
    if state == "failed" and code is not None and code != _SCRUBBED:
        # WHY: a code the Engine vouches for; a retry can help only when the failure is not
        # permanent.
        return 502, code, not permanent
    return 502, _SCRUBBED, False


async def _chat_result(result: ResultEvent | None, store: ArtifactReader | None) -> ChatResult:
    if result is None:
        raise ChatError(502, "result_unavailable")
    if result.data.media_type != CHAT_RESULT_MEDIA_TYPE:
        raise ChatError(502, "result_invalid")
    data = await _result_bytes(result, store)
    try:
        return decode_chat_result(data)
    except ChatResultError:
        raise ChatError(502, "result_invalid") from None


async def _result_bytes(result: ResultEvent, store: ArtifactReader | None) -> bytes:
    """The result body, inline or read through the artifact reader port (contracts C9)."""
    artifact = result.data.artifact
    if artifact is None:
        return (result.data.body or "").encode("utf-8")
    content = await asyncio.to_thread(store.content, artifact.id) if store is not None else None
    if content is None:
        raise ChatError(502, "result_unavailable")
    try:
        return await _content_bytes(content)
    except OSError:
        raise ChatError(502, "result_unavailable") from None


async def _content_bytes(content: ArtifactContent) -> bytes:
    if isinstance(content, LocalFile):
        return await asyncio.to_thread(content.path.read_bytes)
    return b"".join([chunk async for chunk in content.stream])


def _completion(result: ChatResult, frames: RunFrames, model: str) -> ChatCompletionResponse:
    usage, info = completion_parts(result, frames)
    refused = result.status == "refused"
    message = ResponseMessage(
        content=None if refused else result.content,
        tool_calls=list(result.tool_calls) or None,
        refusal=result.refusal,
    )
    return ChatCompletionResponse(
        id=completion_id(),
        created=int(time.time()),
        model=model,
        choices=[Choice(index=0, finish_reason=result.finish_reason, message=message)],
        usage=usage,
        screamingface=info,
    )


def usage_and_cost(root: CostUsageData | None, trace_id: str | None) -> tuple[Usage, str | None]:
    """C9: usage and cost from the root frame; the cost is null for an unpriced run."""
    if root is None:
        return missing_root_frame_usage(trace_id)
    prompt, completion = root.usage.input_tokens, root.usage.output_tokens
    usage = Usage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )
    cost = None if root.pricing_version == UNPRICED else format(root.cost.total_usd, "f")
    return usage, cost


def missing_root_frame_usage(trace_id: str | None) -> tuple[Usage, None]:
    """Q7 default (owner answer pending): zero usage, a null cost and one warning line."""
    _logger.warning("chat run sent no root cost-usage frame trace_id=%s", trace_id or "-")
    return Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0), None


def _final_step(step: FinalStep | None) -> FinalStepInfo | None:
    if step is None:
        return None
    return FinalStepInfo(binding=step.binding, model=step.model, usage=_step_usage(step.usage))


def _step_usage(raw: dict[str, Any] | None) -> Usage | None:
    """The usage block of the final call, when it has whole token counts."""
    prompt, completion = _count(raw, "prompt_tokens"), _count(raw, "completion_tokens")
    if prompt is None or completion is None:
        return None
    return Usage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _count(raw: dict[str, Any] | None, name: str) -> int | None:
    value = (raw or {}).get(name)
    whole = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return value if whole else None
