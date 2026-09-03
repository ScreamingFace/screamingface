"""Trap 1: the sweep must never reclaim the run queue (OME-1088).

`_sweep_orphans` deletes any stream `owns_stream()` accepts, and it runs on every runner pod
and control-plane replica whenever the store is exhausted. The queue is the durable substrate
an accepted run may not be lost from — if a sweep ever reclaimed it, every queued run would
vanish with it. It is named outside the per-run prefix AND excluded explicitly.
"""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from nats.js import JetStreamContext

from screamingface_engine.adapters.jetstream import JetStreamConsumer
from screamingface_engine.subjects import RUN_QUEUE_STREAM, owns_stream, stream_for


class _FakeJetStream:
    def __init__(self, infos: list[Any]) -> None:
        self._infos = infos
        self.deleted: list[str] = []

    async def streams_info(self, offset: int = 0) -> list[Any]:
        return list(self._infos)[offset:]

    async def delete_stream(self, name: str) -> bool:
        self.deleted.append(name)
        return True


def _info(name: str, *, messages: int, last_seq: int) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(name=name),
        state=SimpleNamespace(messages=messages, last_seq=last_seq),
    )


def _consumer(js: _FakeJetStream) -> JetStreamConsumer:
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, js)  # noqa: SLF001
    return stream


def test_owns_stream_refuses_the_queue_name() -> None:
    """The explicit exclusion: even though `url4-runq` does not start with `url4-cloud_`, the
    queue is named AND refused, so a future rename of either side cannot re-arm the sweep."""
    assert not owns_stream(RUN_QUEUE_STREAM)


@pytest.mark.asyncio
async def test_a_sweep_with_the_queue_present_leaves_it_alive() -> None:
    """The queue stream is shaped exactly like a reclaimable orphan (emptied, `last_seq > 0`),
    so WITHOUT the exclusion the sweep would delete it. It must survive."""
    js = _FakeJetStream(
        infos=[
            _info(RUN_QUEUE_STREAM, messages=0, last_seq=42),
            _info(stream_for("dead"), messages=0, last_seq=9),
        ]
    )

    await _consumer(js)._sweep_orphans(cast(JetStreamContext, js))  # noqa: SLF001

    assert RUN_QUEUE_STREAM not in js.deleted
    assert js.deleted == [stream_for("dead")]


def test_owns_stream_follows_the_configured_queue_name() -> None:
    """The exclusion must follow the CONFIGURED stream name, not the default constant
    (review follow-up): the name is a Settings field, and an operator who renames the
    queue must not have the sweep re-armed against the renamed stream by a stale constant
    — that deletes the one stream an accepted run may not be lost from.

    V-9: the names are `url4-cloud_`-shaped, the only shape where the exclusion does
    REAL work — `owns_stream` refuses every other name at the prefix check anyway, so an
    earlier draft asserting on "prod-runq" pinned the signature, not the behaviour.
    (`Settings` itself refuses a `url4-cloud_` queue name at startup — the V-8 validator —
    so this function-level exclusion is the defence-in-depth layer for callers that do
    not come from Settings.)"""
    # The configured queue is excluded by NAME, even in the sweepable prefix.
    assert not owns_stream("url4-cloud_myqueue", run_queue_stream="url4-cloud_myqueue")
    # The exclusion is EXACT-match: a sibling in the prefix is still owned — and swept.
    assert owns_stream("url4-cloud_other", run_queue_stream="url4-cloud_myqueue")
    # The default constant is still excluded for callers that pass nothing.
    assert not owns_stream(RUN_QUEUE_STREAM)
    # A non-prefixed rename needs no exclusion — the prefix check refuses it.
    assert not owns_stream("prod-runq", run_queue_stream="prod-runq")


@pytest.mark.asyncio
async def test_a_sweep_with_a_renamed_queue_leaves_it_alive() -> None:
    """The full path, not just the predicate: a connection configured with a renamed queue
    stream must skip it during reclamation exactly as it skips the default name. V-9: the
    renamed queue is `url4-cloud_`-shaped — WITHOUT the exclusion the sweep would accept
    it on the prefix check alone and delete it (a "prod-runq" rename proved nothing: the
    prefix check refuses it whether wired or not). Its `url4-cloud_` sibling is swept."""
    js = _FakeJetStream(
        infos=[
            _info("url4-cloud_myqueue", messages=0, last_seq=42),
            _info("url4-cloud_orphan", messages=0, last_seq=7),
            _info(stream_for("dead"), messages=0, last_seq=9),
        ]
    )
    stream = JetStreamConsumer("nats://unused:4222", run_queue_stream="url4-cloud_myqueue")
    stream._js = cast(JetStreamContext, js)  # noqa: SLF001

    await stream._sweep_orphans(cast(JetStreamContext, js))  # noqa: SLF001

    assert js.deleted == ["url4-cloud_orphan", stream_for("dead")]
