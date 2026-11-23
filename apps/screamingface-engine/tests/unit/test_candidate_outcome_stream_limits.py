"""E5 P1 spec R4, R6, R11: a live outcome stream may be widened, never narrowed below this code,
and no outcome larger than an outcome can be is published or written.

FEATURE: first-class Runs (OME-1785).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine.adapters.candidate_outcomes_jetstream import (
    CandidateOutcomesStreamConfig,
    CandidateOutcomesStreamConfigError,
    JetStreamCandidateOutcomeStream,
)
from screamingface_engine.candidate_outcomes import MAX_OUTCOME_BYTES, decode_outcome


def _stream_over(live: Any) -> tuple[JetStreamCandidateOutcomeStream, list[Any]]:
    updated: list[Any] = []
    stream = JetStreamCandidateOutcomeStream("nats://unused:4222")

    class _JetStream:
        async def stream_info(self, name: str) -> object:
            return SimpleNamespace(config=live)

        async def update_stream(self, config: Any) -> None:
            updated.append(config)

        async def add_consumer(self, name: str, config: object) -> None:
            return None

    async def _jetstream() -> _JetStream:
        return _JetStream()

    stream._jetstream = _jetstream  # type: ignore[assignment,method-assign]  # noqa: SLF001
    return stream, updated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [("max_age", 60.0), ("max_bytes", 1024), ("max_msg_size", 128)],
)
async def test_a_live_stream_narrower_than_this_code_is_refused(field: str, value: float) -> None:
    live = CandidateOutcomesStreamConfig().stream_config()
    setattr(live, field, value)
    stream, _ = _stream_over(live)

    with pytest.raises(CandidateOutcomesStreamConfigError, match=field):
        await stream.ensure_stream()


@pytest.mark.asyncio
async def test_a_wider_or_unlimited_live_stream_is_accepted() -> None:
    live = CandidateOutcomesStreamConfig().stream_config()
    live.max_age = 0  # unlimited
    live.max_bytes = 1024**3
    stream, updated = _stream_over(live)

    await stream.ensure_stream()

    assert updated == []


@pytest.mark.asyncio
async def test_startup_applies_this_codes_message_size_cap() -> None:
    live = CandidateOutcomesStreamConfig().stream_config()
    live.max_msg_size = -1
    stream, updated = _stream_over(live)

    await stream.ensure_stream(update=True)

    [config] = updated
    assert config.max_msg_size == MAX_OUTCOME_BYTES


def test_an_outcome_larger_than_the_cap_is_malformed() -> None:
    with pytest.raises(ValueError, match="at most"):
        decode_outcome(b" " * (MAX_OUTCOME_BYTES + 1))
