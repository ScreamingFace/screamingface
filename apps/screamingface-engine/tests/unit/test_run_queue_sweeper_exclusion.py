"""Trap 1: the legacy-stream purge must never reclaim the run queue or the events stream
(OME-1088). `purge_legacy_streams` deletes any stream `owns_stream()` accepts, and it is the
operator tool run once after the drained rollout to the shared `url4-events` stream. The queue
is the durable substrate an accepted run may not be lost from — if the purge ever reclaimed it,
every queued run would vanish with it. It is named outside the per-run prefix AND excluded
explicitly; `url4-events` itself is never `url4-cloud_`-shaped, so it is refused on the prefix
check alone.
"""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from nats.js import JetStreamContext

from screamingface_engine.adapters.jetstream import purge_legacy_streams
from screamingface_engine.subjects import EVENTS_STREAM, RUN_QUEUE_STREAM, owns_stream


class _FakeJetStream:
    def __init__(self, names: list[str]) -> None:
        self._infos: list[Any] = [SimpleNamespace(config=SimpleNamespace(name=n)) for n in names]
        self.deleted: list[str] = []

    async def streams_info(self, offset: int = 0) -> list[Any]:
        return list(self._infos)[offset:]

    async def delete_stream(self, name: str) -> bool:
        self.deleted.append(name)
        return True


def _legacy_stream_for(topic: str) -> str:
    # `stream_for` is gone with the per-run layout; the former layout's name is spelled out
    # literally here rather than reintroducing it as an import.
    return f"url4-cloud_{topic}"


def test_owns_stream_refuses_the_queue_name() -> None:
    """The explicit exclusion: even though `url4-runq` does not start with `url4-cloud_`, the
    queue is named AND refused, so a future rename of either side cannot re-arm the purge."""
    assert not owns_stream(RUN_QUEUE_STREAM)


@pytest.mark.asyncio
async def test_purge_legacy_streams_leaves_the_queue_and_events_stream_alive() -> None:
    """The queue and the shared events stream sit alongside every genuine legacy per-run
    stream on the broker; WITHOUT the exclusion the purge would delete the queue too (it is
    exactly the kind of stream `owns_stream` otherwise accepts once renamed into the prefix —
    see below). Both must survive; only the legacy per-run stream is swept."""
    js = _FakeJetStream(
        names=[RUN_QUEUE_STREAM, EVENTS_STREAM, _legacy_stream_for("dead")],
    )

    deleted = await purge_legacy_streams(cast(JetStreamContext, js), dry_run=False)

    assert RUN_QUEUE_STREAM not in js.deleted
    assert EVENTS_STREAM not in js.deleted
    assert js.deleted == [_legacy_stream_for("dead")]
    assert deleted == [_legacy_stream_for("dead")]


def test_owns_stream_follows_the_configured_queue_name() -> None:
    """The exclusion must follow the CONFIGURED stream name, not the default constant
    (review follow-up): the name is a Settings field, and an operator who renames the
    queue must not have the purge re-armed against the renamed stream by a stale constant
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
    assert not owns_stream("renamed-runq", run_queue_stream="renamed-runq")


@pytest.mark.asyncio
async def test_purge_legacy_streams_follows_a_renamed_queue_stream() -> None:
    """The full path, not just the predicate: a purge configured with a renamed queue stream
    must skip it exactly as it skips the default name.

    V-9: the rename is shaped like a legacy stream (`url4-cloud_`-prefixed) — the only shape
    where this proves the CONFIGURED-name exclusion rather than the prefix check alone. A
    non-prefixed rename would be refused by the prefix check by itself and pass this test
    whether or not the exclusion existed. `Settings` refuses a `url4-cloud_` queue name at
    startup (the V-8 validator); this test calls `purge_legacy_streams` directly, below that
    guard, which is exactly the caller the exclusion is defence-in-depth for.
    """
    renamed = "url4-cloud_renamed-runq"
    js = _FakeJetStream(
        names=[renamed, EVENTS_STREAM, _legacy_stream_for("dead")],
    )

    deleted = await purge_legacy_streams(
        cast(JetStreamContext, js), dry_run=False, run_queue_stream=renamed
    )

    assert renamed not in js.deleted
    assert EVENTS_STREAM not in js.deleted
    assert js.deleted == [_legacy_stream_for("dead")]
    assert deleted == [_legacy_stream_for("dead")]
