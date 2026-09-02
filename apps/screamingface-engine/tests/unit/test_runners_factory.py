from typing import cast

import pytest

from screamingface_engine.adapters.factory import build_job_runner
from screamingface_engine.adapters.jetstream import JetStreamPublisher
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueue


def test_runner_none_builds_no_job_runner() -> None:
    assert build_job_runner(Settings(runner="none")) is None


def test_default_settings_build_no_job_runner() -> None:
    assert build_job_runner(Settings()) is None


def test_unknown_runner_is_rejected_at_settings_construction() -> None:
    with pytest.raises(ValueError):
        Settings(runner="kubernetes")  # type: ignore[arg-type]


def test_queue_runner_is_built_from_settings() -> None:
    """The queue backend is the deployed substrate (OME-1090, cut over in OME-1092). Nothing
    connects at construction — the queue, the publisher, and the control client are all lazy."""
    settings = Settings(
        runner="queue",
        nats_url="nats://localhost:4222",
        runner_io_concurrency=7,
        capability_lifetime_s=1234,
    )

    runner = build_job_runner(settings)

    assert isinstance(runner, QueueJobRunner)
    assert runner._io_concurrency == 7  # noqa: SLF001
    assert runner._capability_lifetime_s == 1234  # noqa: SLF001


def test_queue_runner_receives_the_admission_knobs() -> None:
    """OME-1091: the depth ceiling and the per-caller in-flight cap reach the runner."""
    settings = Settings(
        runner="queue",
        run_queue_depth_ceiling=500,
        run_queue_caller_inflight_cap=3,
    )

    runner = build_job_runner(settings)

    assert isinstance(runner, QueueJobRunner)
    assert runner._depth_ceiling == 500  # noqa: SLF001
    assert runner._caller_inflight_cap == 3  # noqa: SLF001


def test_the_queue_runner_wires_the_configured_stream_and_prefix_everywhere() -> None:
    """P2-2/3: `run_queue_stream` and `run_queue_subject_prefix` were honoured by the
    worker's composition root but ignored at the App's — the App published to the
    DEFAULT stream while the worker pulled the configured one (a split that fails loudly
    on every admission), and the App-side publisher's sweep used a stale constant. All
    composition roots must agree for any Settings. The
    per-caller subject prefix rides along — a prefix mismatch would publish where no
    worker listens."""
    settings = Settings(
        runner="queue",
        nats_url="nats://localhost:4222",
        run_queue_stream="prod-runq",
        run_queue_subject_prefix="prod-prefix",
    )

    runner = build_job_runner(settings)

    # `build_job_runner` returns `JobRunner | None`; narrow to the concrete queue-backed
    # runner before reaching for its private collaborators. `_queue`/`_publisher` are
    # themselves typed to the narrow `_Queue`/`_Publisher` Protocols the runner depends
    # on, which rightly do not declare `RunQueue`/`JetStreamPublisher`'s own private
    # attributes — the factory always builds those concrete types for `runner="queue"`.
    assert isinstance(runner, QueueJobRunner)
    queue = cast(RunQueue, runner._queue)
    publisher = cast(JetStreamPublisher, runner._publisher)
    assert queue._stream == "prod-runq"
    assert queue._subject_prefix == "prod-prefix"
    assert publisher._run_queue_stream == "prod-runq"


def test_every_composition_root_wires_the_same_stream_name() -> None:
    """V-9/V-6: the stream-wiring test asserted only `build_job_runner`'s output — it
    could not see the App's consumer (whose sweep deletes what it accepts), the advisor
    (whose advisory subject carries the stream name), or the worker's root, and a fourth
    unwired consumer site (app.py) survived exactly that blindness. All four roots are
    now held to ONE Settings: a mismatch anywhere is a split that fails loudly or a
    sweep that deletes the queue."""
    from fastapi import FastAPI

    from screamingface_engine.app import _install_max_deliveries_advisor as _register_queue_advisor
    from screamingface_engine.app import build_stream_consumer
    from screamingface_engine.worker.loop import worker_composition

    settings = Settings(
        runner="queue",
        nats_url="nats://localhost:4222",
        run_queue_stream="prod-runq",
    )

    # The App's runner: the queue and its publisher agree with Settings.
    runner = build_job_runner(settings)
    assert isinstance(runner, QueueJobRunner)
    root_queue = cast(RunQueue, runner._queue)  # see the cast note above
    root_publisher = cast(JetStreamPublisher, runner._publisher)
    assert root_queue._stream == "prod-runq"  # noqa: SLF001
    assert root_publisher._run_queue_stream == "prod-runq"  # noqa: SLF001

    # The App's event-stream consumer: the sweep's exclusion follows this name (V-6).
    consumer = build_stream_consumer(settings)
    assert consumer._run_queue_stream == "prod-runq"  # noqa: SLF001

    # The advisor: its advisory subject must carry the configured stream name.
    app = FastAPI()
    _register_queue_advisor(app, settings)
    advisor = app.state.max_deliveries_advisor
    assert advisor._run_queue_stream == "prod-runq"  # noqa: SLF001
    assert "prod-runq" in advisor._subject  # noqa: SLF001

    # The worker: it must pull the same stream the App publishes to.
    queue, publisher = worker_composition(settings)
    assert queue._stream == "prod-runq"  # noqa: SLF001
    assert publisher._run_queue_stream == "prod-runq"  # noqa: SLF001