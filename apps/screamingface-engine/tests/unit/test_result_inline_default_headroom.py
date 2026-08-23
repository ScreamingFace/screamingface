"""The default inline cap must clear the broker's frame ceiling AFTER envelope inflation.

FEATURE: finished runs survive their final publish (OME-949).

INVARIANT: whatever rides inline is re-published inside the run-result CloudEvent envelope,
so the shipped default cap plus the envelope's cost must stay under the broker's default
1 MiB `max_payload`. With the cap equal to that limit (the pre-OME-949 default), a raw
result in roughly (0.94 MiB, 1.00 MiB] passed the inline gate and was then REJECTED at
publish — killing the run at its final frame, after every model call had been paid for.
Measured on real DRACO aggregates, the envelope (ids, source, subject, time, JSON
re-escaping) inflates the frame ~6% over the raw result: 619,026 raw → 657,732 published.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from screamingface_engine import job_env
from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.runner.executor import Url4Executor
from url4.io.static import StaticIOLayer
from url4.streaming.interfaces import Completed

# The NATS default max_payload; the broker on the shared cluster runs exactly this.
BROKER_MAX_PAYLOAD_BYTES = 1_048_576
# Measured envelope inflation of the published frame over the raw UTF-8 result (OME-949
# diagnosis): 619,026-byte result published as a 657,732-byte frame ≈ 6.2%.
ENVELOPE_INFLATION = 1.06
# A raw result in the pre-fix dead window: above the old (equal-to-broker) inline cap's
# comfortable zone yet under it — the size class that used to go inline and die at publish.
RESULT_BYTES = int(0.6 * 1024 * 1024)  # 629,146 — inside (512 KiB, 1 MiB)


class _FixedResultNode:
    """Resolves to exactly `RESULT_BYTES` ASCII bytes, so the cap can be aimed precisely."""

    deps: dict = {}

    async def resolve(self, inputs: object, ctx: object) -> str:
        return "X" * RESULT_BYTES


def test_default_inline_cap_leaves_broker_headroom() -> None:
    """The shipped default plus the envelope's cost clears the broker ceiling."""
    # WHY pin the exact value: a future bump back toward 1 MiB reintroduces the dead
    # window silently — the gate below would pass at exactly 990,651 bytes, so the pin
    # forces the next reader to re-do this arithmetic consciously.
    assert job_env.DEFAULT_RESULT_INLINE_CAP_BYTES == 524_288
    inflated = job_env.DEFAULT_RESULT_INLINE_CAP_BYTES * ENVELOPE_INFLATION
    assert inflated <= BROKER_MAX_PAYLOAD_BYTES


@pytest.mark.asyncio
async def test_result_in_dead_window_spills_at_default_caps(tmp_path: Path) -> None:
    """A ~0.6 MiB result — inline under the old default, fatal at publish — now spills.

    STORY: as a benchmark operator, I want a run whose aggregate lands just under the old
    cap to finish, instead of failing at its final frame after the full model spend.
    """
    store = FilesystemArtifactStore(tmp_path / "spill")
    # No explicit result_cap: the executor runs on the SHIPPED default (OME-949's value).
    executor = Url4Executor(StaticIOLayer(), artifact_store=store)

    frames = [frame async for frame in executor.execute(cast("str", _FixedResultNode()))]

    completed = frames[-1]
    assert isinstance(completed, Completed)
    assert completed.result.body is None
    ref = completed.result.artifact
    assert ref is not None
    assert ref.size_bytes == RESULT_BYTES
    # The complete body is redeemable at the address the ticket names.
    assert (tmp_path / "spill" / ref.id).read_bytes() == b"X" * RESULT_BYTES
