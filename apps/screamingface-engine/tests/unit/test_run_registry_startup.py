"""E5 P1 spec R9, D2, R3: how the App opens the Run registry, and what crosses the child pipe.

FEATURE: first-class Runs (OME-1785). INVARIANT: an unreachable database is named as one, never
reported as an unmigrated schema; a bare local Engine keeps its Runs out of a temp folder; the
child's own end time reaches the registry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import tortoise.context

from screamingface_engine import child_protocol
from screamingface_engine.config import Settings
from screamingface_engine.runs import db
from screamingface_engine.runs.wiring import (
    DatabaseUnreachableError,
    open_run_store,
    redacted_url,
)

UNREACHABLE = "postgres://engine:s3cret@127.0.0.1:1/engine"


@pytest.mark.asyncio
async def test_an_unreachable_database_is_named_not_reported_as_unmigrated() -> None:
    with pytest.raises(DatabaseUnreachableError, match="did not answer") as caught:
        await open_run_store(UNREACHABLE, Settings(), survives_restart=True, migrate_first=False)

    assert "127.0.0.1:1" in str(caught.value)
    assert "s3cret" not in str(caught.value)


def test_a_database_url_is_shown_without_its_password() -> None:
    assert redacted_url(UNREACHABLE) == "postgres://engine:***@127.0.0.1:1/engine"
    assert redacted_url("sqlite:///tmp/engine.sqlite3") == "sqlite:///tmp/engine.sqlite3"


@pytest.mark.asyncio
async def test_using_sets_the_context_tortoise_reads(tmp_path: object) -> None:
    """WHY: `db.using` sets Tortoise's private context variable (its public `with context:` shares
    one token across tasks). This fails if a Tortoise version stops reading that variable."""
    context = await db.open_context(f"sqlite://{tmp_path}/engine.sqlite3")
    try:
        outside = tortoise.context.get_current_context()
        with db.using(context):
            assert tortoise.context.get_current_context() is context
        assert tortoise.context.get_current_context() is outside
    finally:
        await context.close_connections()


def test_the_childs_end_time_crosses_the_control_pipe() -> None:
    ended = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    sent = child_protocol.Settled("succeeded", None, Decimal("0.5"), ended)

    received = child_protocol.decode_settled(child_protocol.encode_settled(sent))

    assert (received, received.finished_at) == (sent, ended)


@pytest.mark.parametrize("finished_at", [None, "yesterday", "2026-11-05T10:00:00"])
def test_a_settled_line_without_an_aware_end_time_is_refused(finished_at: object) -> None:
    line = b'SETTLED {"status":"succeeded","error_code":null,"cost_usd":null,"finished_at":'
    line += (b"null" if finished_at is None else f'"{finished_at}"'.encode()) + b"}\n"

    with pytest.raises(child_protocol.ProtocolError, match="finished_at"):
        child_protocol.decode_settled(line)


def test_the_local_runner_stops_before_the_runs_writer() -> None:
    """WHY: shutdown cancels in-flight runs, and their `stopped` outcomes must reach a writer
    that still consumes them, or the next start reconciles them as `lost`."""
    from screamingface_engine.local import create_local_app
    from screamingface_engine.runs.wiring import _RunsLifecycle

    app = create_local_app(Settings(jwt_secret="s" * 32), env={})
    owners = [getattr(hook, "__self__", None) for hook in app.router.on_shutdown]
    runner = owners.index(app.state.job_runner)
    runs = next(i for i, owner in enumerate(owners) if isinstance(owner, _RunsLifecycle))

    assert runner < runs


@pytest.mark.asyncio
async def test_a_database_that_never_answers_fails_the_start_within_the_probe_timeout(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHY: a blackholed host takes asyncpg's own 60 s, past the liveness kill; the probe gives
    up first so the start fails with its reason."""
    import asyncio

    from screamingface_engine.runs import wiring

    class _Silent:
        async def execute_query(self, _sql: str) -> None:
            await asyncio.Event().wait()

    monkeypatch.setattr(wiring, "_PROBE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(wiring, "get_connection", lambda _name: _Silent())

    with pytest.raises(DatabaseUnreachableError, match="TimeoutError"):
        await asyncio.wait_for(
            open_run_store(
                f"sqlite://{tmp_path}/engine.sqlite3",
                Settings(),
                survives_restart=False,
                migrate_first=False,
            ),
            timeout=5,
        )
