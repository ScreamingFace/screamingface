from __future__ import annotations

import json
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import pytest

import screamingface as sf
from screamingface._engine import contract as _engine_contract
from screamingface._engine.contract import _RunState
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


def test_state_decodes_public_events_and_root_lifecycle() -> None:
    state = _RunState(URL4)

    started = state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    result = state.accept(
        frame(
            "ai.url4.result",
            {"body": '{"schema":"result"}', "media_type": "application/json"},
            sequence=2,
        )
    )
    terminated = state.accept(
        frame(
            "ai.url4.terminated",
            {"status": "succeeded", "error": None},
            sequence=3,
        )
    )

    assert isinstance(started.event, sf.events.Started)
    assert result.event is None
    assert terminated.outcome is not None
    assert terminated.outcome.run_id == "run_1"
    assert terminated.outcome.result_body == '{"schema":"result"}'
    assert terminated.outcome.started_at.isoformat() == "2026-07-25T16:00:00+00:00"


def test_unpriced_usage_does_not_fabricate_zero_accounting() -> None:
    accepted = _RunState(URL4).accept(
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

    assert isinstance(accepted.event, sf.events.Usage)
    assert accepted.event.usage == sf.Usage(input_tokens=100, output_tokens=20)


def test_priced_usage_keeps_the_engine_total_when_parts_differ(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="screamingface._engine.contract"):
        accepted = _RunState(URL4).accept(
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

    assert isinstance(accepted.event, sf.events.Usage)
    assert accepted.event.usage.cost_usd == Decimal("0.030001")
    assert "does not equal its parts" in caplog.text


def test_heartbeat_is_internal_and_does_not_participate_in_stream_sequence() -> None:
    state = _RunState(URL4)

    accepted = state.accept(frame("ai.url4.heartbeat", {}, sequence=None))

    assert accepted.event is None
    assert accepted.outcome is None
    assert accepted.replay_from is None


def test_heartbeat_still_validates_its_run_envelope() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.heartbeat", {}, sequence=None))
    changed = json.loads(frame("ai.url4.heartbeat", {}, sequence=None))
    changed["subject"] = "run_2"

    with pytest.raises(sf.ExecutionError, match="changed run subject"):
        state.accept(json.dumps(changed))

    malformed = json.loads(frame("ai.url4.heartbeat", {}, sequence=None))
    malformed.pop("source")
    with pytest.raises(sf.ExecutionError, match="source"):
        _RunState(URL4).accept(json.dumps(malformed))


def test_duplicate_frames_are_ignored_and_gaps_request_replay() -> None:
    state = _RunState(URL4)
    first = frame("ai.url4.started", {"url4": URL4}, sequence=1)

    assert state.accept(first).event is not None
    assert state.accept(first).event is None
    assert (
        state.accept(
            frame(
                "ai.url4.log",
                {
                    "severity_number": 9,
                    "severity_text": "INFO",
                    "body": "working",
                    "attributes": {},
                },
                sequence=3,
            )
        ).replay_from
        == 2
    )


def test_repeated_sequence_gaps_stop_after_a_bounded_replay_budget() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    skipped = frame(
        "ai.url4.log",
        {
            "severity_number": 9,
            "severity_text": "INFO",
            "body": "still missing sequence two",
            "attributes": {},
        },
        sequence=3,
    )

    for _ in range(3):
        assert state.accept(skipped).replay_from == 2
    with pytest.raises(sf.ExecutionError) as caught:
        state.accept(skipped)

    assert caught.value.code == "event_stream_replay_exhausted"
    assert caught.value.permanent is False


def test_reused_event_id_at_a_new_sequence_is_rejected() -> None:
    state = _RunState(URL4)
    state.accept(
        frame(
            "ai.url4.started",
            {"url4": URL4},
            sequence=1,
            event_id="same-event",
        )
    )

    with pytest.raises(sf.ExecutionError, match="event id"):
        state.accept(
            frame(
                "ai.url4.log",
                {
                    "severity_number": 9,
                    "severity_text": "INFO",
                    "body": "working",
                    "attributes": {},
                },
                sequence=2,
                event_id="same-event",
            )
        )


def test_state_rejects_malformed_or_inconsistent_frames() -> None:
    state = _RunState(URL4)

    with pytest.raises(sf.ExecutionError, match="valid JSON"):
        state.accept("not json")

    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    with pytest.raises(sf.ExecutionError, match="changed run subject"):
        changed = json.loads(
            frame(
                "ai.url4.log",
                {
                    "severity_number": 9,
                    "severity_text": "INFO",
                    "body": "working",
                    "attributes": {},
                },
                sequence=2,
            )
        )
        changed["subject"] = "run_2"
        state.accept(json.dumps(changed))


def test_succeeded_root_requires_exactly_one_result() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))

    with pytest.raises(sf.ExecutionError, match="without a root result"):
        state.accept(
            frame(
                "ai.url4.terminated",
                {"status": "succeeded", "error": None},
                sequence=2,
            )
        )


