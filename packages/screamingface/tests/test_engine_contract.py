"""What the Client shows of one SF Engine CloudEvent: `display_event` (E5 P2 spec §4.2, D13).

The follow hands each `candidate.event` frame's CloudEvent to `display_event`, for `on_event` and
the progress output. A Candidate's outcome is the Engine's record; the rules it is folded by are
pinned on the Engine's fold (`apps/screamingface-engine/tests/unit/test_candidate_record_rules.py`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import pytest

import screamingface as sf
from screamingface._engine import contract as _engine_contract
from screamingface._engine.contract import display_event
from screamingface.errors import ExecutionError

URL4 = "(@)!'hello'"


def frame(
    event_type: str,
    data: dict[str, object],
    *,
    sequence: int | None,
    source: str = "/trace/run_1/node/root",
    event_id: str | None = None,
) -> str:
    value: dict[str, object] = {
        "specversion": "1.0",
        "id": event_id or f"event_{sequence or 'heartbeat'}",
        "source": source,
        "subject": "run_1",
        "time": "2026-07-25T16:00:00Z",
        "type": event_type,
        "datacontenttype": "application/json",
        "data": data,
    }
    if sequence is not None:
        value["sequence"] = str(sequence)
        value["sequencetype"] = "Integer"
    return json.dumps(value)


def _shown(raw: str) -> sf.Event | None:
    return display_event(json.loads(raw))


def test_a_start_and_an_end_are_shown_and_a_result_is_not() -> None:
    started = _shown(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    result = _shown(
        frame(
            "ai.url4.result",
            {"body": '{"schema":"result"}', "media_type": "application/json"},
            sequence=2,
        )
    )
    terminated = _shown(
        frame(
            "ai.url4.terminated",
            {"status": "succeeded", "error": None},
            sequence=3,
        )
    )

    assert isinstance(started, sf.events.Started)
    assert result is None
    assert isinstance(terminated, sf.events.Terminated)
    assert terminated.status == "succeeded"


def test_unpriced_usage_does_not_fabricate_zero_accounting() -> None:
    usage = _shown(
        frame(
            "ai.url4.cost.usage",
            {
                "scope": "subtree",
                "gen_ai.provider.name": "openrouter",
                "gen_ai.response.model": "openrouter/openai/gpt-5.5",
                "pricing_version": "unpriced",
                "usage": {
                    "gen_ai.usage.input_tokens": 100,
                    "gen_ai.usage.output_tokens": 20,
                    "gen_ai.usage.cache_read_tokens": 0,
                    "gen_ai.usage.cache_creation_tokens": 0,
                    "gen_ai.usage.reasoning_tokens": 0,
                },
                "cost": {
                    "input_usd": "0",
                    "output_usd": "0",
                    "cache_read_usd": "0",
                    "cache_creation_usd": "0",
                    "reasoning_usd": "0",
                    "total_usd": "0",
                },
            },
            sequence=1,
        )
    )

    assert isinstance(usage, sf.events.Usage)
    assert usage.usage == sf.Usage(input_tokens=100, output_tokens=20)


def test_priced_usage_keeps_the_engine_total_when_parts_differ(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="screamingface._engine.contract"):
        usage = _shown(
            frame(
                "ai.url4.cost.usage",
                {
                    "scope": "subtree",
                    "gen_ai.provider.name": "openrouter",
                    "gen_ai.response.model": "openrouter/openai/gpt-5.5",
                    "pricing_version": "2026-08-06",
                    "usage": {
                        "gen_ai.usage.input_tokens": 100,
                        "gen_ai.usage.output_tokens": 20,
                    },
                    "cost": {
                        "input_usd": "0.01",
                        "output_usd": "0.02",
                        "total_usd": "0.030001",
                    },
                },
                sequence=1,
            )
        )

    assert isinstance(usage, sf.events.Usage)
    assert usage.usage.cost_usd == Decimal("0.030001")
    assert "does not equal its parts" in caplog.text


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        ("ai.url4.heartbeat", {}),
        ("ai.url4.error", {"code": "invalid_attach", "message": "bad attach", "ref_id": None}),
        ("ai.url4.started", {"url4": URL4}),
        ("ai.url4.result", {"body": "{}", "media_type": "application/json"}),
        ("ai.url4.terminated", {"status": "succeeded", "error": None}),
        ("ai.url4.span", {"name": "n", "gen_ai.operation.name": "chat"}),
    ],
)
def test_a_frame_off_the_ordered_stream_is_not_shown(
    event_type: str, data: dict[str, object]
) -> None:
    # WHY: `Event.sequence` is a mandatory positive integer, so a frame without one is no public
    # Event, and inventing one would pollute the order the sequence defines.
    assert _shown(frame(event_type, data, sequence=None)) is None


def test_a_kind_this_client_does_not_know_is_not_shown() -> None:
    assert _shown(frame("ai.url4.unknown", {}, sequence=1)) is None


def test_logs_spans_and_a_childs_lifecycle_are_shown() -> None:
    log = _shown(
        frame(
            "ai.url4.log",
            {
                "severity_number": 9,
                "severity_text": "INFO",
                "body": "working",
                "attributes": {"attempt": 1},
            },
            sequence=2,
        )
    )
    span = _shown(
        frame(
            "ai.url4.span",
            {
                "name": "model",
                "kind": "client",
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": "openrouter",
                "gen_ai.request.model": "requested",
                "gen_ai.response.model": "actual",
                "gen_ai.usage.input_tokens": 10,
                "gen_ai.usage.output_tokens": 2,
                "gen_ai.response.finish_reasons": ["tool_calls", "stop"],
                "refusal": "policy refusal",
                "start": "2026-07-25T16:00:00Z",
                "end": "2026-07-25T16:00:01Z",
                "status": "ok",
            },
            sequence=3,
        )
    )
    child_start = _shown(
        frame(
            "ai.url4.started",
            {"url4": URL4},
            sequence=4,
            source="/trace/run_1/node/child",
        )
    )
    ignored_result = _shown(
        frame(
            "ai.url4.result",
            {"body": "child", "media_type": "application/json"},
            sequence=5,
            source="/trace/run_1/node/child",
        )
    )
    child_terminal = _shown(
        frame(
            "ai.url4.terminated",
            {"status": "succeeded", "error": None},
            sequence=6,
            source="/trace/run_1/node/child",
        )
    )

    assert isinstance(log, sf.events.Log)
    assert isinstance(span, sf.events.Span)
    assert span.finish_reasons == ("tool_calls", "stop")
    assert span.refusal == "policy refusal"
    assert isinstance(child_start, sf.events.Started)
    assert ignored_result is None
    assert isinstance(child_terminal, sf.events.Terminated)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.pop("sequencetype"), "Integer semantics"),
        (lambda value: value.update(sequence="0"), "positive integer string"),
        (lambda value: value.update(time="not-time"), "RFC 3339"),
        (lambda value: value.pop("source"), "source"),
    ],
)
def test_an_invalid_envelope_is_refused(mutate: object, message: str) -> None:
    value = json.loads(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    cast(Callable[[dict[str, object]], None], mutate)(value)
    with pytest.raises(sf.ExecutionError, match=message):
        display_event(value)


def test_an_invalid_event_payload_is_refused() -> None:
    with pytest.raises(sf.ExecutionError, match="severity_text"):
        _shown(
            frame(
                "ai.url4.log",
                {
                    "severity_number": 9,
                    "severity_text": "TRACE",
                    "body": "x",
                    "attributes": {},
                },
                sequence=1,
            )
        )
    with pytest.raises(sf.ExecutionError, match="non-scalar"):
        _shown(
            frame(
                "ai.url4.log",
                {
                    "severity_number": 9,
                    "severity_text": "INFO",
                    "body": "x",
                    "attributes": {"nested": {}},
                },
                sequence=1,
            )
        )
    with pytest.raises(sf.ExecutionError, match="termination status"):
        _shown(
            frame(
                "ai.url4.terminated",
                {"status": "unknown", "error": None},
                sequence=1,
            )
        )
    with pytest.raises(sf.ExecutionError, match="permanent"):
        _shown(
            frame(
                "ai.url4.terminated",
                {
                    "status": "failed",
                    "error": {"code": "x", "message": "x", "permanent": "no"},
                },
                sequence=1,
            )
        )


def test_decoder_scalar_helpers_reject_invalid_wire_values() -> None:
    assert _engine_contract._optional_text(None, "x") is None
    assert _engine_contract._optional_integer(None, "x") is None
    assert _engine_contract._optional_timestamp(None) is None
    assert _engine_contract._decimal(Decimal("1"), "x") == Decimal("1")

    invalid_calls = (
        lambda: _engine_contract._object([], "x"),
        lambda: _engine_contract._required_text("", "x"),
        lambda: _engine_contract._raw_text({}, "x"),
        lambda: _engine_contract._integer(-1, "x"),
        lambda: _engine_contract._timestamp(1),
        lambda: _engine_contract._timestamp("2026-01-01"),
        lambda: _engine_contract._decimal(True, "x"),
        lambda: _engine_contract._decimal("not-decimal", "x"),
        lambda: _engine_contract._decimal("-1", "x"),
    )
    for call in invalid_calls:
        with pytest.raises(sf.ExecutionError):
            call()


# --- Out-of-band advisory notices ---------------------------------------------------------
#
# The control plane may add a notice to a Run's stream outside the broker's sequencer.
# INVARIANT: a notice off the ordered stream is no public Event; one the broker sequenced is.


def _null_sequenced_log(body: str = "cache policy fixed by first attach") -> str:
    """The verbatim wire shape of screamingface_engine.notices.warn through url4's encoder.

    The sequence keys are PRESENT and null rather than omitted, because ``encode`` does not
    pass ``exclude_none``. A hand-written fixture would assume otherwise.
    """

    return json.dumps(
        {
            "specversion": "1.0",
            "id": "notice_1",
            "source": "/trace/run_1",
            "subject": "run_1",
            "time": "2026-07-25T16:00:00Z",
            "datacontenttype": "application/json",
            "dataschema": None,
            "sequence": None,
            "sequencetype": None,
            "traceparent": None,
            "tracestate": None,
            "type": "ai.url4.log",
            "data": {
                "severity_number": 13,
                "severity_text": "WARN",
                "body": body,
                "attributes": {"cache.declared": "not stated"},
            },
        }
    )


def test_an_unsequenced_advisory_log_is_kept_out_of_the_ordered_stream() -> None:
    assert _shown(_null_sequenced_log()) is None


def test_an_advisory_log_with_omitted_sequence_keys_is_also_unsequenced() -> None:
    shown = _shown(
        frame(
            "ai.url4.log",
            {"severity_number": 13, "severity_text": "WARN", "body": "notice"},
            sequence=None,
        )
    )

    assert shown is None


def test_an_advisory_log_that_carries_a_sequence_keeps_the_ordered_path() -> None:
    shown = _shown(
        frame(
            "ai.url4.log",
            {"severity_number": 9, "severity_text": "INFO", "body": "ordered"},
            sequence=1,
        )
    )

    assert isinstance(shown, sf.events.Log)
    assert shown.sequence == 1


def test_a_sequenced_frame_missing_only_its_sequencetype_is_still_rejected() -> None:
    # INVARIANT: the discriminator is the presence of "sequence" ALONE. Keying on both fields
    # would reclassify this frame as advisory and silently skip the started handler.
    payload = cast(dict[str, Any], json.loads(frame("ai.url4.started", {"url4": URL4}, sequence=1)))
    del payload["sequencetype"]

    with pytest.raises(sf.ExecutionError, match="Integer semantics"):
        display_event(payload)


def test_a_spans_cache_provenance_is_shown() -> None:
    span = _shown(
        frame(
            "ai.url4.span",
            {
                "name": "model",
                "kind": "client",
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "openrouter/example/model",
                "start": "2026-07-25T16:00:00Z",
                "end": "2026-07-25T16:00:01Z",
                "status": "ok",
                "cache_status": "hit",
                "cache_reason": "exact_match",
            },
            sequence=1,
        )
    )

    assert isinstance(span, sf.events.Span)
    assert span.cache_status == "hit"
    assert span.cache_reason == "exact_match"


def test_an_unknown_span_cache_status_is_refused() -> None:
    with pytest.raises(ExecutionError, match="cache_status"):
        _shown(
            frame(
                "ai.url4.span",
                {
                    "name": "model",
                    "kind": "client",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": "openrouter/example/model",
                    "start": "2026-07-25T16:00:00Z",
                    "end": "2026-07-25T16:00:01Z",
                    "status": "ok",
                    "cache_status": "stale",
                },
                sequence=1,
            )
        )


@pytest.mark.parametrize("cache_status", [[], {}])
def test_a_non_scalar_span_cache_status_is_refused(cache_status: object) -> None:
    """INVARIANT: malformed JSON stays inside the Client's ExecutionError boundary."""

    with pytest.raises(ExecutionError, match="cache_status"):
        _shown(
            frame(
                "ai.url4.span",
                {
                    "name": "model",
                    "kind": "client",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": "openrouter/example/model",
                    "start": "2026-07-25T16:00:00Z",
                    "end": "2026-07-25T16:00:01Z",
                    "status": "ok",
                    "cache_status": cache_status,
                },
                sequence=1,
            )
        )
