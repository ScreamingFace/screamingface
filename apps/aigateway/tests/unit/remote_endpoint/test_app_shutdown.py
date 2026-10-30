"""The app's shutdown: one cancelled step skips none of the cleanup steps after it.

# FEATURE: hosted BYOM Unit 1 — configured endpoint clients close with the app, beside the usage
# accounting handler, the cache snapshot scheduler, the loopback OAuth callbacks, the process-wide
# secret store and the database.
# INVARIANT: a cancellation that reaches one shutdown step, as a cancelled shutdown does, still
# lets every later step run once and in order; the cancellation is raised after them.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from .conftest import Harness

SHUTDOWN_STEPS = (
    "snapshot scheduler",
    "usage accounting",
    "remote endpoints",
    "loopback callbacks",
    "secret store",
    "database",
)


async def _nothing_to_stop() -> None:
    """The stand-in scheduler's real stop: no snapshot job runs in this app."""


@pytest.mark.parametrize(
    "cancelled_step",
    ["snapshot scheduler", "usage accounting", "remote endpoints", "loopback callbacks"],
)
def test_a_cancelled_shutdown_step_skips_none_of_the_steps_after_it(
    byom: Harness, monkeypatch: pytest.MonkeyPatch, cancelled_step: str
) -> None:
    from aigateway import main

    app = main.create_app()
    ran: list[str] = []
    real = {
        "snapshot scheduler": _nothing_to_stop,
        "usage accounting": app.state.taxonomy_plugin.close,
        "remote endpoints": main.close_remote_endpoints,
        "loopback callbacks": main.auth.close_loopback_callbacks,
        "database": main.close_db,
    }

    def step(name: str) -> Any:
        async def run(*args: Any) -> None:
            ran.append(name)
            if name == cancelled_step:
                raise asyncio.CancelledError
            await real[name](*args)

        return run

    def set_store(store: Any) -> None:
        if store is None:
            ran.append("secret store")
        main_set_store(store)

    main_set_store = main.set_active_secret_store
    # WHY a stand-in: the lifespan arms a real scheduler only when snapshots are enabled, and
    # stops whatever `app.state` holds.
    scheduler = SimpleNamespace(stop=step("snapshot scheduler"))
    monkeypatch.setattr(app.state, "cache_snapshot_scheduler", scheduler, raising=False)
    monkeypatch.setattr(app.state.taxonomy_plugin, "close", step("usage accounting"))
    monkeypatch.setattr(main, "close_remote_endpoints", step("remote endpoints"))
    monkeypatch.setattr(main.auth, "close_loopback_callbacks", step("loopback callbacks"))
    monkeypatch.setattr(main, "set_active_secret_store", set_store)
    monkeypatch.setattr(main, "close_db", step("database"))

    async def start_then_shut_down() -> None:
        try:
            async with app.router.lifespan_context(app):
                pass
        finally:
            if "database" not in ran:
                # WHY: a skipped database close leaves its worker thread, and the test, running.
                await real["database"]()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(start_then_shut_down())

    # INVARIANT: every step runs once, in order, whichever one the shutdown's cancellation hit.
    assert ran == list(SHUTDOWN_STEPS)
