"""The claim pass in the app lifespan (OME-1947; prd/score-claim.md K-28, K-29, K-32, K-34)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import scoreboard.main as main_module
from scoreboard.config import Settings
from scoreboard.core.copy_claims import ClaimPassTask, ClaimResult
from scoreboard.main import create_app
from tests.unit.test_claim_pass_at_start import MemoryClaims, seed_database_file


def _wait_until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class StuckClaims:
    """A claim that does not return in 5 s. It records the end of the call, and a timeout."""

    def __init__(self, order: list[str]) -> None:
        self.started = threading.Event()
        self.timed_out = False
        self.order = order

    async def claim(self, copy_id: str) -> ClaimResult:
        self.started.set()
        try:
            await asyncio.wait_for(asyncio.Event().wait(), timeout=5)
        except TimeoutError:
            self.timed_out = True
        finally:
            self.order.append("task ended")
        return ClaimResult.CLAIMED

    async def aclose(self) -> None:
        self.order.append("client closed")


def _settings_for(url: str) -> Settings:
    return Settings(database_url=url, cors_origins=[])


def test_the_start_claims_the_copy_of_each_stored_score(tmp_path: Path) -> None:
    url, rows = seed_database_file(tmp_path / "scoreboard.sqlite3")
    claims = MemoryClaims()
    app = create_app(_settings_for(url), copy_claims=claims)

    with TestClient(app):
        task = app.state.claim_pass_task
        assert isinstance(task, ClaimPassTask)
        running = task.task
        assert running is not None
        assert _wait_until(running.done)

    assert claims.calls == [copy_id for _, copy_id in rows]
    assert claims.closed is True


def test_the_app_serves_a_request_while_the_pass_waits_on_a_claim(tmp_path: Path) -> None:
    url, _ = seed_database_file(tmp_path / "scoreboard.sqlite3")
    claims = StuckClaims([])

    with TestClient(create_app(_settings_for(url), copy_claims=claims)) as http:
        assert claims.started.wait(timeout=2)
        assert http.get("/healthz").status_code == 200

    assert claims.timed_out is False


def test_with_no_gateway_url_the_start_runs_no_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SCOREBOARD_GATEWAY_URL", raising=False)
    url, _ = seed_database_file(tmp_path / "scoreboard.sqlite3")
    send_calls: list[httpx.Request] = []

    async def send_recorder(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> None:
        send_calls.append(request)
        raise AssertionError("no HTTP call")

    monkeypatch.setattr(httpx.AsyncClient, "send", send_recorder)
    app = create_app(_settings_for(url))

    with TestClient(app) as http:
        assert http.get("/healthz").status_code == 200
        assert app.state.copy_claims is None
        assert app.state.claim_pass_task is None

    assert send_calls == []


def test_shutdown_ends_the_task_then_closes_the_client_then_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, _ = seed_database_file(tmp_path / "scoreboard.sqlite3")
    order: list[str] = []
    claims = StuckClaims(order)
    original_close = main_module.close_db

    async def recorded_close() -> None:
        order.append("database closed")
        await original_close()

    monkeypatch.setattr(main_module, "close_db", recorded_close)

    with TestClient(create_app(_settings_for(url), copy_claims=claims)):
        assert claims.started.wait(timeout=2)

    assert order == ["task ended", "client closed", "database closed"]
    assert claims.timed_out is False
