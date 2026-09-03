from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from functools import cache
from types import FrameType
from typing import Any, Protocol

from screamingface._runtime.bootstrap import enable_local_providers, scoreboard_seed_json
from screamingface._runtime.config import RuntimeConfig, scoreboard_assets
from screamingface._runtime.runtime_logging import log_service
from screamingface._runtime.source import (
    RuntimeSource,
    activate,
    resolve_source,
    verify_live_modules,
)

STARTUP_TIMEOUT_SECONDS = 90.0


class Server(Protocol):
    started: bool
    should_exit: bool

    async def serve(self) -> None: ...


# The modules ONLY the "runtime" extra provides AND the local boot path reaches before it
# can serve: the gateway app (fastapi, litellm, pydantic_settings, tortoise, bcrypt,
# cryptography), its sqlite database (aiosqlite), the Engine app (kubernetes — adapters.k8s
# imports it at module level; prometheus_client for metrics), and the servers (uvicorn).
#
# WHY probed with find_spec and not imported: the check must stay fast (importing litellm
# alone costs seconds) and must run in CI, which installs no runtime extra.
#
# WHY a fixed list and not "import the vendored apps": the vendored aigateway, scoreboard,
# and screamingface_engine packages import nothing heavy, so importing them proves nothing
# about the extra — the Colab gap (OME-1036). Fresh Colab preinstalls uvicorn and fastapi
# (gradio needs them) but not tortoise, so the old five-import guard passed on a plain
# install and the stack died inside the child with a raw ModuleNotFoundError. Keep this
# tuple in step with the "runtime" extra in pyproject.toml.
_RUNTIME_ONLY_MODULES: tuple[str, ...] = (
    "aiosqlite",
    "bcrypt",
    "cryptography",
    "fastapi",
    "kubernetes",
    "litellm",
    "prometheus_client",
    "pydantic_settings",
    "tortoise",
    "uvicorn",
)


def _missing_runtime_modules(
    names: Sequence[str], find_spec: Callable[[str], Any] = importlib.util.find_spec
) -> tuple[str, ...]:
    """The probed names that are not importable, in probe order.

    ``find_spec`` is a parameter so tests can simulate a host without the extra; the
    default locates a module WITHOUT executing it.
    """
    missing: list[str] = []
    for name in names:
        try:
            located = find_spec(name)
        except (ImportError, ValueError):
            # find_spec raises for a broken parent package or an invalid name; either way
            # this module is not usable, which is the answer the caller needs.
            located = None
        if located is None:
            missing.append(name)
    return tuple(missing)


def require_runtime_extra() -> RuntimeSource:
    # INVARIANT (OME-1001): the runtime source activates before ANY runtime app
    # import — in a checkout, the live apps/ code must shadow the stale build-time
    # copies a dev venv carries in site-packages.
    source = resolve_source(os.environ)
    activate(source)
    # WHY before `enable_local_providers` (which mutates os.environ): a refused boot must
    # leave no trace beyond the error, and find_spec imports nothing, so nothing about the
    # provider defaults matters to the probe (OME-1036).
    missing = _missing_runtime_modules(_RUNTIME_ONLY_MODULES)
    if missing:
        raise RuntimeError(
            f"Local runtime dependencies are missing: {', '.join(missing)}. "
            'Install "screamingface[runtime]".'
        )
    # Configure provider discovery before importing URL4 Cloud: its compiled model world may load
    # AI Gateway plugins, whose module-level instances capture provider settings at import time.
    enable_local_providers(os.environ)
    try:
        import aigateway
        import scoreboard
        import screamingface_engine
        import url4
        import uvicorn  # pyright: ignore[reportMissingImports]  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            'Local runtime dependencies are missing. Install "screamingface[runtime]".'
        ) from exc
    verify_live_modules(
        source,
        {
            "aigateway": aigateway,
            "scoreboard": scoreboard,
            "screamingface_engine": screamingface_engine,
            "url4": url4,
        },
    )
    return source


