"""Local mode's composition root — the App and the run mode fused into one process.

    screamingface-engine serve --local

Runs the whole protocol with no Kubernetes and no NATS: an `InProcessJobRunner` spawns each run
as an `asyncio.Task` in the serving process, and an `InMemoryEventStream` carries its frames to
the same REST sync-hold and WS pump a deployed App reads from JetStream. Everything above the two
swapped adapters — auth, the 428 subscriber gate, sequencing, replay-from, the model catalog — is
the production code path, unmodified.

# INVARIANT: this module is the ONLY place the control plane and the run mode meet, which is why
# `.claude/scripts/check_layering.py` lists it in BOTH `CONTROL_PLANE` and `_EXEMPT` — exactly as
# it does `cli.py`, and for the same reason. Being exempt is not the same as being unexamined:
# naming it in `CONTROL_PLANE` is what puts it in the gate's field of view at all, so a future
# reader sees a declared exception rather than a module that quietly evaded the rule.
#
# INVARIANT: nothing imports this module except `cli.py`. `screamingface_engine.app`
# must stay importable without dragging in the engine, which is what keeps a
# deployed App's cold start unchanged — `tests/unit/test_local_app.py` pins the
# direction of that edge.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from functools import partial
from pathlib import Path

from fastapi import FastAPI

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.app import create_app
from screamingface_engine.benchmarks import (
    BENCHMARK_ASSETS_ENV,
    EMPTY_BENCHMARKS,
    BenchmarkRegistry,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.catalog import build_executable_catalog_service
from screamingface_engine.config import INSECURE_DEFAULT_JWT_SECRET, Settings
from screamingface_engine.connections import build_connections
from screamingface_engine.metrics import register_fair_share_metrics
from screamingface_engine.runner.fair_share import FairShareGate

_logger = logging.getLogger(__name__)

LOCAL_HOST = "127.0.0.1"
"""INVARIANT: loopback only. Local mode deliberately skips `_require_prod_secret`, so it may be
running on the publicly-known dev JWT secret — anyone who can reach the port could mint a
capability token for any topic. The bind address is what keeps that from being remotely
reachable, and it is not configurable for that reason."""


def _warn_if_insecure(settings: Settings) -> None:
    """Say plainly that auth is open when the dev default secret is in play.

    `create_app_from_env` REFUSES to boot on this secret; local mode accepts it so a developer
    need not mint one, and pairs that with the loopback bind above. The warning exists so the
    trade is visible in the log rather than inferred from the absence of an error.
    """
    if settings.jwt_secret == INSECURE_DEFAULT_JWT_SECRET:
        _logger.warning(
            "local mode is using the INSECURE default JWT secret — anyone who can reach %s can "
            "mint a capability token for any topic. Set URL4_CLOUD_JWT_SECRET to change it; "
            "never expose this process beyond loopback.",
            LOCAL_HOST,
        )


def _with_runner_config(env: Mapping[str, str]) -> Mapping[str, str]:
    """Point an unconfigured local run at the repo's own ``url4.toml``.

    The declared world is baked into the IMAGE at ``/etc/url4/url4.toml`` (the Dockerfile copies
    it there) and is not installed by the wheel — so in a dev checkout that path does not exist
    and every local run would terminate as ``failed`` with a missing-config error before it could
    reach a model. Falling back to the checkout's own ``url4.toml``, which sits two levels above
    this package, is what makes `--local` usable straight out of a clone.

    Deliberately narrow: an explicit ``URL4_RUNNER_CONFIG`` always wins, and so does a real
    ``/etc/url4/url4.toml`` — this only fills a gap that exists nowhere but a source checkout.
    """
    from screamingface_engine.world_config import DEFAULT_CONFIG_PATH

    if job_env.RUNNER_CONFIG in env or Path(DEFAULT_CONFIG_PATH).is_file():
        return env
    candidate = Path(__file__).resolve().parents[2] / "url4.toml"
    if not candidate.is_file():
        return env
    _logger.info("local mode: using the checkout's runner config at %s", candidate)
    return {**env, job_env.RUNNER_CONFIG: str(candidate)}


def _local_benchmarks(env: Mapping[str, str]) -> BenchmarkRegistry:
    """The Benchmarks a local run installs: the builtins only where assets were declared.

    WHY not the builtins unconditionally (which is what this used to be): `benchmarks.install()`
    runs while the WORLD is built — before, and independent of, what the expression addresses —
    so a Benchmark whose assets are absent fails EVERY run, including one that references no
    Benchmark at all. DRACO's cases live at ``/opt/benchmarks/draco/cases.json``, a path the
    Dockerfile creates and a source checkout does not, so the default was guaranteed to fail
    exactly where local mode is meant to be usable (OME-795).

    INVARIANT: naming an asset root is the operator asserting the assets exist. Local mode takes
    that at face value and installs, so a wrong path fails loudly rather than silently serving a
    Benchmark-less Engine. Absence of the variable is the only "install nothing" signal.
    """
    return BUILTIN_BENCHMARKS if BENCHMARK_ASSETS_ENV in env else EMPTY_BENCHMARKS


def _with_local_gateway(settings: Settings) -> Settings:
    """Substitute the loopback default into the ONE address the whole App resolves.

    INVARIANT: `aigateway_base_url` still wins when stated — the local value is a fallback, not
    an override, so a developer who names a gateway never has half the App quietly talk to a
    different one.
    """
    if settings.aigateway_base_url is not None:
        return settings
    return settings.model_copy(update={"aigateway_base_url": settings.local_aigateway_base_url})


def create_local_app(
    settings: Settings | None = None,
    *,
    env: Mapping[str, str] | None = None,
    benchmarks: BenchmarkRegistry | None = None,
) -> FastAPI:
    """Build the local-mode App: in-process runner, in-memory stream, real everything else.

    `env` is the ambient environment each run's executor is built from (the deploy-time half a
    Job would receive via `envFrom`); it defaults to the process environment and is a parameter
    so tests need not mutate `os.environ`.
    """
    settings = settings or Settings()
    _warn_if_insecure(settings)

    # ONE object, handed to both sides — it is an `EventStream`, so it satisfies the App's
    # `EventConsumer` and the runner's `EventPublisher` at once. That shared instance IS the bus.
    stream = InMemoryEventStream(max_frames_per_topic=settings.local_stream_max_frames)

    # WHY the import is function-local: it is THE line that crosses the layering boundary, and
    # keeping it here means the crossing happens when a local App is actually built rather than on
    # any import of this module. What it defers is `runner.connector`/`runner.executor` and httpx
    # — not the engine itself, which `url4/__init__` has already pulled in via any `url4.streaming`
    # import (see the SCOPE NOTE in `check_layering.py`).
    from screamingface_engine.runner.main import build_executor

    run_env = _with_runner_config(env if env is not None else os.environ)
    if benchmarks is None:
        benchmarks = _local_benchmarks(run_env)
    # INVARIANT: the local default is substituted ONCE, here, before anything reads the address —
    # so discovery and connections resolve the same gateway by construction rather than by two
    # call sites agreeing. This substitution used to sit BELOW the catalog and feed only
    # `build_connections`, which left `/v1/models` answering 503 "not configured" on the one
    # deployment shape whose address is known in advance, while `/v1/connections` on that very
    # address answered 200 (OME-795).
    settings = _with_local_gateway(settings)
    # Catalog before the runner (OME-880): the runner takes the admitted-model overlay so a
    # dynamically admitted model is routable by the very next local run.
    catalog = build_executable_catalog_service(settings, run_env)
    # FEATURE (OME-908): ONE gate, shared by every local run — the composition point that
    # makes local fair-share dynamic where a deployed Job gets a static budget instead.
    # Built beside the runner (its runs' executors bind into it through `build_executor`'s
    # `io_gate`) and closed AFTER the runner on shutdown, so cancelled runs release their
    # permits into a gate that still accepts the releases.
    io_gate = FairShareGate(settings.local_io_capacity)
    job_runner = InProcessJobRunner(
        stream,
        partial(build_executor, benchmarks=benchmarks, io_gate=io_gate),
        base_env=run_env,
        max_concurrent_runs=settings.local_max_concurrent_runs,
        max_history=settings.local_max_run_history,
        extra_models=None if catalog is None else (lambda: catalog.admitted_model_ids),
    )
    # INVARIANT: local mode keeps the caller-managed rows that back its BYOK controls; profile
    # availability is the deployed Engine policy and must not replace this mutable state.
    connections = build_connections(settings, listing_source="connections")
    app = create_app(
        settings,
        stream=stream,
        job_runner=job_runner,
        catalog=catalog,
        model_parameters=catalog.model_parameter_source if catalog is not None else None,
        connections=connections,
        benchmarks=benchmarks,
    )
    register_fair_share_metrics(app.state.metrics, lambda: io_gate)
    # On app.state for operators and tests: the one gate every local run shares. Read-only
    # by convention — nothing outside `runner.fair_share` mutates it.
    app.state.fair_share_gate = io_gate
    app.router.on_shutdown.append(job_runner.aclose)
    # WHY after `job_runner.aclose`: shutdown cancels every in-flight run first, and each
    # cancelled fetch releases its permit in a `finally` — closing the gate before those
    # releases land would drop them on a dead object instead of the books.
    app.router.on_shutdown.append(io_gate.aclose)
    if catalog is not None:
        app.router.on_shutdown.append(catalog.aclose)
    if connections is not None:
        app.router.on_shutdown.append(connections.aclose)
    return app


__all__ = ["LOCAL_HOST", "create_local_app"]