def test_failed_root_becomes_a_structured_execution_error() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))

    with pytest.raises(sf.ExecutionError) as caught:
        state.accept(
            frame(
                "ai.url4.terminated",
                {
                    "status": "failed",
                    "error": {
                        "code": "gateway_timeout",
                        "message": "The model timed out.",
                        "permanent": False,
                    },
                },
                sequence=2,
            )
        )

    assert caught.value.code == "gateway_timeout"
    assert caught.value.permanent is False


def test_root_result_preserves_optional_media_type_without_interpreting_the_body() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    state.accept(
        frame(
            "ai.url4.result",
            {"body": "[mock] done", "media_type": None},
            sequence=2,
        )
    )
    terminated = state.accept(
        frame(
            "ai.url4.terminated",
            {"status": "succeeded", "error": None},
            sequence=3,
        )
    )

    assert terminated.outcome is not None
    assert terminated.outcome.result_body == "[mock] done"
    assert terminated.outcome.media_type is None


def test_state_decodes_log_span_and_non_root_lifecycle() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    log = state.accept(
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
    span = state.accept(
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
    ignored_result = state.accept(
        frame(
            "ai.url4.result",
            {"body": "child", "media_type": "application/json"},
            sequence=4,
            source="/trace/run_1/node/child",
        )
    )
    child_terminal = state.accept(
        frame(
            "ai.url4.terminated",
            {"status": "succeeded", "error": None},
            sequence=5,
            source="/trace/run_1/node/child",
        )
    )

    assert isinstance(log.event, sf.events.Log)
    assert isinstance(span.event, sf.events.Span)
    assert span.event.finish_reasons == ("tool_calls", "stop")
    assert span.event.refusal == "policy refusal"
    assert ignored_result.outcome is None
    assert isinstance(child_terminal.event, sf.events.Terminated)


def test_state_rejects_duplicate_root_events_and_consumes_protocol_nacks() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    with pytest.raises(sf.ExecutionError, match="duplicate root started"):
        state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=2))

    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    state.accept(
        frame(
            "ai.url4.result",
            {"body": "{}", "media_type": "application/json"},
            sequence=2,
        )
    )
    with pytest.raises(sf.ExecutionError, match="duplicate root result"):
        state.accept(
            frame(
                "ai.url4.result",
                {"body": "{}", "media_type": "application/json"},
                sequence=3,
            )
        )

    state = _RunState(URL4)
    advisory = state.accept(
        frame(
            "ai.url4.error",
            {"code": "invalid_attach", "message": "bad attach", "ref_id": None},
            sequence=None,
        )
    )
    started = state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))

    assert advisory == _engine_contract._Accepted()
    assert isinstance(started.event, sf.events.Started)


def test_stream_failure_requests_bounded_reattach_then_surfaces_the_error() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    data = {
        "code": "stream_failed",
        "message": "the topic subscription failed (ServerError); re-attach to resume",
        "ref_id": None,
    }

    for _ in range(3):
        accepted = state.accept(frame("ai.url4.error", data, sequence=None))
        assert accepted.replay_from == 2

    with pytest.raises(sf.ExecutionError) as caught:
        state.accept(frame("ai.url4.error", data, sequence=None))

    assert caught.value.code == "event_stream_failed"
    assert caught.value.permanent is False
    assert caught.value.details == data
    assert str(caught.value) == data["message"]


