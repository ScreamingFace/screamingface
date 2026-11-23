"""P8 and C2.1: the traceparent of each chat call has the W3C shape that url4 accepts."""

from __future__ import annotations

import re

import httpx
from _chat_engine import ok, recording_client

import screamingface as sf
from screamingface._inference.trace import new_trace_context

TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-01$")


def test_a_new_trace_context_has_the_w3c_shape() -> None:
    context = new_trace_context()
    match = TRACEPARENT.match(context.traceparent)

    assert match is not None
    assert match.group(1) == context.trace_id
    assert match.group(2) == context.span_id
    assert context.trace_id != "0" * 32
    assert context.span_id != "0" * 16
    assert context.headers() == {"traceparent": context.traceparent}


def test_two_contexts_differ() -> None:
    assert new_trace_context().trace_id != new_trace_context().trace_id


def test_the_chat_request_carries_a_w3c_traceparent() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        sf.InferenceClient("openrouter/a", client=client).chat.completions.create("Hello")

    assert TRACEPARENT.match(requests[0].headers["traceparent"]) is not None
