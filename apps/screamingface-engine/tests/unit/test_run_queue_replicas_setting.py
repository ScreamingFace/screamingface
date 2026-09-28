"""The run queue's replica count is configuration, not a constant (OME-1088).

A single-node broker — which is what the chart's own bundled NATS subchart ships, and what
local dev and the CI conformance job run — refuses `replicas > 1` outright with
`ServerError 10074` ("replicas > 1 not supported in non-clustered mode"). That error is not a
`BadRequestError`, so `ensure_stream` does not tolerate it: it escapes into the worker's claim
loop, which logs and retries forever, and every run is refused. The seam
(`RunQueue(replicas=...)`) existed from the start but no composition root passed it and no
setting fed it, so the constraint was expressible only in tests.

This file pins the setting half: the field, its single-node-safe default, its env transport,
its boundary, and that the queue actually declares the stream with what it was given.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from screamingface_engine import runner_queue
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueue


class _RecordingJetStream:
    """The one call this file cares about — `add_stream` — recorded verbatim.

    Self-contained rather than imported from a sibling test module: the append-only rule
    means each cycle brings its own fixtures, so a later edit here cannot break a prior file.
    """

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    async def add_stream(self, **kwargs: Any) -> object:
        self.added.append(kwargs)
        return object()


def _queue_with(fake: _RecordingJetStream, **kwargs: Any) -> RunQueue:
    queue = RunQueue("nats://unused:4222", **kwargs)

    async def _fake_jetstream() -> _RecordingJetStream:
        return fake

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return queue


def test_the_replica_setting_defaults_to_the_module_constant() -> None:
    """INVARIANT: the setting and the constant cannot drift — the constant IS the default, so a
    deployment that states nothing gets exactly what `RunQueue` would have used on its own."""
    assert Settings().run_queue_replicas == runner_queue.QUEUE_REPLICAS


def test_the_default_replica_count_is_single_node_safe() -> None:
    """The invariant this unit exists to protect: a deployment that configures NOTHING must be
    able to declare its queue on the single-node broker the chart actually bundles.

    WHY 1 and not the spec's 3 (owner decision, 2026-09-03): the per-run event streams are
    already declared at JetStream's default of one replica, so a 3-replica queue on an
    otherwise 1-replica bus hardens only the queued-not-started window. Multi-replica
    durability arrives with clustering, under OME-1093.
    """
    assert Settings().run_queue_replicas == 1


def test_the_environment_sets_the_replica_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chart's transport: `env_prefix` + the field name, uppercased. A clustered
    deployment raises this without a code change."""
    monkeypatch.setenv("URL4_CLOUD_RUN_QUEUE_REPLICAS", "3")
    assert Settings().run_queue_replicas == 3


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_replica_count_below_one_is_refused(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Boundary: a stream has at least one replica. Refusing at startup beats a broker error
    on the first publish, which surfaces as the same retry-forever claim loop this unit fixes."""
    monkeypatch.setenv("URL4_CLOUD_RUN_QUEUE_REPLICAS", value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.asyncio
async def test_the_queue_declares_the_stream_with_the_configured_replica_count() -> None:
    """The seam is honoured end to end: what the composition root passes is what reaches the
    broker. Pinned at 3 (not the default) so the test fails if the parameter is ignored."""
    fake = _RecordingJetStream()
    await _queue_with(fake, replicas=3).ensure_stream()
    assert fake.added[0]["num_replicas"] == 3


@pytest.mark.asyncio
async def test_the_queue_falls_back_to_the_constant_when_no_replica_count_is_given() -> None:
    """An unconfigured `RunQueue` declares the single-node-safe default, so a caller that
    forgets the parameter cannot resurrect the retry-forever failure."""
    fake = _RecordingJetStream()
    await _queue_with(fake).ensure_stream()
    assert fake.added[0]["num_replicas"] == runner_queue.QUEUE_REPLICAS
