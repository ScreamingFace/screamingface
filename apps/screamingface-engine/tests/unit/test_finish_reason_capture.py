"""Capturing a model call's `finish_reason` and the provider `refusal` field.

FEATURE: OME-679 — a provider refusal must be distinguishable from a bad answer, so a
safety-refusing model is not scored as if it answered badly.
STORY: as a researcher running HealthBench, a refused case shows up as its own failure kind
rather than as a wrong answer, and I can audit why every model call ended.

Three layers, because the signal crosses three seams:
  1. the connector reads it off the chat-completions payload and reports it (`ModelResponse`);
  2. `_RunState` folds those events onto the owning span;
  3. `SpanData` carries it on the wire as the OTel `gen_ai.response.finish_reasons` attribute.

A separate module from `test_aigateway_connector.py` rather than an append: the repo's
append-only gate compares file status, so growing an existing test file reads as "a prior test
was modified" even when the diff is purely additive (the line-level fix is in flight as OME-369).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.observe import ModelResponse, NodeFinished, NodeStarted, ObservationEvent
from url4.streaming.interfaces import Traced
from url4.streaming.protocol import SpanData

_MODEL = "anthropic/claude-haiku-4-5"


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def responses(self) -> list[ModelResponse]:
        return [e for e in self.events if isinstance(e, ModelResponse)]


def _gateway(bodies: dict | list[dict]) -> httpx.AsyncClient:
    """A chat-completions endpoint serving `bodies` — one dict, or a list consumed in order
    (the tool-loop case, where one turn is several round trips)."""
    sequence = bodies if isinstance(bodies, list) else [bodies]
    index = {"i": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        i = min(index["i"], len(sequence) - 1)
        index["i"] += 1
        return httpx.Response(200, json=sequence[i])

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )


def _body(
    *,
    content: str | None = "an answer",
    finish_reason: str | None = "stop",
    refusal: str | None = None,
    tool_calls: list[dict] | None = None,
) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if refusal is not None:
        message["refusal"] = refusal
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    choice: dict = {"message": message}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


async def _run(bodies: dict | list[dict], recorder: _Recorder | None = None) -> str:
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL)
    async with _gateway(bodies) as client:
        world = await build_aigateway_world(cfg, client=client)
        return await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=recorder)


# ── layer 1: the connector reports what it read ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_finish_reason_is_reported_for_a_normal_turn() -> None:
    # The signal OME-679 needs, which died at this hop: `_parse_choice` read only content and
    # tool_calls, so `stop` never left the connector.
    rec = _Recorder()
    result = await _run(_body(content="an answer", finish_reason="stop"), rec)

    assert result == "an answer"
    assert [r.finish_reason for r in rec.responses] == ["stop"]
    assert rec.responses[0].refusal is None


@pytest.mark.asyncio
async def test_absent_finish_reason_is_reported_as_none_not_fabricated() -> None:
    # Boundary: not every provider sends the field. Its absence must travel as None rather than
    # being invented — a fabricated "stop" is exactly the defect OME-746 fixed in aigateway.
    rec = _Recorder()
    await _run(_body(finish_reason=None), rec)

    assert [r.finish_reason for r in rec.responses] == [None]


@pytest.mark.asyncio
async def test_the_report_is_attributed_to_the_calling_node_span() -> None:
    # INVARIANT: the event lands on the span of the node that made the call, or a consumer
    # cannot tell WHICH model call ended how.
    rec = _Recorder()
    await _run(_body(), rec)

    starts = [e for e in rec.events if isinstance(e, NodeStarted)]
    assert {r.span_id for r in rec.responses} <= {e.span_id for e in starts}


# ── layer 1b: a refusal becomes its own typed failure ─────────────────────────────────────


@pytest.mark.asyncio
async def test_content_filter_raises_provider_refusal() -> None:
    # The conflation OME-679 exists to remove: a refused answer used to collapse into the same
    # generic `aigateway_bad_response` a malformed payload produces.
    with pytest.raises(ResolutionError) as exc_info:
        await _run(_body(content=None, finish_reason="content_filter"))

    assert exc_info.value.code == "provider_refusal"
    # WHY permanent: a refusal is deterministic. Retrying spends budget to be refused again.
    assert exc_info.value.permanent is True


@pytest.mark.asyncio
async def test_provider_refusal_field_raises_provider_refusal() -> None:
    # Not every provider signals a refusal through finish_reason; some populate `message.refusal`
    # and leave the reason as a plain stop.
    with pytest.raises(ResolutionError) as exc_info:
        await _run(_body(content=None, finish_reason="stop", refusal="I can't help with that"))

    assert exc_info.value.code == "provider_refusal"


@pytest.mark.asyncio
async def test_a_refused_turn_is_still_reported_before_it_raises() -> None:
    # INVARIANT: the refusal is the case a reviewer most needs to audit, so the event must be
    # emitted even though the call then fails. Reporting after the raise would lose exactly the
    # turn OME-679 cares about.
    rec = _Recorder()
    with pytest.raises(ResolutionError):
        await _run(_body(content=None, finish_reason="content_filter", refusal="nope"), rec)

    assert [r.finish_reason for r in rec.responses] == ["content_filter"]
    assert rec.responses[0].refusal == "nope"


@pytest.mark.asyncio
async def test_malformed_payload_still_raises_aigateway_bad_response() -> None:
    # Regression guard: classifying refusals must not swallow the pre-existing error class for a
    # response carrying neither content nor tool calls.
    with pytest.raises(ResolutionError) as exc_info:
        await _run({"choices": [{"message": {}}]})

    assert exc_info.value.code == "aigateway_bad_response"
    assert exc_info.value.permanent is True


@pytest.mark.asyncio
async def test_tool_loop_reports_one_event_per_round_trip() -> None:
    # INVARIANT: one node can make several model calls. The web-tool loop is the normal case, so
    # the intermediate `tool_calls` turn and the final `stop` must BOTH be auditable — the seam
    # must not collapse a turn's calls into one.
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "nope", "arguments": "{}"},
    }
    rec = _Recorder()
    await _run(
        [
            _body(content=None, finish_reason="tool_calls", tool_calls=[tool_call]),
            _body(content="final answer", finish_reason="stop"),
        ],
        rec,
    )

    assert [r.finish_reason for r in rec.responses] == ["tool_calls", "stop"]


# ── layer 2: the span accumulates them ────────────────────────────────────────────────────


def _span_frames(state: _RunState, events: list[ObservationEvent]) -> list[SpanData]:
    frames: list[SpanData] = []
    for event in events:
        for frame in state.map(event):
            payload = frame.payload if isinstance(frame, Traced) else frame
            if isinstance(payload, SpanData):
                frames.append(payload)
    return frames


def test_run_state_folds_every_reason_onto_the_owning_span_in_order() -> None:
    # Mirrors `_fold_usage`'s accumulate-don't-assign invariant: assigning would keep only the
    # last round trip and silently drop the rest of the turn.
    state = _RunState()
    spans = _span_frames(
        state,
        [
            NodeStarted("span1", None, "Node", "detail"),
            ModelResponse("span1", "tool_calls", None),
            ModelResponse("span1", "stop", None),
            NodeFinished("span1", "ok", 1),
        ],
    )

    assert len(spans) == 1
    assert spans[0].finish_reasons == ["tool_calls", "stop"]


def test_run_state_carries_the_refusal_text_onto_the_span() -> None:
    state = _RunState()
    spans = _span_frames(
        state,
        [
            NodeStarted("span1", None, "Node", "detail"),
            ModelResponse("span1", "content_filter", "I can't help with that"),
            NodeFinished("span1", "error", 1),
        ],
    )

    assert spans[0].refusal == "I can't help with that"


def test_a_span_with_no_model_call_carries_no_reasons() -> None:
    # Boundary: most nodes never call a model, so the attribute is absent rather than an empty
    # list — matching how OTel treats `gen_ai.*` attributes.
    state = _RunState()
    spans = _span_frames(
        state,
        [
            NodeStarted("span1", None, "Node", "detail"),
            NodeFinished("span1", "ok", 1),
        ],
    )

    assert spans[0].finish_reasons is None
    assert spans[0].refusal is None


def test_a_call_that_reported_no_reason_is_indistinguishable_from_no_call() -> None:
    # Pins the COLLAPSE as intended rather than accidental: a provider that omits finish_reason
    # leaves the span with nothing to report, and `_finish` renders that absent — byte-identical
    # to `test_a_span_with_no_model_call_carries_no_reasons` above.
    #
    # AIDEV-NOTE: this is a deliberate limit, not an oversight. Nothing consumes the difference
    # today. If something ever must tell "called a model that said nothing" from "made no call",
    # count folded events on `_SpanState` — do not infer it from an empty list.
    state = _RunState()
    spans = _span_frames(
        state,
        [
            NodeStarted("span1", None, "Node", "detail"),
            ModelResponse("span1", None, None),
            NodeFinished("span1", "ok", 1),
        ],
    )

    assert spans[0].finish_reasons is None


def test_a_reason_for_an_unknown_span_is_dropped_not_fabricated() -> None:
    # Boundary: mirrors `_fold_usage`'s guard — an event for a span the run never opened must not
    # invent one.
    state = _RunState()
    assert state.map(ModelResponse("ghost", "stop", None)) == []


# ── layer 3: the wire shape ───────────────────────────────────────────────────────────────


def test_span_data_round_trips_the_otel_finish_reasons_attribute() -> None:
    # INVARIANT: `gen_ai.response.finish_reasons` is the OTel semantic-convention name, and every
    # other gen_ai attribute on this model is aliased the same way — an OTel-aware consumer reads
    # this frame without a translation table.
    span = SpanData(
        name="n",
        operation="chat",
        start=datetime.now(UTC),
        finish_reasons=["stop"],
    )

    dumped = json.loads(span.model_dump_json(by_alias=True))
    assert dumped["gen_ai.response.finish_reasons"] == ["stop"]

    revived = SpanData.model_validate({**dumped})
    assert revived.finish_reasons == ["stop"]


def test_span_data_accepts_the_attribute_by_field_name_too() -> None:
    # `populate_by_name` is set on this model, so both spellings must validate.
    span = SpanData.model_validate(
        {
            "name": "n",
            "gen_ai.operation.name": "chat",
            "start": datetime.now(UTC).isoformat(),
            "finish_reasons": ["length"],
        }
    )

    assert span.finish_reasons == ["length"]