async def run(config: RuntimeConfig, shutdown_event: threading.Event | None = None) -> None:
    source = require_runtime_extra()
    # WHY logged at boot: whether a stack serves the live checkout or the installed
    # package decides what a benchmark actually tests — it must be auditable in the
    # runtime log (OME-1001).
    print(f"runtime source: {source.describe()}", flush=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    await _migrate(config)
    gateway, engine = _build_apps(config)
    servers = (
        _server(gateway, config.gateway_port, "AI Gateway"),
        _server(engine, config.engine_port, "Engine"),
    )
    if getattr(sys, "frozen", False):
        scoreboard_command = [
            sys.executable,
            "--data-dir",
            str(config.data_dir),
            "--scoreboard-child",
            "--scoreboard-port",
            str(config.scoreboard_port),
        ]
    else:
        scoreboard_command = [
            sys.executable,
            "-m",
            "screamingface._runtime.cli",
            "--data-dir",
            str(config.data_dir),
            "_scoreboard",
            "--scoreboard-port",
            str(config.scoreboard_port),
        ]
    scoreboard = subprocess.Popen(
        scoreboard_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        await _supervise(
            servers,
            scoreboard=scoreboard,
            scoreboard_port=config.scoreboard_port,
            services=config.services,
            shutdown_event=shutdown_event,
        )
    finally:
        if scoreboard.poll() is None:
            scoreboard.terminate()
            await asyncio.to_thread(scoreboard.wait)


async def _migrate(config: RuntimeConfig) -> None:
    from aigateway.db import build_tortoise_config as gateway_tortoise_config
    from scoreboard.db import build_tortoise_config as scoreboard_tortoise_config
    from tortoise import Tortoise  # pyright: ignore[reportMissingImports]
    from tortoise.migrations.api import migrate  # pyright: ignore[reportMissingImports]

    for database_url, tortoise_config in (
        (config.gateway_database_url, gateway_tortoise_config),
        (config.scoreboard_database_url, scoreboard_tortoise_config),
    ):
        try:
            await migrate(config=tortoise_config(database_url))
        finally:
            await Tortoise.close_connections()


def _build_apps(config: RuntimeConfig) -> tuple[object, object]:
    from aigateway.config import Settings as GatewaySettings
    from aigateway.main import create_app as create_gateway_app
    from pydantic import SecretStr  # pyright: ignore[reportMissingImports]
    from screamingface_engine import job_env
    from screamingface_engine.config import Settings as EngineSettings
    from screamingface_engine.local import create_local_app

    gateway = create_gateway_app(
        GatewaySettings(
            host="127.0.0.1",
            port=config.gateway_port,
            database_url=SecretStr(config.gateway_database_url),
            auth_mode="disabled",
        )
    )
    run_env: Mapping[str, str] = {
        **os.environ,
        job_env.RUNNER_CONFIG: str(config.runner_config),
        job_env.AIGATEWAY_BASE_URL: config.services["gateway"],
        "URL4_BENCHMARK_ASSETS": str(config.assets_dir),
    }
    engine = create_local_app(
        settings=EngineSettings(aigateway_base_url=config.services["gateway"]),
        env=run_env,
    )
    return gateway, engine


def run_scoreboard(config: RuntimeConfig) -> None:
    portal_dir, artifacts_dir = scoreboard_assets()
    os.environ.setdefault("SCOREBOARD_PORTAL_DIR", str(portal_dir))
    os.environ.setdefault("SCOREBOARD_PORTAL_ARTIFACTS_DIR", str(artifacts_dir))
    os.environ["SCOREBOARD_DATABASE_URL"] = config.scoreboard_database_url

    import uvicorn  # pyright: ignore[reportMissingImports]
    from scoreboard.config import Settings
    from scoreboard.main import create_app
    from scoreboard.seed import _run, load_benchmarks_json
    from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS

    # The Engine owns benchmark identity and revision. Deriving the local Scoreboard catalogue
    # from that same registry prevents retired aliases or stale revisions from making a completed
    # local evaluation impossible to publish.
    #
    # WHY `engine_rows` and not `configured`: these ARE the Engine's benchmarks, read by import
    # because a local stack runs both in one virtualenv. Handing them in as configuration would
    # trip the seeder's rule that configuration may not assert a revision the Engine did not
    # publish — every row would be refused and the local leaderboard would come up empty
    # (OME-904).
    asyncio.run(
        _run(
            configured=[],
            engine_url=None,
            engine_rows=load_benchmarks_json(scoreboard_seed_json(BUILTIN_BENCHMARKS)),
        )
    )
    settings = Settings(
        host="127.0.0.1",
        port=config.scoreboard_port,
        database_url=config.scoreboard_database_url,
        auth_mode="disabled",
        portal_dir=portal_dir,
        portal_artifacts_dir=artifacts_dir,
    )
    uvicorn.run(
        create_app(settings), host="127.0.0.1", port=config.scoreboard_port, log_level="info"
    )


def _server(app: Any, port: int, name: str) -> Server:
    # WHY: the ASGI app comes from _build_apps via the optional "runtime" extra, so its
    # static type is unavailable whenever that extra is not installed (as in CI). `object`
    # typechecked only while uvicorn was absent — with the extra installed, pyright
    # rejected it against uvicorn.Config's ASGIApplication parameter.
    import uvicorn  # pyright: ignore[reportMissingImports]

    # WHY access_log=False (OME-990): a run starts as `GET /?q=<url4 expression>`, and a url4
    # expression carries the user's prompt verbatim as its intent text. uvicorn's access line
    # records the full request line including the query string, and this process's stdout is
    # the RuntimeLog — so every prompt would be written to `<data_dir>/runtime.log`, which is
    # world-readable and is tailed back into the notebook by `_runtime_log_tail` when the
    # stack fails to start. The stdlib control server at `cli._control_server` already takes
    # this posture by overriding `log_message`.
    # INVARIANT: EVERY uvicorn Config built in this process must pass it. uvicorn clears the
    # `uvicorn.access` handlers only for the Config being constructed at that moment, while
    # each new Config re-runs dictConfig and re-creates them.
    return _embedded_server_type()(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            lifespan="on",
            access_log=False,
        ),
        name=name,
    )


@cache
def _embedded_server_type():
    import uvicorn  # pyright: ignore[reportMissingImports]

    class EmbeddedServer(uvicorn.Server):
        def __init__(self, config, *, name: str) -> None:
            super().__init__(config)
            self.name = name

        async def startup(self, sockets=None) -> None:
            try:
                await super().startup(sockets=sockets)
            except SystemExit as exc:
                raise RuntimeError(
                    f"{self.name} could not listen on {self.config.host}:{self.config.port}"
                ) from exc

        @contextlib.contextmanager
        def capture_signals(self) -> Iterator[None]:
            yield

    return EmbeddedServer


async def _supervise(  # noqa: C901, PLR0912, PLR0915
    servers: tuple[Server, ...],
    *,
    scoreboard: subprocess.Popen[bytes],
    scoreboard_port: int,
    services: Mapping[str, str],
    shutdown_event: threading.Event | None,
) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    with _signal_handlers(loop, stop):
        tasks = tuple(asyncio.create_task(_serve_service(server)) for server in servers)
        scoreboard_log_task = asyncio.create_task(_relay_scoreboard_output(scoreboard))
        stop_task = asyncio.create_task(stop.wait())
        external_stop_task = (
            asyncio.create_task(_wait_for_thread_event(shutdown_event))
            if shutdown_event is not None
            else None
        )
        try:
            async with asyncio.timeout(STARTUP_TIMEOUT_SECONDS):
                while not all(server.started for server in servers) or not _port_open(
                    scoreboard_port
                ):
                    if scoreboard.poll() is not None:
                        raise RuntimeError("Scoreboard stopped during startup")
                    failed = next((task for task in tasks if task.done()), None)
                    if failed is not None:
                        exception = failed.exception()
                        raise RuntimeError("runtime service stopped during startup") from exception
                    await asyncio.sleep(0.01)
            print(
                "SCREAMINGFACE_RUNTIME_READY "
                + json.dumps({"services": services}, separators=(",", ":"), sort_keys=True),
                flush=True,
            )
            scoreboard_task = asyncio.create_task(asyncio.to_thread(scoreboard.wait))
            waiters = (*tasks, stop_task, scoreboard_task)
            if external_stop_task is not None:
                waiters = (*waiters, external_stop_task)
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if stop_task not in done and external_stop_task not in done:
                if scoreboard_task in done:
                    raise RuntimeError("Scoreboard stopped unexpectedly")
                failed = next(task for task in tasks if task in done)
                exception = failed.exception()
                raise RuntimeError("a runtime service stopped unexpectedly") from exception
        finally:
            for server in servers:
                server.should_exit = True
            await asyncio.gather(*tasks, return_exceptions=True)
            stop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stop_task
            if external_stop_task is not None:
                external_stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await external_stop_task
            scoreboard_log_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scoreboard_log_task


async def _wait_for_thread_event(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0.05)


async def _serve_service(server: Server) -> None:
    name = getattr(server, "name", "supervisor").lower().replace("ai ", "")
    with log_service(name):
        await server.serve()


async def _relay_scoreboard_output(scoreboard: subprocess.Popen[bytes]) -> None:
    if scoreboard.stdout is None:
        return
    with log_service("scoreboard"):
        while line := await asyncio.to_thread(scoreboard.stdout.readline):
            print(line.decode(errors="replace").rstrip(), flush=True)


def _port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


@contextlib.contextmanager
def _signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> Iterator[None]:
    previous: dict[signal.Signals, Any] = {}

    def handle(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop.set)

    for selected in (signal.SIGINT, signal.SIGTERM):
        previous[selected] = signal.signal(selected, handle)
    try:
        yield
    finally:
        for selected, handler in previous.items():
            signal.signal(selected, handler)
