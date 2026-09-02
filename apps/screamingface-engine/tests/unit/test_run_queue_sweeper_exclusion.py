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
