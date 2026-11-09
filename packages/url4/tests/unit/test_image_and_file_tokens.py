"""Image and file input tokens ride `Usage` and the wire `TokenUsage` as an OPTIONAL class.

FEATURE: image/file token accounting (OME-1744, engine half of OME-1546). The gateway states how
much of `prompt_tokens` was image or document input; the run cost carries it on.
STORY: as a researcher running a vision benchmark, the run's cost frames say how much of my input
was media — and say "unknown" when the provider did not break it down, never a false zero.

INVARIANT under test: unknown is `None` and is OMITTED from the wire frame. The key appears only
when a count is known, so every text-only frame stays byte-identical to the pre-OME-1744 encoding.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from url4.dag._context import _ObsState
from url4.dag.node import ExecutionContext
from url4.io.static import StaticIOLayer
from url4.observe import ObservationEvent, Usage
from url4.streaming.protocol import TokenUsage

_KEY = "gen_ai.usage.image_and_file_tokens"

# The pre-OME-1744 encoding of a text-only `TokenUsage`, captured from the code before the field
# existed. A LITERAL on purpose: recomputing it would agree with any regression.
_TEXT_ONLY_JSON = (
    '{"gen_ai.usage.input_tokens":150,"gen_ai.usage.output_tokens":30,'
    '"gen_ai.usage.cache_read_tokens":8,"gen_ai.usage.cache_creation_tokens":4,'
    '"gen_ai.usage.reasoning_tokens":3}'
)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


def _text_only() -> TokenUsage:
    return TokenUsage(
        input_tokens=150,
        output_tokens=30,
        cache_read_tokens=8,
        cache_creation_tokens=4,
        reasoning_tokens=3,
    )


def test_usage_defaults_the_image_class_to_unknown() -> None:
    usage = Usage("span", "p", "m", 1, 2)

    assert usage.image_and_file_tokens is None


def test_report_usage_forwards_the_image_class() -> None:
    recorder = _Recorder()
    ctx = ExecutionContext(
        StaticIOLayer({}), _obs=_ObsState(recorder, "trace"), _current_span_id="span"
    )

    ctx.report_usage(
        provider="p", model="m", input_tokens=10, output_tokens=1, image_and_file_tokens=7
    )

    [event] = recorder.events
    assert isinstance(event, Usage)
    assert event.image_and_file_tokens == 7


def test_report_usage_left_silent_reports_the_image_class_unknown_not_zero() -> None:
    recorder = _Recorder()
    ctx = ExecutionContext(
        StaticIOLayer({}), _obs=_ObsState(recorder, "trace"), _current_span_id="span"
    )

    ctx.report_usage(provider="p", model="m", input_tokens=10, output_tokens=1)

    [event] = recorder.events
    assert isinstance(event, Usage)
    assert event.image_and_file_tokens is None


def test_a_text_only_token_usage_encodes_byte_identically_to_before() -> None:
    assert _text_only().model_dump_json(by_alias=True) == _TEXT_ONLY_JSON


def test_an_unknown_image_class_is_omitted_from_the_wire() -> None:
    usage = _text_only()

    assert usage.image_and_file_tokens is None
    assert _KEY not in usage.model_dump(by_alias=True)


def test_a_known_image_class_is_on_the_wire_under_its_gen_ai_key() -> None:
    usage = TokenUsage(input_tokens=150, image_and_file_tokens=120)

    assert usage.model_dump(by_alias=True)[_KEY] == 120


@pytest.mark.parametrize("count", [0, 1, 120])
def test_a_known_image_class_round_trips_including_a_real_zero(count: int) -> None:
    # A known 0 ("the breakdown had no media") is a different claim from unknown, so it must
    # survive the round trip rather than be dropped like `None`.
    encoded = TokenUsage(input_tokens=150, image_and_file_tokens=count).model_dump_json(
        by_alias=True
    )

    assert f'"{_KEY}":{count}' in encoded
    assert TokenUsage.model_validate_json(encoded).image_and_file_tokens == count


def test_a_frame_without_the_key_decodes_as_unknown() -> None:
    assert TokenUsage.model_validate_json(_TEXT_ONLY_JSON).image_and_file_tokens is None


def test_the_wire_still_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        TokenUsage.model_validate({"gen_ai.usage.video_tokens": 1})
