"""MI-56: the final step of a reply tells a gateway cache hit (RR-S14, SDK part).

FEATURE: SDK model inference (docs/spec/2026-11-17-engine-openai-chat-endpoint, RR-S14).
WHY: the Engine sends final_step.cached only when a reply came from the gateway cache. The SDK
reads the key when it is true and keeps the field False otherwise.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from _chat_engine import recording_client
from _chat_frames import engine_stream
from _chat_stream import engine_for

from screamingface._inference.frames import chunk_from_payload
from screamingface.chat_completion import FinalStep


def _info(**final_step: Any) -> dict[str, Any]:
    """The screamingface object of a reply whose final step has these keys."""

    return {
        "status": "answered",
        "abstain_reason": None,
        "cost_usd": "0",
        "trace_id": None,
        "final_step": {
            "binding": "model_1",
            "model": "openrouter/a",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            **final_step,
        },
    }


def _last_payload(final_step: dict[str, Any]) -> dict[str, Any]:
    """The last chunk payload of a reply, which carries the screamingface object."""

    payloads = engine_stream(
        {"role": "assistant", "content": "Hi"}, "stop", screamingface=_info(**final_step)
    )
    return payloads[-1]


def test_final_step_cached_is_read_when_true() -> None:
    chunk = chunk_from_payload(_last_payload({"cached": True}))

    assert chunk.screamingface is not None
    assert chunk.screamingface.final_step is not None
    assert chunk.screamingface.final_step.cached is True
    assert chunk.screamingface.final_step.to_dict()["cached"] is True


@pytest.mark.parametrize("final_step", [{}, {"cached": False}], ids=["absent", "false"])
def test_final_step_cached_is_false_and_not_dumped_when_absent_or_false(
    final_step: dict[str, Any],
) -> None:
    chunk = chunk_from_payload(_last_payload(final_step))

    assert chunk.screamingface is not None
    assert chunk.screamingface.final_step is not None
    assert chunk.screamingface.final_step.cached is False
    assert "cached" not in chunk.screamingface.final_step.to_dict()


def test_final_step_default_is_not_cached() -> None:
    step = FinalStep(binding="b", model="m", usage=None)

    assert step.cached is False
    assert step.to_dict() == {"binding": "b", "model": "m", "usage": None}


def test_reply_of_a_cache_hit_has_cached() -> None:
    requests: list[httpx.Request] = []
    payloads = engine_stream(
        {"role": "assistant", "content": "Hi"},
        "stop",
        screamingface=_info(cached=True),
    )
    with recording_client(engine_for(payloads), requests) as client:
        reply = client.chat.completions.create("Hi", model="openrouter/a")

    assert reply.screamingface.final_step is not None
    assert reply.screamingface.final_step.cached is True
    screamingface = cast(dict[str, Any], reply.to_dict()["screamingface"])
    assert screamingface["final_step"]["cached"] is True
