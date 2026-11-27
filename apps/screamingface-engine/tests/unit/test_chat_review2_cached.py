"""RR-S14 / RR-19: the final step of a gateway cache hit is marked `cached` (review round 2).

FEATURE: tool-calls §3.2. A final model step served from the gateway cache has zero usage and
`cached` true. The answer and the stream give the key `cached` only when it is true.
"""

from __future__ import annotations

import json

import pytest
from _chat_app import answered, body, chat_app, chat_result, post
from _chat_stream import data_payloads, stream_body

from screamingface_engine.benchmarks.contract import (
    OperationOutput,
    decode_candidate_invocation_record,
    encode_candidate_invocation,
)
from screamingface_engine.chat.result import FinalStep, decode_chat_result, encode_chat_result
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    OperationCache,
    OperationUsage,
)
from screamingface_engine.world.chat_turn import chat_result_from_invocation


def _invocation(output: str, finish_reason: str | None, refusal: str | None = None, **kw):
    return decode_candidate_invocation_record(
        encode_candidate_invocation(output, finish_reason, refusal, **kw)
    )


def _accounting(hits: int, misses: int, tokens: int) -> OperationAccounting:
    return OperationAccounting(
        provider="prov",
        request_model="prov/a",
        response_model="prov/a",
        usage=OperationUsage(
            input_tokens=tokens,
            output_tokens=tokens,
            cache_read_tokens=None,
            cache_creation_tokens=None,
            reasoning_tokens=None,
            cost_usd=None,
        ),
        provider_latency_ms=None,
        provider_attempts=None,
        cache=OperationCache(hits=hits, misses=misses, bypasses=0, unknown=0),
    )


def test_final_step_of_a_cache_hit_is_marked_in_the_record() -> None:
    result = chat_result_from_invocation(
        _invocation("Paris", "stop"),
        OperationOutput(
            operation_id="op_model_1",
            output="Paris",
            finish_reason="stop",
            accounting=_accounting(1, 0, 0),
        ),
        abstain_reason=None,
    )

    assert result.final_step is not None
    assert result.final_step.cached is True
    assert result.final_step.usage == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert decode_chat_result(encode_chat_result(result)) == result


def test_final_step_of_a_miss_is_not_marked_in_the_record() -> None:
    result = chat_result_from_invocation(
        _invocation("Paris", "stop"),
        OperationOutput(
            operation_id="op_model_1",
            output="Paris",
            finish_reason="stop",
            accounting=_accounting(0, 1, 5),
        ),
        abstain_reason=None,
    )

    assert result.final_step is not None
    assert result.final_step.cached is False


def test_a_record_without_the_cached_key_decodes_with_cached_false() -> None:
    result = chat_result_from_invocation(
        _invocation("Paris", "stop"),
        OperationOutput(
            operation_id="op_model_1",
            output="Paris",
            finish_reason="stop",
            accounting=_accounting(0, 1, 5),
        ),
        abstain_reason=None,
    )
    value = json.loads(encode_chat_result(result))
    del value["final_step"]["cached"]

    decoded = decode_chat_result(json.dumps(value).encode())

    assert decoded.final_step is not None
    assert decoded.final_step.cached is False


@pytest.mark.asyncio
async def test_final_step_of_a_cache_hit_is_marked_in_the_answer() -> None:
    final = FinalStep(
        binding="model_1",
        model="prov/a",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        cached=True,
    )
    ca = chat_app(answered(chat_result(final_step=final)))
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    assert resp.json()["screamingface"]["final_step"] == {
        "binding": "model_1",
        "model": "prov/a",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cached": True,
    }


@pytest.mark.asyncio
async def test_final_step_of_a_miss_has_no_cached_key() -> None:
    final = FinalStep(
        binding="model_1",
        model="prov/a",
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        cached=False,
    )
    ca = chat_app(answered(chat_result(final_step=final)))
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    assert "cached" not in resp.json()["screamingface"]["final_step"]


@pytest.mark.asyncio
async def test_stream_final_step_of_a_cache_hit_is_marked() -> None:
    final = FinalStep(
        binding="model_1",
        model="prov/a",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        cached=True,
    )
    ca = chat_app(answered(chat_result(final_step=final)))
    resp = await post(ca.app, stream_body())

    info = [
        p["screamingface"]
        for p in data_payloads(resp.content)
        if isinstance(p, dict) and "screamingface" in p
    ]
    assert info
    assert info[-1]["final_step"]["cached"] is True


@pytest.mark.asyncio
async def test_stream_final_step_of_a_miss_has_no_cached_key() -> None:
    final = FinalStep(
        binding="model_1",
        model="prov/a",
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        cached=False,
    )
    ca = chat_app(answered(chat_result(final_step=final)))
    resp = await post(ca.app, stream_body())

    info = [
        p["screamingface"]
        for p in data_payloads(resp.content)
        if isinstance(p, dict) and "screamingface" in p
    ]
    assert info
    assert "cached" not in info[-1]["final_step"]
