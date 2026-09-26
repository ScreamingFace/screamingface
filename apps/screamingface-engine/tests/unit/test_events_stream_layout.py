"""EVT-18: the per-run stream layout is GONE (uniform executor, PRD 01).

The former layout gave every run its own JetStream stream, swept orphans on error 10047,
and named a stream from a topic (`subjects.stream_for`). One shared stream (`url4-events`)
replaced all of it (erd.md §5): no per-topic `add_stream`, no sweep, no stream-per-topic
naming helper, and the only place this codebase still calls the broker's own
`delete_stream` (by a stream NAME, as opposed to this codebase's own `delete_stream(topic)`
wrapper, which purges a SUBJECT) is `purge_legacy_streams` — the one-shot admin command
that tears down the FORMER layout's leftover streams after a drained rollout.

These are regression pins: this test module fails the moment any of it comes back, rather
than at the next incident that per-run reservations caused (adapters/jetstream.py:64-76).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

import pytest
from nats.errors import Error as NatsError
from nats.js import JetStreamContext
from nats.js.errors import APIError, NotFoundError

from screamingface_engine import subjects
from screamingface_engine.adapters import jetstream
from screamingface_engine.adapters.jetstream import (
    INSUFFICIENT_RESOURCES_ERR_CODE,
    EventsStreamConfig,
    EventsStreamConfigError,
    JetStreamPublisher,
    ensure_events_stream,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "screamingface_engine"


class _FakeInsufficientResourcesJetStream:
    """A JetStream context whose `add_stream` always fails the same way a store too small for
    `events.maxBytes` fails on the broker (`INSUFFICIENT_RESOURCES_ERR_CODE`)."""

    def __init__(self) -> None:
        self.add_stream_calls = 0

    async def stream_info(self, name: str) -> object:
        raise NotFoundError(code=404, err_code=10059, description="stream not found")

    async def add_stream(self, *_args: Any, **_kwargs: Any) -> object:
        self.add_stream_calls += 1
        raise APIError(err_code=INSUFFICIENT_RESOURCES_ERR_CODE)

    async def account_info(self) -> object:
        # Unreachable is fine: `_store_too_small` falls back to "store limit unreadable" on
        # either an `APIError` or a `NatsError` here.
        raise NatsError("account_info unreachable in this fake")


def _iter_py_files() -> list[Path]:
    return sorted(_SRC.rglob("*.py"))


def test_the_module_defines_no_orphan_sweep() -> None:
    """`_sweep_orphans`/`_never_started`/`_is_orphan` swept the broker's OWN stream list on
    error 10047 (the former layout's only reclaim backstop for a crashed runner). A shared
    stream needs none of it: `max_age` expiry is the backstop now (EV-D13)."""
    for name in ("_sweep_orphans", "_never_started", "_is_orphan"):
        assert not hasattr(jetstream, name), f"{name} should have been removed with the sweep"


@pytest.mark.asyncio
async def test_ensure_events_stream_does_not_retry_add_stream_on_insufficient_resources() -> None:
    """The former layout retried `add_stream` after an orphan sweep on 10047
    (INSUFFICIENT_RESOURCES_ERR_CODE) — the very capacity failure a shared stream removes the
    cap that caused. `ensure_events_stream` must call `add_stream` exactly once and RAISE a
    named `EventsStreamConfigError` instead of retrying.

    Behavioral, not a source-text pin (review follow-up V-10): the integration test
    `test_startup_fails_when_max_bytes_exceeds_store` proves the same error against a real
    broker; this one pins the no-retry property with a fake, which the integration test cannot
    (it can only observe the one call a real broker made)."""
    js = _FakeInsufficientResourcesJetStream()

    with pytest.raises(EventsStreamConfigError, match="events.maxBytes"):
        await ensure_events_stream(cast(JetStreamContext, js), EventsStreamConfig(), update=True)

    assert js.add_stream_calls == 1


def test_subjects_module_has_no_per_topic_stream_naming() -> None:
    """`stream_for`/`topic_of` named a stream FROM a topic (`url4-cloud_<topic>`) — meaningless
    once every topic is a SUBJECT of the one shared stream."""
    assert not hasattr(subjects, "stream_for")
    assert not hasattr(subjects, "topic_of")
    assert "stream_for" not in subjects.__all__
    assert "topic_of" not in subjects.__all__


def test_only_purge_legacy_streams_calls_the_brokers_delete_stream_by_name() -> None:
    """`js.delete_stream(<name>)` deletes a broker stream OBJECT by name — the former
    layout's per-run teardown. The shared-stream layout's own `delete_stream(topic)`
    (`_JetStreamConnection`, `JetStreamPublisher`/`JetStreamConsumer`, `deps.stream`, the
    Runner's `publisher.delete_stream`) is a SUBJECT purge, never this call, so `js.` is the
    marker: it is the raw JetStream context, not this codebase's own wrapper of the same name.

    The only legitimate call is inside `purge_legacy_streams` (adapters/jetstream.py): the
    one-shot admin command that deletes the FORMER layout's leftover `url4-cloud_<topic>`
    streams after a drained rollout (erd.md §10, EV-E3).
    """
    hits: list[tuple[Path, int]] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "js.delete_stream(" in line:
                hits.append((path, lineno))
    assert len(hits) == 1, f"expected exactly one js.delete_stream( call site, found {hits}"
    (path, lineno) = hits[0]
    assert path.name == "jetstream.py"

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    enclosing = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.lineno <= lineno <= (node.end_lineno or node.lineno)
    ]
    # WHY the innermost (max `lineno`) function, not any ancestor: `ast.walk` yields every
    # enclosing scope, and the module-level function is the one whose NAME must be
    # `purge_legacy_streams` — an inner helper of the same body would also match "encloses
    # this line" without being the function this test means to pin.
    innermost = max(enclosing, key=lambda node: node.lineno)
    assert innermost.name == "purge_legacy_streams"


def test_the_publisher_still_exposes_the_shared_stream_metrics_surface() -> None:
    """A companion pin for the worker's metrics collector (tasks 1-3): the attributes it reads
    via `getattr(..., None)` must still exist on the real adapter, or the collector silently
    renders nothing against production code while every fake in the test suite keeps them.

    `store_snapshot` is deliberately NOT pinned here (review follow-up): it is the App's
    CONSUMER the events-store gauge reads (`_EventsStoreCollector` takes `get_stream`, not
    `get_publisher`), so a publisher happening to inherit it from `_JetStreamConnection` is an
    implementation detail, not a contract this test should lock in.
    """
    publisher = JetStreamPublisher("nats://localhost:4222")
    assert publisher.subject_purges == 0
    assert publisher.publish_conflicts == {}


@pytest.mark.asyncio
async def test_an_existing_events_stream_is_never_re_added() -> None:
    """REGRESSION (kind K6/K12): `add_stream` on an existing stream makes the server reserve its
    bytes twice, so a restart failed with 10047 once `max_bytes` passed half the store. An
    existing stream is reconciled (`stream_info`) and never re-added."""
    from types import SimpleNamespace

    from screamingface_engine.adapters.jetstream import EventsStreamConfig, ensure_events_stream

    config = EventsStreamConfig()

    class _Existing:
        added = 0

        async def stream_info(self, name: str) -> object:
            return SimpleNamespace(config=config.stream_config())

        async def add_stream(self, *_args: Any, **_kwargs: Any) -> object:
            self.added += 1
            return object()

    js = _Existing()
    await ensure_events_stream(js, config, update=True)  # type: ignore[arg-type]
    assert js.added == 0
