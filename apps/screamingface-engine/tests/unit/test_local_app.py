"""`screamingface_engine.local` — the composition root that fuses the control plane
and the run mode.

It is the ONE declared exception to the layering rule, so what matters here is that
the exception stays contained: the App it builds must be the real one with two
adapters swapped, and importing the ordinary serving path must not drag the engine
in behind it.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.config import INSECURE_DEFAULT_JWT_SECRET, Settings
from screamingface_engine.local import LOCAL_HOST, _with_runner_config, create_local_app


def _app(**kwargs: object) -> FastAPI:
    return create_local_app(Settings(jwt_secret="s" * 32, **kwargs), env={})  # type: ignore[arg-type]


def test_local_app_wires_the_in_memory_pair() -> None:
    app = _app()

    assert isinstance(app.state.stream, InMemoryEventStream)
    assert isinstance(app.state.job_runner, InProcessJobRunner)


def test_the_stream_is_ONE_object_shared_by_both_sides() -> None:
    """The App reads it as an `EventConsumer` and the runner writes it as an `EventPublisher`.

    Two instances would be two disjoint logs: every run would publish into a stream nobody reads,
    and every subscriber would wait forever on an empty one. That shared instance IS the bus.
    """
    app = _app()

    runner: InProcessJobRunner = app.state.job_runner
    assert runner._stream is app.state.stream  # noqa: SLF001 - identity is the invariant


def test_local_mode_registers_a_shutdown_hook_for_in_flight_runs() -> None:
    """Without it, `aclose` never runs and in-flight runs die with the loop, publishing nothing."""
    app = _app()

    runner: InProcessJobRunner = app.state.job_runner
    assert runner.aclose in app.router.on_shutdown


def test_local_mode_boots_on_the_insecure_default_secret() -> None:
    """`create_app_from_env` REFUSES this secret; local mode accepts it deliberately.

    That is the trade `LOCAL_HOST` pays for — so if this ever starts raising, the loopback bind
    has become load-bearing for something it was not designed to carry.
    """
    app = create_local_app(Settings(jwt_secret=INSECURE_DEFAULT_JWT_SECRET), env={})

    assert isinstance(app, FastAPI)


def test_the_insecure_default_is_warned_about(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        create_local_app(Settings(jwt_secret=INSECURE_DEFAULT_JWT_SECRET), env={})

    assert "INSECURE" in caplog.text


def test_a_real_secret_produces_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        _app()

    assert "INSECURE" not in caplog.text


def test_local_host_is_loopback() -> None:
    # INVARIANT: not configurable, and not 0.0.0.0. See the docstring on `LOCAL_HOST`.
    assert LOCAL_HOST == "127.0.0.1"


def test_settings_tune_the_local_bounds() -> None:
    app = _app(local_max_concurrent_runs=3, local_stream_max_frames=7, local_max_run_history=5)

    runner: InProcessJobRunner = app.state.job_runner
    assert runner._max_concurrent == 3  # noqa: SLF001
    assert runner._max_history == 5  # noqa: SLF001
    assert app.state.stream._max_frames == 7  # noqa: SLF001


def test_an_unconfigured_local_run_falls_back_to_the_checkout_config() -> None:
    """Without this, every run in a dev checkout fails before reaching a model.

    The declared world is baked into the IMAGE at `/etc/url4/url4.toml` and is not installed by
    the wheel, so the default path does not exist outside a container.
    """
    resolved = _with_runner_config({})

    config_path = Path(resolved[job_env.RUNNER_CONFIG])
    assert config_path.is_file()
    assert config_path.name == "url4.toml"


def test_an_explicit_runner_config_is_never_overridden() -> None:
    resolved = _with_runner_config({job_env.RUNNER_CONFIG: "/somewhere/else.toml"})

    assert resolved[job_env.RUNNER_CONFIG] == "/somewhere/else.toml"


def test_the_fallback_leaves_the_rest_of_the_environment_alone() -> None:
    resolved = _with_runner_config({job_env.AIGATEWAY_PROFILE: "team-a"})

    assert resolved[job_env.AIGATEWAY_PROFILE] == "team-a"


def test_importing_the_serving_app_does_not_pull_in_local_mode_or_the_run_mode() -> None:
    """INVARIANT: the fusion edge points ONE way — `local` imports `app`, never the reverse.

    `local` is exempt from the layering gate, so the containment of that exemption is
    exactly what needs pinning: an ordinary `screamingface-engine serve` must not
    reach the run mode just because a local mode exists. If `screamingface_engine.app`
    ever imported `local` at module scope, every deployed App would load
    `runner.connector`/`runner.executor` and httpx behind it.

    NOT asserted here: that the url4 ENGINE stays unloaded. `url4/__init__` imports the DAG, so
    any `url4.streaming` import loads it — which `check_layering.py`'s SCOPE NOTE already records
    as unenforceable by construction. A subprocess because this interpreter has imported the lot.

    WHY the probe is precise (dot-suffixed) rather than a bare
    `startswith('screamingface_engine.runner')`: the run queue (`runner_queue`, OME-1088) is a
    SHARED LEAF both halves import, and its name happens to start with `runner` — a bare prefix
    would flag the serving app for importing its own queue substrate.
    """
    probe = (
        "import sys, screamingface_engine.app;"
        "leaked = sorted(m for m in sys.modules "
        "if m == 'screamingface_engine.local' "
        "or m == 'screamingface_engine.runner' "
        "or m.startswith('screamingface_engine.runner.'));"
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", (
        f"importing screamingface_engine.app reached the run mode: {result.stdout.strip()}"
    )
