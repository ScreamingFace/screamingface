"""The worker's composition root feeds the queue its configured replica count (OME-1089).

The App and the worker declare the SAME singleton queue stream, and `ensure_stream` refuses a
declaration whose properties diverge from an existing stream. So a worker that declares with a
different replica count than the App is not a cosmetic mismatch — it is a startup failure on
whichever side loses the race. `run_worker` omitted `replicas` entirely, which meant the
worker always used the code default no matter what the deployment configured.

Both halves must therefore read the SAME setting. This file pins the worker half.
"""

from typing import Any

import pytest

from screamingface_engine.config import Settings


class _RecordingQueue:
    """Stands in for `RunQueue`, capturing the kwargs the composition root passes."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, url: str, **kwargs: Any) -> None:
        type(self).last_kwargs = dict(kwargs)


class _NoopWorker:
    """Stands in for `Worker`. `run` is a real coroutine, so `run_worker`'s own
    `asyncio.run(...)` runs untouched — patching `asyncio.run` would reach far beyond this
    test."""

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def run(self) -> None:
        return None


def _composed_queue_kwargs(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> dict[str, Any]:
    """Run `run_worker` with its collaborators stubbed, and return the queue's kwargs.

    `RunQueue` and `JetStreamPublisher` are imported INSIDE `run_worker`, so patching the
    attribute on their defining module is what the call-time import picks up.
    """
    import screamingface_engine.adapters.jetstream as jetstream_mod
    import screamingface_engine.runner_queue as runner_queue_mod
    import screamingface_engine.worker.loop as loop

    _RecordingQueue.last_kwargs = {}
    monkeypatch.setattr(runner_queue_mod, "RunQueue", _RecordingQueue)
    monkeypatch.setattr(jetstream_mod, "JetStreamPublisher", lambda *a, **k: object())
    monkeypatch.setattr(loop, "Worker", _NoopWorker)

    loop.run_worker(settings)
    return _RecordingQueue.last_kwargs


def test_the_worker_declares_the_queue_with_the_configured_replica_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pinned with a NON-default value: a composition root that drops the argument would still
    pass if the test used the default, which is exactly how this bug shipped."""
    kwargs = _composed_queue_kwargs(monkeypatch, Settings(run_queue_replicas=3))
    assert kwargs["replicas"] == 3


def test_an_unconfigured_worker_declares_the_single_node_safe_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment that states nothing must still be able to declare its stream on the
    single-node broker the chart bundles."""
    settings = Settings()
    kwargs = _composed_queue_kwargs(monkeypatch, settings)
    assert kwargs["replicas"] == settings.run_queue_replicas == 1


def test_the_worker_reads_the_replica_count_from_settings_not_a_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: the value the worker declares tracks `Settings`, so the App and the worker
    cannot diverge on a stream property that `ensure_stream` refuses to reconcile."""
    for configured in (1, 2, 5):
        kwargs = _composed_queue_kwargs(monkeypatch, Settings(run_queue_replicas=configured))
        assert kwargs["replicas"] == configured
