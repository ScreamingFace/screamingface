from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from screamingface_runtime.bundled import runner_config_path
from screamingface_runtime.runtime import RuntimeConfig, run


class FakeServer:
    def __init__(self, *, stop_immediately: bool = False) -> None:
        self.should_exit = False
        self.started = False
        self.stop_immediately = stop_immediately

    async def serve(self) -> None:
        if self.stop_immediately:
            return
        self.started = True
        while not self.should_exit:
            await asyncio.sleep(0)


def test_runtime_config_uses_one_persistent_database(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path)

    assert config.database_path == tmp_path / "aigateway.sqlite3"
    assert config.database_url == f"sqlite://{tmp_path}/aigateway.sqlite3"
    assert config.runner_config == runner_config_path()


def test_run_migrates_before_building_and_stops_peer_on_failure(tmp_path: Path) -> None:
    events: list[str] = []
    servers: list[FakeServer] = []

    async def migrate(database_url: str) -> None:
        events.append(f"migrate:{database_url}")

    def build_apps(_config: RuntimeConfig) -> tuple[object, object]:
        events.append("build")
        return object(), object()

    def server_factory(_app: object, _host: str, _port: int, name: str) -> FakeServer:
        server = FakeServer(stop_immediately=name == "screamingface-engine")
        servers.append(server)
        return server

    with pytest.raises(RuntimeError, match="stopped during startup"):
        asyncio.run(
            run(
                RuntimeConfig(data_dir=tmp_path),
                migrate=migrate,
                build_apps=build_apps,
                server_factory=server_factory,
            )
        )

    assert events == [f"migrate:sqlite://{tmp_path}/aigateway.sqlite3", "build"]
    assert all(server.should_exit for server in servers)


def test_missing_runner_config_is_rejected(tmp_path: Path) -> None:
    from screamingface_runtime.runtime import _build_apps

    missing = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError, match=str(missing)):
        _build_apps(RuntimeConfig(data_dir=tmp_path, runner_config=missing))


def test_ready_is_reported_only_after_both_servers_start(tmp_path: Path) -> None:
    services: list[dict[str, str]] = []
    servers: list[FakeServer] = []

    async def migrate(_database_url: str) -> None:
        pass

    def server_factory(_app: object, _host: str, _port: int, _name: str) -> FakeServer:
        server = FakeServer()
        servers.append(server)
        return server

    async def exercise() -> None:
        task = asyncio.create_task(
            run(
                RuntimeConfig(data_dir=tmp_path),
                migrate=migrate,
                build_apps=lambda _config: (object(), object()),
                server_factory=server_factory,
                ready=lambda value: services.append(dict(value)),
            )
        )
        while not services:
            await asyncio.sleep(0)
        for server in servers:
            server.should_exit = True
        with pytest.raises(RuntimeError, match="stopped unexpectedly"):
            await task

    asyncio.run(exercise())

    assert services == [
        {
            "aigateway": "http://127.0.0.1:9105",
            "engine": "http://127.0.0.1:9108",
        }
    ]


def test_migration_failure_has_a_named_startup_error(tmp_path: Path) -> None:
    async def fail(_database_url: str) -> None:
        raise ValueError("database is read-only")

    with pytest.raises(
        RuntimeError, match="AI Gateway database migration failed.*read-only"
    ):
        asyncio.run(run(RuntimeConfig(data_dir=tmp_path), migrate=fail))


def test_bundled_runner_config_matches_the_deployment_config() -> None:
    deployment = Path(__file__).resolve().parents[3] / "url4-cloud" / "url4.toml"

    assert runner_config_path().read_text().rstrip() == deployment.read_text().rstrip()
