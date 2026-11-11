import httpx
import pytest

from scoreboard.check_sources import check_board_sources
from scoreboard.scores.baseline_store import BaselineStore
from tests.unit.scores.test_baseline_comparison import BOARD, _board, _row


@pytest.mark.asyncio
async def test_board_command_checks_shared_source_once_and_persists_failures(tortoise_db):
    await _board()
    await BaselineStore().import_many(
        [
            _row(model_name="One", source_url="https://example.org/table"),
            _row(model_name="Two", source_url="https://example.org/table"),
            _row(model_name="Three", source_url="https://example.org/missing"),
        ]
    )
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200 if req.url.path == "/table" else 404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await check_board_sources(BOARD, client)
    assert summary == {"checked": 2, "available": 1, "unchecked": 1}
    assert sorted(calls) == ["/missing", "/table"]
    rows = {row.model_name: row for row in await BaselineStore().list_baselines(BOARD)}
    assert rows["One"].source_health == rows["Two"].source_health
    assert rows["Three"].source_health is not None
    assert rows["Three"].source_health.available is False
    assert rows["Three"].source_health.last_available_at is None


@pytest.mark.asyncio
async def test_empty_board_and_unknown_board_make_no_requests(tortoise_db):
    await _board()

    def forbidden(req):
        pytest.fail("unexpected network request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        assert await check_board_sources(BOARD, client) == {
            "checked": 0,
            "available": 0,
            "unchecked": 0,
        }
        with pytest.raises(ValueError, match="unknown benchmark"):
            await check_board_sources("missing", client)


@pytest.mark.asyncio
async def test_operator_runner_uses_guarded_client_and_closes_database(monkeypatch):
    from unittest.mock import AsyncMock

    from scoreboard import check_sources
    from scoreboard.source_probe import PublicSourceTransport

    opened = AsyncMock()
    closed = AsyncMock()

    async def checked(board, client):
        assert board == BOARD
        assert isinstance(client._transport, PublicSourceTransport)
        assert client.trust_env is False
        assert client.headers["user-agent"] == "ScreamingFace-SourceCheck/1.0"
        raise ValueError("unknown benchmark")

    monkeypatch.setattr(check_sources, "init_db", opened)
    monkeypatch.setattr(check_sources, "close_db", closed)
    monkeypatch.setattr(check_sources, "check_board_sources", checked)
    with pytest.raises(ValueError, match="unknown benchmark"):
        await check_sources._run(BOARD)
    opened.assert_awaited_once()
    closed.assert_awaited_once()


def test_command_prints_counts_and_reports_invalid_board(monkeypatch, capsys):
    from unittest.mock import AsyncMock

    from scoreboard import check_sources

    runner = AsyncMock(return_value={"checked": 2, "available": 1, "unchecked": 1})
    monkeypatch.setattr(check_sources, "_run", runner)
    check_sources.main(["--benchmark-id", BOARD])
    assert capsys.readouterr().out == "Checked 2: 1 available, 1 unchecked\n"
    runner.assert_awaited_once_with(BOARD)
    runner.side_effect = ValueError("unknown benchmark")
    with pytest.raises(SystemExit) as caught:
        check_sources.main(["--benchmark-id", "missing"])
    assert caught.value.code == 2
    assert "unknown benchmark" in capsys.readouterr().err
