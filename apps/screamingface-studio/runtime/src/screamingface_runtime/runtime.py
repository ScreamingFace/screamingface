"""Supervise the two ASGI applications that make up the local desktop runtime."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Protocol

from screamingface_runtime.bundled import runner_config_path

AI_GATEWAY_HOST = "127.0.0.1"
AI_GATEWAY_PORT = 9105
ENGINE_HOST = "127.0.0.1"
ENGINE_PORT = 9108
STARTUP_TIMEOUT_SECONDS = 30.0

_logger = logging.getLogger("screamingface_runtime")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Filesystem and network configuration for one local runtime."""

    data_dir: Path
    runner_config: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", self.data_dir.expanduser().resolve())
        selected_config = self.runner_config or runner_config_path()
        object.__setattr__(
            self,
            "runner_config",
            selected_config.expanduser().resolve(),
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "aigateway.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite://{self.database_path}"


class Server(Protocol):
    should_exit: bool
    started: bool

    async def serve(self) -> None: ...


ServerFactory = Callable[[object, str, int, str], Server]
Migration = Callable[[str], Awaitable[None]]
AppFactory = Callable[[RuntimeConfig], tuple[object, object]]
ReadyCallback = Callable[[Mapping[str, str]], None]


async def run(
    config: RuntimeConfig,
    *,
    migrate: Migration | None = None,
    build_apps: AppFactory | None = None,
    server_factory: ServerFactory | None = None,
    ready: ReadyCallback | None = None,
) -> None:
    """Prepare persistent state and run both HTTP services until shutdown."""

    config.data_dir.mkdir(parents=True, exist_ok=True)
    selected_migration = migrate or _migrate
    selected_app_factory = build_apps or _build_apps
    selected_server_factory = server_factory or _server

    try:
        await selected_migration(config.database_url)
    except Exception as exc:
        raise RuntimeError(f"AI Gateway database migration failed: {exc}") from exc
    try:
        gateway_app, engine_app = selected_app_factory(config)
    except Exception as exc:
        raise RuntimeError(f"runtime application setup failed: {exc}") from exc
    servers = (
        selected_server_factory(
            gateway_app,
            AI_GATEWAY_HOST,
            AI_GATEWAY_PORT,
            "aigateway",
        ),
        selected_server_factory(
            engine_app,
            ENGINE_HOST,
            ENGINE_PORT,
            "screamingface-engine",
        ),
    )
    await _supervise(servers, ready=ready or _announce_ready)


def _announce_ready(services: Mapping[str, str]) -> None:
    """Emit one machine-readable line once both ASGI lifespans have started."""

    print(
        "SCREAMINGFACE_RUNTIME_READY "
        + json.dumps({"services": services}, separators=(",", ":"), sort_keys=True),
        flush=True,
    )


async def _migrate(database_url: str) -> None:
    """Apply AI Gateway migrations without spawning another Python process."""

    from aigateway.db import build_tortoise_config
    from tortoise import Tortoise
    from tortoise.migrations.api import migrate

    try:
        await migrate(config=build_tortoise_config(database_url))
    finally:
        await Tortoise.close_connections()


def _build_apps(config: RuntimeConfig) -> tuple[object, object]:
    """Construct both production ASGI apps in their loopback-only local modes."""

    if config.runner_config is not None and not config.runner_config.is_file():
        raise FileNotFoundError(f"URL4 runner config not found: {config.runner_config}")

    from aigateway.config import Settings as GatewaySettings
    from aigateway.main import create_app as create_gateway_app
    from pydantic import SecretStr
    from url4_cloud import job_env
    from url4_cloud.config import Settings as EngineSettings
    from url4_cloud.local import create_local_app

    gateway = create_gateway_app(
        GatewaySettings(
            host=AI_GATEWAY_HOST,
            port=AI_GATEWAY_PORT,
            database_url=SecretStr(config.database_url),
            auth_mode="disabled",
        )
    )
    run_env: Mapping[str, str] = {
        **os.environ,
        job_env.RUNNER_CONFIG: str(config.runner_config),
    }
    engine = create_local_app(
        settings=EngineSettings(
            aigateway_base_url=f"http://{AI_GATEWAY_HOST}:{AI_GATEWAY_PORT}"
        ),
        env=run_env,
    )
    return gateway, engine


def _server(app: object, host: str, port: int, name: str) -> Server:
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        lifespan="on",
    )
    return _EmbeddedServer(config, name=name)


def _embedded_server_type():
    import uvicorn

    class EmbeddedServer(uvicorn.Server):
        def __init__(self, config, *, name: str) -> None:
            super().__init__(config)
            self.name = name

        async def startup(self, sockets=None) -> None:
            try:
                await super().startup(sockets=sockets)
            except SystemExit as exc:
                # Uvicorn treats a bind error as a top-level CLI exit. Embedded in our shared
                # process, that would cancel the peer app and bypass the launcher's error path.
                raise RuntimeError(
                    f"{self.name} could not listen on {self.config.host}:{self.config.port}"
                ) from exc

        @contextlib.contextmanager
        def capture_signals(self) -> Iterator[None]:
            # The runtime owns process signals so one signal stops both servers.
            yield

    return EmbeddedServer


_EmbeddedServer = _embedded_server_type()


async def _supervise(servers: tuple[Server, ...], *, ready: ReadyCallback) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    with _signal_handlers(loop, stop):
        tasks = tuple(asyncio.create_task(server.serve()) for server in servers)
        stop_task = asyncio.create_task(stop.wait())
        try:
            async with asyncio.timeout(STARTUP_TIMEOUT_SECONDS):
                await _wait_until_started(servers, tasks)
            ready(
                {
                    "aigateway": f"http://{AI_GATEWAY_HOST}:{AI_GATEWAY_PORT}",
                    "engine": f"http://{ENGINE_HOST}:{ENGINE_PORT}",
                }
            )
            done, _ = await asyncio.wait(
                (*tasks, stop_task), return_when=asyncio.FIRST_COMPLETED
            )
            unexpected = stop_task not in done
            if unexpected:
                failed = next(task for task in tasks if task in done)
                exception = failed.exception()
                if exception is not None:
                    raise exception
                raise RuntimeError("a managed runtime service stopped unexpectedly")
        except TimeoutError as exc:
            raise RuntimeError(
                f"runtime services did not become ready within {STARTUP_TIMEOUT_SECONDS:g} seconds"
            ) from exc
        finally:
            for server in servers:
                server.should_exit = True
            await asyncio.gather(*tasks, return_exceptions=True)
            stop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stop_task


async def _wait_until_started(
    servers: tuple[Server, ...], tasks: tuple[asyncio.Task[None], ...]
) -> None:
    """Wait until Uvicorn has completed both application startup lifespans."""

    while not all(getattr(server, "started", False) for server in servers):
        failed = next((task for task in tasks if task.done()), None)
        if failed is not None:
            exception = failed.exception()
            if exception is not None:
                raise RuntimeError(
                    f"runtime service failed during startup: {exception}"
                ) from exception
            raise RuntimeError("runtime service stopped during startup")
        await asyncio.sleep(0.01)


@contextlib.contextmanager
def _signal_handlers(
    loop: asyncio.AbstractEventLoop, stop: asyncio.Event
) -> Iterator[None]:
    previous: dict[signal.Signals, signal.Handlers] = {}

    def handle(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop.set)

    for selected in (signal.SIGINT, signal.SIGTERM):
        previous[selected] = signal.signal(selected, handle)
    try:
        yield
    finally:
        for selected, handler in previous.items():
            signal.signal(selected, handler)


__all__ = ["RuntimeConfig", "run"]
