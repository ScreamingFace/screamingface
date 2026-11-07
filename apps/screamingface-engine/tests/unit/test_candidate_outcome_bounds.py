"""E5 P1 spec R3, R4: an outcome the registry cannot store is refused before it is published,
and no message can stop the writer.

FEATURE: first-class Runs (OME-1785).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from screamingface_engine.adapters.memory import (
    InMemoryCandidateOutcomeStream,
    OutcomeStreamFull,
)
from screamingface_engine.candidate_outcomes import (
    ERROR_CODE_LENGTH,
    UNSTORABLE_ERROR_CODE,
    CandidateOutcome,
    decode_outcome,
    encode_outcome,
    storable_error_code,
)

T0 = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)


def test_a_deeply_nested_payload_is_malformed_not_fatal() -> None:
    payload = b"[" * 100_000 + b"]" * 100_000

    with pytest.raises(ValueError, match="JSON object"):
        decode_outcome(payload)


def test_a_topic_with_a_nul_is_malformed() -> None:
    body = json.loads(encode_outcome("topic", CandidateOutcome("succeeded")))
    body["topic"] = "to\x00pic"

    with pytest.raises(ValueError, match="NUL"):
        decode_outcome(json.dumps(body).encode())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cost_usd": Decimal("1E12")},
        {"cost_usd": Decimal("999999999999.9999999999999")},  # rounds up onto the bound
        {"cost_usd": Decimal("1E+999999999999999999")},  # too large to round at all
        {"error_code": "x" * (ERROR_CODE_LENGTH + 1)},
        {"error_code": "bad\x00code"},
        {"finished_at": datetime(2026, 11, 5, 9, 30)},  # noqa: DTZ001 - naive on purpose
    ],
    ids=[
        "cost-overflow",
        "cost-rounds-over",
        "cost-huge-exponent",
        "long-code",
        "nul-code",
        "naive-time",
    ],
)
def test_an_outcome_the_registry_cannot_store_is_refused(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        CandidateOutcome("failed", **kwargs)  # type: ignore[arg-type]


def test_an_unstorable_error_code_is_named_not_truncated() -> None:
    assert storable_error_code("provider_error") == "provider_error"
    assert storable_error_code("x" * (ERROR_CODE_LENGTH + 1)) == UNSTORABLE_ERROR_CODE
    assert storable_error_code("bad\x00code") == UNSTORABLE_ERROR_CODE
    assert storable_error_code(None) is None


def test_the_producers_end_time_travels_with_the_outcome() -> None:
    sent = CandidateOutcome("succeeded", cost_usd=Decimal("0.5"), finished_at=T0)

    _, received = decode_outcome(encode_outcome("topic", sent))

    assert (received, received.finished_at) == (sent, T0)


def test_an_outcome_without_an_end_time_is_malformed() -> None:
    body = json.loads(encode_outcome("topic", CandidateOutcome("succeeded")))
    del body["finished_at"]

    with pytest.raises(ValueError, match="finished_at"):
        decode_outcome(json.dumps(body).encode())


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", ["", "to\x00pic"], ids=["empty", "nul"])
async def test_the_in_memory_stream_refuses_a_topic_the_codec_refuses(topic: str) -> None:
    with pytest.raises(ValueError, match="topic"):
        await InMemoryCandidateOutcomeStream().publish(topic, CandidateOutcome("succeeded"))
    with pytest.raises(ValueError, match="topic"):
        encode_outcome(topic, CandidateOutcome("succeeded"))


@pytest.mark.asyncio
async def test_a_full_in_memory_stream_refuses_new_outcomes() -> None:
    stream = InMemoryCandidateOutcomeStream(max_outcomes=2)
    await stream.publish("a", CandidateOutcome("succeeded"))
    await stream.publish("b", CandidateOutcome("succeeded"))

    with pytest.raises(OutcomeStreamFull):
        await stream.publish("c", CandidateOutcome("succeeded"))


@pytest.mark.asyncio
async def test_the_in_memory_stream_drops_an_outcome_past_its_max_age() -> None:
    stream = InMemoryCandidateOutcomeStream(max_age_s=0.05)
    await stream.publish("old", CandidateOutcome("succeeded"))
    await asyncio.sleep(0.1)
    await stream.publish("new", CandidateOutcome("succeeded"))

    delivery = await asyncio.wait_for(anext(stream.consume()), 1)

    assert delivery.topic == "new"


def test_a_cost_too_large_to_round_is_malformed_on_the_wire() -> None:
    """WHY `ValueError`: it is what the writer drops as malformed; any other error would stop it."""
    body = json.loads(encode_outcome("topic", CandidateOutcome("succeeded")))
    body["cost_usd"] = "1E+999999999999999999"

    with pytest.raises(ValueError, match="cost"):
        decode_outcome(json.dumps(body).encode())
