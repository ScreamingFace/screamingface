"""The App's composition root feeds the queue its configured replica count (OME-1090).

The App and the worker declare the SAME singleton queue stream, and `ensure_stream` refuses a
declaration whose properties diverge from an existing one. The App usually declares first — it
accepts a run before any worker pulls it — so an App stuck on the code default while the worker
reads configuration is a startup failure for the worker, and vice versa.

`build_job_runner` omitted `replicas` entirely. OME-1088 made the count a setting and OME-1089
wired the worker half; this file pins the App half and, more importantly, the agreement between
the two.
"""

from typing import Any

import pytest

from screamingface_engine.config import Settings


class _RecordingQueue:
    """Stands in for `RunQueue`, capturing the kwargs a composition root passes."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, url: str, **kwargs: Any) -> None:
        type(self).last_kwargs = dict(kwargs)


def _app_queue_kwargs(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> dict[str, Any]:
    """The kwargs the APP's composition root passes to `RunQueue`.

    `factory` imports `RunQueue`, `JetStreamPublisher` and `ControlClient` at module level, so
    the patches land on the factory's own namespace.
    """
    import screamingface_engine.adapters.factory as factory

    _RecordingQueue.last_kwargs = {}
    monkeypatch.setattr(factory, "RunQueue", _RecordingQueue)
    monkeypatch.setattr(factory, "JetStreamPublisher", lambda *a, **k: object())
    monkeypatch.setattr(factory, "ControlClient", lambda *a, **k: object())

    factory.build_job_runner(settings)
    return _RecordingQueue.last_kwargs


def _worker_queue_kwargs(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> dict[str, Any]:
    """The kwargs the WORKER's composition root passes to `RunQueue`.

    `worker_composition` — not `run_worker`: the latter opens a real NATS connection for the
    run-control channel, which a unit test must not drive. `worker_composition` was extracted
    for precisely this, so both halves can be held to one `Settings` in one test.

    It imports its collaborators INSIDE the function, so these patches land on the defining
    modules rather than on `loop`'s namespace.
    """
    import screamingface_engine.adapters.jetstream as jetstream_mod
    import screamingface_engine.runner_queue as runner_queue_mod
    import screamingface_engine.worker.loop as loop

    _RecordingQueue.last_kwargs = {}
    monkeypatch.setattr(runner_queue_mod, "RunQueue", _RecordingQueue)
    monkeypatch.setattr(jetstream_mod, "JetStreamPublisher", lambda *a, **k: object())

    loop.worker_composition(settings)
    return _RecordingQueue.last_kwargs


def test_the_app_declares_the_queue_with_the_configured_replica_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pinned with a NON-default value: a composition root that drops the argument still passes
    a test written against the default, which is how this shipped unnoticed."""
    settings = Settings(runner="queue", run_queue_replicas=3)
    assert _app_queue_kwargs(monkeypatch, settings)["replicas"] == 3


def test_an_unconfigured_app_declares_the_single_node_safe_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment that states nothing must still declare its stream on the single-node broker
    the chart bundles."""
    settings = Settings(runner="queue")
    kwargs = _app_queue_kwargs(monkeypatch, settings)
    assert kwargs["replicas"] == settings.run_queue_replicas == 1


@pytest.mark.parametrize("configured", [1, 2, 5])
def test_both_composition_roots_declare_the_same_replica_count(
    configured: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT — the point of this unit: the App and the worker declare ONE stream, and
    `ensure_stream` refuses a divergent declaration. Reading the same setting on both sides is
    what makes them agree for ANY configuration, rather than only where the defaults coincide.
    """
    settings = Settings(runner="queue", run_queue_replicas=configured)
    app = _app_queue_kwargs(monkeypatch, settings)["replicas"]
    worker = _worker_queue_kwargs(monkeypatch, settings)["replicas"]
    assert app == worker == configured
