"""`create_app` builds the archive reader and refuses half-configured publishing (plan 4.1).

FEATURE: OME-1307 (E14). INVARIANT under test: a partly set configuration fails at startup, naming
the missing variable and never a secret value.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from scoreboard.adapters.fs_archive_reader import FilesystemArchiveReader
from scoreboard.adapters.s3_archive_reader import S3ArchiveReader
from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.publish.worker import PublishWorker

_S3: dict[str, Any] = {
    "archive_backend": "s3",
    "archive_s3_endpoint_url": "http://garage.test:3900",
    "archive_s3_bucket": "cv",
    "archive_s3_access_key_id": "AKIATEST",
    "archive_s3_secret_access_key": "the-secret-value",
}


def _app(**values: Any) -> Any:
    return create_app(Settings.model_validate({"database_url": "sqlite://:memory:", **values}))


def test_no_archive_backend_means_no_reader() -> None:
    assert _app().state.archive_reader is None


def test_filesystem_backend_builds_the_filesystem_reader(tmp_path: Path) -> None:
    app = _app(archive_backend="filesystem", archive_fs_root=tmp_path)

    assert isinstance(app.state.archive_reader, FilesystemArchiveReader)


def test_s3_backend_builds_the_s3_reader() -> None:
    assert isinstance(_app(**_S3).state.archive_reader, S3ArchiveReader)


def test_filesystem_backend_without_a_root_is_refused() -> None:
    with pytest.raises(ValueError, match="SCOREBOARD_ARCHIVE_FS_ROOT"):
        _app(archive_backend="filesystem")


@pytest.mark.parametrize(
    ("missing", "variable"),
    [
        ("archive_s3_endpoint_url", "SCOREBOARD_ARCHIVE_S3_ENDPOINT_URL"),
        ("archive_s3_bucket", "SCOREBOARD_ARCHIVE_S3_BUCKET"),
        ("archive_s3_access_key_id", "SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID"),
        ("archive_s3_secret_access_key", "SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY"),
    ],
)
def test_s3_backend_with_a_missing_setting_is_refused_without_the_secret(
    missing: str, variable: str
) -> None:
    values = {key: value for key, value in _S3.items() if key != missing}

    with pytest.raises(ValueError, match=variable) as refused:
        _app(**values)

    assert "the-secret-value" not in str(refused.value)


_GITHUB: dict[str, Any] = {
    "github_app_id": "12345",
    "github_app_installation_id": "678",
    "github_app_private_key": "the-private-key-value",
}


def test_no_github_settings_means_no_publisher_factory() -> None:
    assert _app().state.release_publisher_factory is None


def test_all_three_github_settings_build_a_publisher_factory() -> None:
    assert callable(_app(**_GITHUB).state.release_publisher_factory)


@pytest.mark.parametrize(
    "missing",
    [
        ["github_app_id"],
        ["github_app_installation_id", "github_app_private_key"],
    ],
)
def test_a_partly_set_github_app_is_refused_naming_the_missing_variables(
    missing: list[str],
) -> None:
    values = {key: value for key, value in _GITHUB.items() if key not in missing}

    with pytest.raises(ValueError) as refused:
        _app(**values)

    for name in missing:
        assert f"SCOREBOARD_{name.upper()}" in str(refused.value)
    # WHY: the message names variables, never a value that is set.
    assert "the-private-key-value" not in str(refused.value)


def _lifespan_app(tmp_path: Path, **values: Any) -> Any:
    return _app(
        database_url=f"sqlite://{tmp_path / 'lifespan.sqlite3'}",
        auth_mode="cloudflare_headers",
        allowed_networks="127.0.0.1/32",
        archive_backend="filesystem",
        archive_fs_root=tmp_path,
        publish_poll_interval_s=0.01,
        **_GITHUB,
        **values,
    )


@pytest.fixture
def _forwarded_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")


@pytest.mark.asyncio
@pytest.mark.usefixtures("_forwarded_ips")
async def test_the_worker_loop_runs_inside_the_lifespan_and_stops_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = asyncio.Event()
    calls: list[int] = []

    async def run_once(self: PublishWorker) -> bool:
        calls.append(1)
        ran.set()
        return False

    monkeypatch.setattr(PublishWorker, "run_once", run_once)
    app = _lifespan_app(tmp_path)

    async with app.router.lifespan_context(app):
        await asyncio.wait_for(ran.wait(), timeout=5)
    settled = len(calls)
    await asyncio.sleep(0.05)

    # The loop is cancelled and awaited before the database closes: no call after shutdown.
    assert len(calls) == settled


@pytest.mark.asyncio
@pytest.mark.usefixtures("_forwarded_ips")
async def test_the_worker_loop_survives_an_iteration_error_and_logs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    recovered = asyncio.Event()
    calls: list[int] = []

    async def run_once(self: PublishWorker) -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        recovered.set()
        return False

    monkeypatch.setattr(PublishWorker, "run_once", run_once)
    caplog.set_level(logging.ERROR)
    app = _lifespan_app(tmp_path)

    async with app.router.lifespan_context(app):
        await asyncio.wait_for(recovered.wait(), timeout=5)

    assert "publish worker iteration failed" in caplog.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("_forwarded_ips")
async def test_no_worker_starts_when_it_is_disabled_or_publishing_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    async def run_once(self: PublishWorker) -> bool:
        calls.append(1)
        return False

    monkeypatch.setattr(PublishWorker, "run_once", run_once)
    disabled = _lifespan_app(tmp_path, publish_worker_enabled=False)
    unavailable = _app(
        database_url=f"sqlite://{tmp_path / 'other.sqlite3'}",
        auth_mode="cloudflare_headers",
        allowed_networks="127.0.0.1/32",
        publish_poll_interval_s=0.01,
    )

    for app in (disabled, unavailable):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)

    assert calls == []