def test_equal_looking_child_started_event_does_not_replace_root_identity() -> None:
    state = _RunState(URL4)
    root = state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    child = state.accept(
        frame(
            "ai.url4.started",
            {"url4": URL4},
            sequence=2,
            source="/trace/run_1/node/child",
        )
    )

    assert isinstance(root.event, sf.events.Started)
    assert isinstance(child.event, sf.events.Started)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(specversion="0.3"), "specversion"),
        (lambda value: value.update(datacontenttype="text/plain"), "application/json"),
        (lambda value: value.pop("sequencetype"), "Integer semantics"),
        (lambda value: value.update(sequence="0"), "positive integer string"),
        (lambda value: value.update(type="ai.url4.unknown"), "unsupported"),
        (lambda value: value.update(time="not-time"), "RFC 3339"),
    ],
)
def test_state_rejects_invalid_envelopes(mutate: object, message: str) -> None:
    value = json.loads(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    cast(Callable[[dict[str, object]], None], mutate)(value)
    with pytest.raises(sf.ExecutionError, match=message):
        _RunState(URL4).accept(json.dumps(value))


def test_state_accepts_utf8_bytes_and_rejects_non_utf8_or_binary_objects() -> None:
    accepted = _RunState(URL4).accept(frame("ai.url4.started", {"url4": URL4}, sequence=1).encode())
    assert accepted.event is not None
    with pytest.raises(sf.ExecutionError, match="UTF-8"):
        _RunState(URL4).accept(b"\xff")
    with pytest.raises(sf.ExecutionError, match="text JSON"):
        _RunState(URL4).accept(cast(Any, 123))


def test_state_rejects_invalid_event_payloads() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    with pytest.raises(sf.ExecutionError, match="media_type"):
        state.accept(
            frame(
                "ai.url4.result",
                {"body": "x", "media_type": 123},
                sequence=2,
            )
        )

    with pytest.raises(sf.ExecutionError, match="severity_text"):
        _RunState(URL4).accept(
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
        _RunState(URL4).accept(
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
        _RunState(URL4).accept(
            frame(
                "ai.url4.terminated",
                {"status": "unknown", "error": None},
                sequence=1,
            )
        )
    with pytest.raises(sf.ExecutionError, match="permanent"):
        _RunState(URL4).accept(
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
# FEATURE: the control plane may warn an attached client about its own Run.
# STORY: as a researcher whose cache directive was overridden, I am told so, and the Run I
# am paying for keeps going.
#
# INVARIANT: only frames that mutate no _RunState may arrive unsequenced. Gap detection,
# event-id de-duplication, and the replay-order guarantee all live on the sequenced path.


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


def test_an_unsequenced_advisory_log_is_kept_out_of_the_ordered_stream(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _RunState(URL4)

    with caplog.at_level(logging.WARNING, logger="screamingface._engine.contract"):
        accepted = state.accept(_null_sequenced_log())

    assert accepted.event is None
    assert accepted.outcome is None
    assert accepted.replay_from is None
    # The notice reaches a human: it cannot become a public Event, because Event.sequence is
    # a mandatory positive integer and inventing one would pollute replay order.
    assert "cache policy fixed by first attach" in caplog.text
    # INVARIANT: an advisory frame must not disturb the sequence cursor. A following
    # sequence=1 frame is still the next contiguous Event, not a gap needing replay.
    following = state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    assert isinstance(following.event, sf.events.Started)
    assert following.replay_from is None


def test_an_advisory_log_with_omitted_sequence_keys_is_also_unsequenced() -> None:
    state = _RunState(URL4)

    accepted = state.accept(
        frame(
            "ai.url4.log",
            {"severity_number": 13, "severity_text": "WARN", "body": "notice"},
            sequence=None,
        )
    )

    assert accepted.event is None


def test_an_advisory_log_that_carries_a_sequence_keeps_the_ordered_path() -> None:
    state = _RunState(URL4)

    accepted = state.accept(
        frame(
            "ai.url4.log",
            {"severity_number": 9, "severity_text": "INFO", "body": "ordered"},
            sequence=1,
        )
    )

    assert isinstance(accepted.event, sf.events.Log)
    assert accepted.event.sequence == 1


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda data: data.__setitem__("severity_text", "TRACE"), "severity_text"),
        (lambda data: data.__setitem__("attributes", {"nested": {}}), "non-scalar"),
    ],
)
def test_an_unsequenced_advisory_log_is_still_validated(
    mutate: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    # INVARIANT: dropped from the Event stream is not the same as unvalidated. A malformed
    # advisory frame is still a broken Engine contract and must surface.
    payload = cast(dict[str, Any], json.loads(_null_sequenced_log()))
    mutate(cast(dict[str, Any], payload["data"]))

    with pytest.raises(sf.ExecutionError, match=expected):
        _RunState(URL4).accept(json.dumps(payload))


def test_an_unsequenced_advisory_log_still_validates_its_run_envelope() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    payload = cast(dict[str, Any], json.loads(_null_sequenced_log()))
    payload["subject"] = "run_2"

    with pytest.raises(sf.ExecutionError, match="changed run subject"):
        state.accept(json.dumps(payload))


def test_a_sequenced_frame_missing_only_its_sequencetype_is_still_rejected() -> None:
    # INVARIANT: the discriminator is the presence of "sequence" ALONE. Keying on both fields
    # would reclassify this frame as advisory and silently skip the started handler.
    payload = cast(dict[str, Any], json.loads(frame("ai.url4.started", {"url4": URL4}, sequence=1)))
    del payload["sequencetype"]

    with pytest.raises(sf.ExecutionError, match="Integer semantics"):
        _RunState(URL4).accept(json.dumps(payload))


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        ("ai.url4.started", {"url4": URL4}),
        ("ai.url4.result", {"body": "{}", "media_type": "application/json"}),
        ("ai.url4.terminated", {"status": "succeeded", "error": None}),
        ("ai.url4.span", {"name": "n", "gen_ai.operation.name": "chat"}),
    ],
)
def test_unsequenced_lifecycle_frames_are_still_rejected(
    event_type: str,
    data: dict[str, object],
) -> None:
    # INVARIANT: a lifecycle frame may never travel out of band. An unsequenced terminated
    # would build an outcome from a stream never checked for gaps; an unsequenced cost.usage
    # would corrupt the billing total the user reads in their Report.
    with pytest.raises(sf.ExecutionError, match="sequence"):
        _RunState(URL4).accept(frame(event_type, data, sequence=None))


# FEATURE: deliver large results in full instead of cutting them off at 1 MiB (OME-892).
# A result frame may carry an artifact claim ticket instead of an inline body; the state
# machine surfaces it on the outcome for the transport to redeem before anyone decodes it.

_SHA = "9f" * 32


def _artifact_data(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "body": None,
        "media_type": None,
        "artifact": {"id": _SHA, "size_bytes": 11, "sha256": _SHA},
    }
    value.update(overrides)
    return value


def test_state_decodes_an_artifact_result() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    state.accept(frame("ai.url4.result", _artifact_data(), sequence=2))
    terminated = state.accept(
        frame("ai.url4.terminated", {"status": "succeeded", "error": None}, sequence=3)
    )

    outcome = terminated.outcome
    assert outcome is not None
    # INVARIANT: the raw outcome carries the UNREDEEMED ticket — result_body stays None
    # until the transport fetches and verifies; nothing downstream may guess at content.
    assert outcome.result_body is None
    assert outcome.artifact is not None
    assert outcome.artifact.id == _SHA
    assert outcome.artifact.size_bytes == 11
    assert outcome.artifact.sha256 == _SHA


@pytest.mark.parametrize(
    "artifact",
    [
        {"id": "../etc/passwd", "size_bytes": 11, "sha256": "9f" * 32},
        {"id": "9f" * 32, "size_bytes": "11", "sha256": "9f" * 32},
        {"id": "9f" * 32, "size_bytes": 11},
        "not a mapping",
    ],
)
def test_state_rejects_malformed_artifact_references(artifact: object) -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    with pytest.raises(ExecutionError):
        state.accept(frame("ai.url4.result", {"body": None, "artifact": artifact}, sequence=2))


def test_state_rejects_a_result_with_neither_body_nor_artifact() -> None:
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    with pytest.raises(ExecutionError):
        state.accept(frame("ai.url4.result", {"body": None, "media_type": None}, sequence=2))


def test_state_decodes_span_cache_provenance() -> None:
    accepted = _RunState(URL4).accept(
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

    assert isinstance(accepted.event, sf.events.Span)
    assert accepted.event.cache_status == "hit"
    assert accepted.event.cache_reason == "exact_match"


def test_state_rejects_unknown_span_cache_status() -> None:
    with pytest.raises(ExecutionError, match="cache_status"):
        _RunState(URL4).accept(
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
def test_state_rejects_non_scalar_span_cache_status(cache_status: object) -> None:
    """INVARIANT: malformed JSON stays inside the Client's ExecutionError boundary."""

    with pytest.raises(ExecutionError, match="cache_status"):
        _RunState(URL4).accept(
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
