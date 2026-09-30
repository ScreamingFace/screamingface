"""PB-10, PB-12, PB-12a, PB-17 — `POST /v1/admin/results/{id}/withdraw` (C10, takedown).

FEATURE: OME-1307 (E14). D5: the main path runs `cloudflare_headers`; only PB-12a uses the
`disabled` fallback. INVARIANT under test: a takedown keeps the row and the head (PB-H4), and every
admin attempt leaves one audit line, refusals included.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from scoreboard import cli
from scoreboard.cli import configure_logging
from scoreboard.core.replay_access import replay_access
from scoreboard.routes.scores import UNTRUSTED_PEER_DETAIL
from scoreboard.scores.models import CacheVersionPublication
from tests.unit.publish._fakes import NOW, FakeReleasePublisher, Seeded
from tests.unit.publish._rows import seed_rows
from tests.unit.publish.conftest import ADMIN
from tests.unit.publish.test_worker import Build
from tests.unit.submissions._receipts import ANA, BRUNO, as_user

pytestmark = pytest.mark.asyncio

Seed = Callable[..., Awaitable[Seeded]]
_AUDIT = "scoreboard.routes.admin"


async def _withdraw(
    client: AsyncClient,
    result_id: str,
    user: str | None = ADMIN,
    reason: str = "license: not redistributable",
) -> Response:
    headers = as_user(user) if user is not None else {}
    return await client.post(
        f"/v1/admin/results/{result_id}/withdraw", json={"reason": reason}, headers=headers
    )


def _audit_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _AUDIT and record.getMessage().startswith("admin_action ")
    ]


async def _row(seeded: Seeded) -> CacheVersionPublication:
    return await CacheVersionPublication.get(result_id=seeded.result_id)


async def test_admin_withdraw_sets_withdrawn_deletes_release_keeps_row(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await seed_result(publish_client, board="pub")
    assert (
        await publish_client.post(f"/v1/results/{seeded.result_id}/publish", headers=as_user(ANA))
    ).status_code == 202
    worker = build_worker(seeded)
    await worker.run_once()
    assert (await _row(seeded)).state == "published"
    assert fake_publisher.releases

    response = await _withdraw(publish_client, seeded.result_id)

    assert response.status_code == 200
    assert response.json() == {"state": "withdrawn"}
    row = await _row(seeded)
    assert row.state == "withdrawn"
    assert row.withdrawn_by == ADMIN
    assert row.withdrawn_reason == "license: not redistributable"
    assert row.withdrawn_at == NOW
    assert await worker.run_once() is True
    assert fake_publisher.releases == {}
    assert fake_publisher.tags == set()
    assert (await _row(seeded)).next_attempt_at is None
    # PB-H4: the row and the head stay, with the marker.
    assert (await publish_client.get(f"/v1/scores/{seeded.head_id}")).status_code == 200
    board = (await publish_client.get("/v1/leaderboard/pub")).json()["entries"]
    assert [entry["spec_id"] for entry in board] == ["kevins-best"]


async def test_non_admin_withdraw_403_and_audited(
    publish_client: AsyncClient,
    publish_untrusted_client: AsyncClient,
    no_admin_client: AsyncClient,
    seed_result: Seed,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seeded = await seed_result(publish_client, board="pub")
    caplog.set_level(logging.INFO, logger=_AUDIT)

    not_admin = await _withdraw(publish_client, seeded.result_id, BRUNO)
    lines_after_403 = _audit_lines(caplog)
    anonymous = await _withdraw(publish_client, seeded.result_id, None)
    untrusted = await _withdraw(publish_untrusted_client, seeded.result_id, ADMIN)
    no_allowlist = await _withdraw(no_admin_client, seeded.result_id, ADMIN)

    assert not_admin.status_code == 403
    assert not_admin.json()["detail"]["code"] == "admin_required"
    assert len(lines_after_403) == 1
    assert "actor=bruno@y.org" in lines_after_403[0]
    assert f"result_id={seeded.result_id}" in lines_after_403[0]
    assert "outcome=403" in lines_after_403[0]
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "identity_not_verified"
    assert untrusted.status_code == 403
    assert untrusted.json()["detail"] == UNTRUSTED_PEER_DETAIL
    assert no_allowlist.status_code == 503
    assert no_allowlist.json()["detail"]["code"] == "admin_unavailable"
    lines = _audit_lines(caplog)
    assert any("actor=<unidentified>" in line and "outcome=401" in line for line in lines)
    assert any("actor=<unidentified>" in line and "outcome=403" in line for line in lines)
    assert (await _row(seeded)).state == "private"


async def test_withdraw_in_disabled_mode_is_503(publish_disabled_client: AsyncClient) -> None:
    seeded = await seed_rows(board="pub", state="published")

    response = await _withdraw(publish_disabled_client, seeded.result_id, ADMIN)

    # WHY forged header: `disabled` reads no identity, so a header proves nothing (D5).
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "admin_unavailable"
    assert (await _row(seeded)).state == "published"


async def test_withdraw_never_published_blocks_replay_no_github_call(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await seed_result(publish_client, board="pub")

    response = await _withdraw(publish_client, seeded.result_id)

    assert response.status_code == 200
    row = await _row(seeded)
    assert (row.state, row.next_attempt_at) == ("withdrawn", None)
    assert await build_worker(seeded).run_once() is False
    assert fake_publisher.calls == []
    assert (
        replay_access(
            board_visibility="public",
            redistributable=True,
            reporter=ANA,
            publication_state=row.state,
            caller="bruno@x.org",
            identity_verified=True,
        )
        == "withdrawn"
    )


async def test_withdraw_answers_404_409_and_is_idempotent(
    publish_client: AsyncClient, publish_app: FastAPI, seed_result: Seed
) -> None:
    unknown = await _withdraw(publish_client, "00000000-0000-4000-8000-000000000000")
    no_version = await seed_result(publish_client, board="pub", with_receipt=False)
    no_receipt = await _withdraw(publish_client, no_version.result_id)
    seeded = await seed_result(publish_client, board="pub")

    first = await _withdraw(publish_client, seeded.result_id)
    again = await _withdraw(publish_client, seeded.result_id, reason="second reason")

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "result not found"}
    assert no_receipt.status_code == 409
    assert no_receipt.json()["detail"]["reason"] == "no_cache_version"
    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json() == {"state": "withdrawn"}
    assert (await _row(seeded)).withdrawn_reason == "license: not redistributable"


@pytest.mark.parametrize(
    "body", [{}, {"reason": ""}, {"reason": "x" * 513}, {"reason": "r", "x": 1}]
)
async def test_withdraw_needs_a_bounded_reason(
    publish_client: AsyncClient, seed_result: Seed, body: dict[str, object]
) -> None:
    seeded = await seed_result(publish_client, board="pub")

    response = await publish_client.post(
        f"/v1/admin/results/{seeded.result_id}/withdraw", json=body, headers=as_user(ADMIN)
    )

    assert response.status_code == 422
    assert (await _row(seeded)).state == "private"


async def test_the_audit_line_holds_an_escaped_bounded_reason(
    publish_client: AsyncClient, seed_result: Seed, caplog: pytest.LogCaptureFixture
) -> None:
    seeded = await seed_result(publish_client, board="pub")
    caplog.set_level(logging.INFO, logger=_AUDIT)

    await _withdraw(
        publish_client, seeded.result_id, reason="x\nadmin_action actor=evil " + "*" * 300
    )

    (line,) = _audit_lines(caplog)
    reason = re.search(r"reason=(.*) outcome=", line)
    assert reason is not None
    # WHY: the reason is caller text; a newline would forge a second audit line.
    assert "\n" not in line
    assert len(reason.group(1)) <= 120
    assert "\\*" in reason.group(1)
    assert "outcome=200" in line


async def test_an_unexpected_error_is_audited_as_a_500(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = await seed_result(publish_client, board="pub")

    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is gone")

    monkeypatch.setattr(publish_app.state.publication_store, "withdraw", broken)
    caplog.set_level(logging.INFO, logger=_AUDIT)

    with pytest.raises(RuntimeError):
        await _withdraw(publish_client, seeded.result_id)

    (line,) = _audit_lines(caplog)
    assert "actor=admin@x.org" in line
    assert "outcome=500" in line


# MRA-1 and MRA-2 — the admin audit record reaches the log in production, and it holds the value
# before the change. The `admin_action` line above is pinned by prior tests, so the change record is
# a SECOND line on the same logger, written only when an attempt succeeded.


def _change_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _AUDIT and record.getMessage().startswith("admin_change ")
    ]


async def test_withdraw_of_a_private_row_records_before_and_after(
    publish_client: AsyncClient, seed_result: Seed, caplog: pytest.LogCaptureFixture
) -> None:
    seeded = await seed_result(publish_client, board="pub")
    caplog.set_level(logging.INFO, logger=_AUDIT)

    await _withdraw(publish_client, seeded.result_id, reason="licence")

    (line,) = _change_lines(caplog)
    assert line == (
        f"admin_change actor=admin@x.org result_id={seeded.result_id} "
        "before=private after=withdrawn reason=licence"
    )


async def test_withdraw_of_a_published_row_records_the_state_it_left(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seeded = await seed_result(publish_client, board="pub")
    await publish_client.post(f"/v1/results/{seeded.result_id}/publish", headers=as_user(ANA))
    await build_worker(seeded).run_once()
    caplog.set_level(logging.INFO, logger=_AUDIT)

    await _withdraw(publish_client, seeded.result_id)
    await _withdraw(publish_client, seeded.result_id)

    first, again = _change_lines(caplog)
    assert "before=published after=withdrawn" in first
    # A repeat is a no-op, and the record says so: the value did not change.
    assert "before=withdrawn after=withdrawn" in again


async def test_a_refused_or_failed_withdraw_writes_no_change_record(
    publish_client: AsyncClient, seed_result: Seed, caplog: pytest.LogCaptureFixture
) -> None:
    seeded = await seed_result(publish_client, board="pub")
    caplog.set_level(logging.INFO, logger=_AUDIT)

    refused = await _withdraw(publish_client, seeded.result_id, BRUNO)
    missing = await _withdraw(publish_client, "00000000-0000-4000-8000-000000000000")

    assert (refused.status_code, missing.status_code) == (403, 404)
    assert _change_lines(caplog) == []


async def test_redistributable_records_the_value_before_the_change(
    publish_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=_AUDIT)
    url = "/v1/admin/benchmarks/gated/redistributable"
    body = {"redistributable": True, "reason": "CC-BY"}

    flip = await publish_client.put(url, json=body, headers=as_user(ADMIN))
    repeat = await publish_client.put(url, json=body, headers=as_user(ADMIN))
    denied = await publish_client.put(url, json=body, headers=as_user(BRUNO))
    missing = await publish_client.put(
        "/v1/admin/benchmarks/nope/redistributable", json=body, headers=as_user(ADMIN)
    )

    assert [r.json().get("changed") for r in (flip, repeat)] == [True, False]
    assert (denied.status_code, missing.status_code) == (403, 404)
    flipped, repeated = _change_lines(caplog)
    assert flipped == (
        "admin_change actor=admin@x.org benchmark_id=gated before=false after=true reason=CC\\-BY"
    )
    assert "before=true after=true" in repeated


@pytest.fixture
def scoreboard_logger() -> Iterator[logging.Logger]:
    """The `scoreboard` logger, put back the way it was: the tests below configure it for real."""
    logger = logging.getLogger("scoreboard")
    level, handlers, propagate = logger.level, list(logger.handlers), logger.propagate
    yield logger
    logger.setLevel(level)
    logger.handlers[:] = handlers
    logger.propagate = propagate


async def test_the_audit_line_reaches_stderr_without_forcing_a_level(
    publish_client: AsyncClient,
    seed_result: Seed,
    scoreboard_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # INVARIANT (MRA-1): uvicorn configures only its own loggers, so a process that starts through
    # the CLI has root at WARNING and no handler. `configure_logging` is what makes the INFO audit
    # line visible. This test does NOT call `caplog.set_level`, which is what hid the bug.
    scoreboard_logger.handlers.clear()
    scoreboard_logger.setLevel(logging.NOTSET)
    seeded = await seed_result(publish_client, board="pub")

    configure_logging("info")
    await _withdraw(publish_client, seeded.result_id)

    err = capsys.readouterr().err
    assert f"admin_action actor=admin@x.org result_id={seeded.result_id}" in err
    assert "admin_change actor=admin@x.org" in err
    assert "INFO" in err


def test_configure_logging_honours_the_level_and_adds_one_handler(
    scoreboard_logger: logging.Logger,
) -> None:
    scoreboard_logger.handlers.clear()

    configure_logging("warning")
    configure_logging("warning")

    assert scoreboard_logger.level == logging.WARNING
    assert len(scoreboard_logger.handlers) == 1
    assert not logging.getLogger("scoreboard.routes.admin").isEnabledFor(logging.INFO)


def test_the_cli_configures_logging_before_it_starts_uvicorn(
    scoreboard_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoreboard_logger.handlers.clear()
    scoreboard_logger.setLevel(logging.NOTSET)
    seen: list[int] = []
    monkeypatch.setenv("SCOREBOARD_LOG_LEVEL", "debug")
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: seen.append(scoreboard_logger.level))

    cli.main()

    assert seen == [logging.DEBUG]
