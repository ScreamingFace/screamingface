"""The usage and cost shapes agree across observe, dag and the wire contract (audit HY-8).

STORY: as a maintainer I add a token class or a cache field in one place, and a test
tells me every other place that must change with it.

The seam is deliberate: ``url4.streaming`` must not import the engine, and
``url4.observe`` must not import pydantic. So the shapes are written by hand in three
places, and nothing but this test keeps them in step:

- ``ExecutionContext.report_usage`` builds :class:`url4.observe.Usage` POSITIONALLY, so its
  keyword arguments must be the event's fields, in the same order, and each argument must
  land in its own field (a swap in the call body keeps the signature right).
- ``ExecutionContext.report_response`` must take every :class:`url4.observe.ModelResponse`
  field.
- The token classes on :class:`url4.observe.Usage` are the wire
  :class:`url4.streaming.protocol.TokenUsage` fields.
- ``cache_status`` has one vocabulary on ``ModelResponse`` and on the wire ``SpanData``.
"""

from __future__ import annotations

import dataclasses
import inspect
import typing
from collections.abc import Callable
from decimal import Decimal

from url4.dag._context import _ObsState
from url4.dag.node import ExecutionContext
from url4.io.static import StaticIOLayer
from url4.observe import ModelResponse, ObservationEvent, Usage
from url4.streaming.protocol import SpanData, TokenUsage


def _keyword_names(function: Callable[..., object]) -> list[str]:
    parameters = inspect.signature(function).parameters.values()
    return [p.name for p in parameters if p.kind is inspect.Parameter.KEYWORD_ONLY]


def _event_fields(event: type) -> list[str]:
    return [field.name for field in dataclasses.fields(event) if field.name != "span_id"]


def _literal_values(annotation: object) -> set[object]:
    return {
        value
        for arg in typing.get_args(annotation)
        if typing.get_origin(arg) is typing.Literal
        for value in typing.get_args(arg)
    }


def test_report_usage_takes_the_usage_fields_in_order() -> None:
    assert _keyword_names(ExecutionContext.report_usage) == _event_fields(Usage)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


def test_report_usage_puts_each_argument_in_its_own_field() -> None:
    # One distinct value per argument: a swap of two same-typed arguments in the call body
    # moves a value into the wrong field, and this sees it.
    recorder = _Recorder()
    ctx = ExecutionContext(
        StaticIOLayer({}), _obs=_ObsState(recorder, "trace"), _current_span_id="span"
    )
    ctx.report_usage(
        provider="p",
        model="m",
        input_tokens=1,
        output_tokens=2,
        response_model="rm",
        cache_read_tokens=3,
        cache_creation_tokens=4,
        reasoning_tokens=5,
        cost_usd=Decimal("0.06"),
    )
    values = {
        "provider": "p",
        "model": "m",
        "input_tokens": 1,
        "output_tokens": 2,
        "response_model": "rm",
        "cache_read_tokens": 3,
        "cache_creation_tokens": 4,
        "reasoning_tokens": 5,
        "cost_usd": Decimal("0.06"),
    }
    assert list(values) == _event_fields(Usage)
    [event] = recorder.events
    assert isinstance(event, Usage)
    assert {name: getattr(event, name) for name in values} == values
    assert event.span_id == "span"


def test_report_response_takes_every_model_response_field() -> None:
    assert set(_keyword_names(ExecutionContext.report_response)) == set(
        _event_fields(ModelResponse)
    )


def test_usage_token_classes_are_the_wire_token_classes() -> None:
    tokens = {name for name in _event_fields(Usage) if name.endswith("_tokens")}
    assert tokens == set(TokenUsage.model_fields)


def test_cache_status_has_one_vocabulary() -> None:
    hints = typing.get_type_hints(ModelResponse)
    engine = _literal_values(hints["cache_status"])
    wire = _literal_values(SpanData.model_fields["cache_status"].annotation)
    assert engine == wire == {"hit", "miss", "bypass"}
