"""The `python -m scoreboard.claim_copies` command (OME-1947; prd/score-claim.md K-18 to K-22,
K-27).

WHY a database file, as in `test_delete_scores_cli.py`: `main()` goes through `Settings()`,
`init_db()` and `close_db()` of its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from tortoise.exceptions import OperationalError

import scoreboard.claim_copies as claim_copies
from scoreboard.claim_copies import main
from scoreboard.core.copy_claims import ClaimResult
from tests.unit.test_claim_pass_at_start import MemoryClaims, seed_database_file


@pytest.fixture
def rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    url, seeded = seed_database_file(tmp_path / "scoreboard.sqlite3")
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", url)
    monkeypatch.setenv("SCOREBOARD_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setenv("SCOREBOARD_GATEWAY_ACTOR", "claims@example.test")
    return seeded


def _use(monkeypatch: pytest.MonkeyPatch, claims: MemoryClaims) -> None:
    monkeypatch.setattr(claim_copies, "build_copy_claims", lambda settings: claims)


def _lines(out: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in out.splitlines()]


def _expected(rows: list[tuple[str, str]], result: str | None) -> list[dict[str, Any]]:
    return [{"score_id": s, "frozen_copy_id": c, "result": result} for s, c in rows]


def test_the_command_claims_the_copy_of_each_score_on_public_and_private_boards(
    rows: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims = MemoryClaims()
    _use(monkeypatch, claims)

    status = main([])

    captured = capsys.readouterr()
    assert status == 0
    assert _lines(captured.out) == [
        *_expected(rows, "claimed"),
        {"scores": 3, "results": {"claimed": 3}},
    ]
    assert claims.calls == [c for _, c in rows]
    assert claims.closed is True
    assert "@" not in captured.out


def test_a_second_run_reports_already_for_each_copy(
    rows: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims = MemoryClaims()
    _use(monkeypatch, claims)
    main([])
    capsys.readouterr()

    status = main([])

    assert status == 0
    assert _lines(capsys.readouterr().out) == [
        *_expected(rows, "already"),
        {"scores": 3, "results": {"already": 3}},
    ]


def test_a_result_that_is_not_kept_is_printed_the_run_continues_and_the_status_is_3(
    rows: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims = MemoryClaims({rows[1][1]: [ClaimResult.EXPIRED]})
    _use(monkeypatch, claims)

    status = main([])

    lines = _lines(capsys.readouterr().out)
    assert status == 3
    assert lines[1] == {"score_id": rows[1][0], "frozen_copy_id": rows[1][1], "result": "expired"}
    assert lines[2]["result"] == "claimed"
    assert lines[-1] == {"scores": 3, "results": {"claimed": 2, "expired": 1}}
    assert claims.calls == [c for _, c in rows]


def test_no_answer_stops_the_run_with_status_1(
    rows: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims = MemoryClaims({rows[1][1]: [ClaimResult.UNAVAILABLE]})
    _use(monkeypatch, claims)

    status = main([])

    captured = capsys.readouterr()
    assert status == 1
    assert claims.calls == [rows[0][1], rows[1][1]]
    assert _lines(captured.out) == [
        *_expected(rows[:1], "claimed"),
        *_expected(rows[1:2], "unavailable"),
        {"scores": 2, "results": {"claimed": 1, "unavailable": 1}},
    ]
    assert "did not answer" in captured.err
    assert claims.closed is True


def test_no_gateway_url_exits_2_before_the_database_and_makes_no_call(
    rows: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SCOREBOARD_GATEWAY_URL", raising=False)
    init_calls: list[Any] = []

    async def init_recorder(*args: Any, **kwargs: Any) -> None:
        init_calls.append(args)

    monkeypatch.setattr(claim_copies, "init_db", init_recorder)
    send_calls: list[httpx.Request] = []

    async def send_recorder(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> None:
        send_calls.append(request)
        raise AssertionError("no HTTP call")

    monkeypatch.setattr(httpx.AsyncClient, "send", send_recorder)

    status = main([])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "SCOREBOARD_GATEWAY_URL" in captured.err
    assert init_calls == []
    assert send_calls == []


def test_dry_run_lists_each_score_and_makes_no_call(
    rows: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims = MemoryClaims()
    _use(monkeypatch, claims)

    status = main(["--dry-run"])

    assert status == 0
    assert _lines(capsys.readouterr().out) == [
        *_expected(rows, None),
        {"scores": 3, "results": {}},
    ]
    assert claims.calls == []
    assert claims.closed is True


@pytest.mark.usefixtures("rows")
def test_a_database_error_at_start_still_closes_the_claim_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = MemoryClaims()
    _use(monkeypatch, claims)

    async def broken_init_db(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("database is not available")

    monkeypatch.setattr(claim_copies, "init_db", broken_init_db)

    with pytest.raises(OperationalError):
        main([])

    assert claims.calls == []
    assert claims.closed is True
