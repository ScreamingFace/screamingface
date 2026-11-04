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
        {"error_code": "x" * (ERROR_CODE_LENGTH + 1)},
        {"error_code": "bad\x00code"},
        {"finished_at": datetime(2026, 11, 5, 9, 30)},  # noqa: DTZ001 - naive on purpose
    ],
    ids=["cost-overflow", "long-code", "nul-code", "naive-time"],
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
async def test_the_in_memory_stream_refuses_an_outcome_with_no_topic() -> None:
    with pytest.raises(ValueError, match="topic"):
        await InMemoryCandidateOutcomeStream().publish("", CandidateOutcome("succeeded"))


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
