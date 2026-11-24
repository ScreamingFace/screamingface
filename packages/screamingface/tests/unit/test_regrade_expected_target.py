"""An operator's declared target constrains execution and submission, sync and async."""

from __future__ import annotations

import httpx
import pytest
from test_leaderboards import SCORE_ID, SCOREBOARD_URL
from test_regrade import (
    NEW_REVISION,
    OLD_REVISION,
    REGRADE_PATH,
    _Board,
    _Catalog,
    _client,
    _new_revision_replayer,
    _source,
)
from test_reproduce import _AsyncReplayer

import screamingface as sf
from screamingface.errors import ExecutionError, PlanningError


@pytest.mark.parametrize("stage", ["catalogue", "result", "success"])
def test_sync_target_is_checked_before_execution_and_submission(stage: str) -> None:
    expected = "different-target" if stage == "catalogue" else NEW_REVISION
    actual = "unexpected-result" if stage == "result" else NEW_REVISION
    engine = _new_revision_replayer(benchmark_revision=actual)
    board = _Board(public=_source())
    with _client(engine, _Catalog(regradable_from=[OLD_REVISION]), board) as client:
        if stage == "success":
            client.regrade(SCORE_ID, expected_target_revision=expected, progress=False)
        else:
            with pytest.raises((PlanningError, ExecutionError)) as exc:
                client.regrade(SCORE_ID, expected_target_revision=expected, progress=False)
            assert exc.value.code == "regrade_target_mismatch"
            assert exc.value.permanent is False
    assert engine.runs == (0 if stage == "catalogue" else 1)
    assert [path for path, _ in board.posts] == ([REGRADE_PATH] if stage == "success" else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["catalogue", "result", "success"])
async def test_async_target_is_checked_before_execution_and_submission(stage: str) -> None:
    expected = "different-target" if stage == "catalogue" else NEW_REVISION
    actual = "unexpected-result" if stage == "result" else NEW_REVISION
    engine = _AsyncReplayer(cases=((1, None), (2, None), (3, None)), benchmark_revision=actual)
    board = _Board(public=_source())
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_Catalog(regradable_from=[OLD_REVISION])),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=engine,
    ) as client:
        if stage == "success":
            await client.regrade(SCORE_ID, expected_target_revision=expected, progress=False)
        else:
            with pytest.raises((PlanningError, ExecutionError)) as exc:
                await client.regrade(SCORE_ID, expected_target_revision=expected, progress=False)
            assert exc.value.code == "regrade_target_mismatch"
            assert exc.value.permanent is False
    assert engine.runs == (0 if stage == "catalogue" else 1)
    assert [path for path, _ in board.posts] == ([REGRADE_PATH] if stage == "success" else [])


@pytest.mark.parametrize("expected", ["", " ", 123])
def test_invalid_expected_target_is_rejected_before_network_reads(expected: object) -> None:
    board = _Board(public=_source())
    engine = _new_revision_replayer()
    with _client(engine, _Catalog(regradable_from=[OLD_REVISION]), board) as client:
        with pytest.raises(ValueError, match="expected_target_revision"):
            client.regrade(SCORE_ID, expected_target_revision=expected)  # type: ignore[arg-type]
    assert board.reads == []
    assert engine.runs == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("expected", ["", " ", 123])
async def test_async_invalid_target_is_rejected_before_network_reads(expected: object) -> None:
    board = _Board(public=_source())
    engine = _AsyncReplayer(cases=((1, None),), benchmark_revision=NEW_REVISION)
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_Catalog(regradable_from=[OLD_REVISION])),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=engine,
    ) as client:
        with pytest.raises(ValueError, match="expected_target_revision"):
            await client.regrade(SCORE_ID, expected_target_revision=expected)  # type: ignore[arg-type]
    assert board.reads == []
    assert engine.runs == 0
