"""The preflight an operator runs before `helm rollback` (OME-894).

FEATURE: OME-894 — privacy is enforced by CODE reading a column the database holds. Roll the code
back below the release that introduced it and the column stays put while nothing reads it, so a
private board serves every participant's submission to anyone. Verified against the merge base
`454253da`: its `ScoreStore.leaderboard()` contains no reference to `visibility` at all, so there
is no version of the old code that could be persuaded to filter.

Helm cannot guard this: `helm rollback` executes the TARGET revision's hooks
(`execHook(targetRelease, release.HookPreRollback, ...)`), and the pre-privacy revision's stored
manifest has no such hook. So the control is a preflight the operator runs, and this suite is what
keeps it honest (review of PR #719).
"""

from __future__ import annotations

import pytest

from scoreboard.check_rollback_safety import PrivateBoard, format_verdict, private_boards
from scoreboard.scores.schemas import ScoreSubmission, Visibility
from scoreboard.scores.store import ScoreStore

ALICE = "alice@example.test"


def _submission(benchmark_id: str, spec_id: str) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=benchmark_id,
        spec_id=spec_id,
        url4_expression=f"url4://{benchmark_id}/{spec_id}",
        submitted_by=ALICE,
        score=0.5,
        total_questions=100,
        correct_questions=50,
        ran_with_providers=["openai"],
    )


async def _register(store: ScoreStore, benchmark_id: str, visibility: Visibility) -> None:
    await store.register_benchmark(
        benchmark_id=benchmark_id,
        display_name=benchmark_id.title(),
        visibility=visibility,
    )


@pytest.mark.asyncio
async def test_a_database_with_no_private_board_is_safe_to_roll_back(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store, "hle", "public")
    await store.submit(_submission("hle", "spec-1"))

    assert await private_boards() == []


@pytest.mark.asyncio
async def test_a_private_board_is_reported_with_its_submission_count(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store, "healthbench-worst30", "private")
    await store.submit(_submission("healthbench-worst30", "spec-1"), identity_verified=True)
    await store.submit(_submission("healthbench-worst30", "spec-2"), identity_verified=True)

    assert await private_boards() == [
        PrivateBoard(
            benchmark_id="healthbench-worst30",
            display_name="Healthbench-Worst30",
            submissions=2,
        )
    ]


@pytest.mark.asyncio
async def test_public_boards_are_not_reported_even_when_they_hold_rows(tortoise_db: None) -> None:
    # INVARIANT: a public board's rows are ALREADY published, so rolling back exposes nothing new.
    # Reporting them would train operators to read the refusal as noise.
    store = ScoreStore()
    await _register(store, "hle", "public")
    await _register(store, "secret", "private")
    await store.submit(_submission("hle", "spec-1"))

    assert [board.benchmark_id for board in await private_boards()] == ["secret"]


@pytest.mark.asyncio
async def test_an_empty_private_board_is_still_refused(tortoise_db: None) -> None:
    # WHY refuse with nothing to leak yet: the check and the rollback are not one operation. A
    # board configured private with zero rows today is a board that accepts submissions the moment
    # the challenge opens, and the restored code would serve those unscoped. The configuration is
    # the hazard, not the current row count.
    store = ScoreStore()
    await _register(store, "healthbench-worst30", "private")

    boards = await private_boards()

    assert [board.submissions for board in boards] == [0]
    assert "0 submissions" in format_verdict(boards, running_version="0.1.1")


def test_the_verdict_names_the_version_that_must_not_be_rolled_below() -> None:
    # The floor is not a constant this module can hardcode: the privacy-aware release did not
    # exist when it was written. What IS knowable at runtime is the version doing the reporting,
    # and that is exactly the floor — this code reads `visibility`, so anything below it may not.
    verdict = format_verdict(
        [PrivateBoard(benchmark_id="secret", display_name="Secret", submissions=3)],
        running_version="9.9.9",
    )

    assert "9.9.9" in verdict
    assert "secret" in verdict


def test_a_safe_verdict_says_so_without_naming_a_procedure() -> None:
    verdict = format_verdict([], running_version="0.1.1")

    assert "SAFE" in verdict
    assert "DEPLOYMENT.md" not in verdict


def test_main_exits_nonzero_when_a_private_board_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # INVARIANT: the EXIT CODE is the whole enforcement. Printing a warning that scrolls past in a
    # terminal is what "advisory" means; a non-zero exit is what a runbook step, a CI gate or an
    # `&&` chain can actually stop on.
    from scoreboard import check_rollback_safety

    async def _fake_run() -> tuple[str, int]:
        return "REFUSED: ...", 1

    monkeypatch.setattr(check_rollback_safety, "_run", _fake_run)

    with pytest.raises(SystemExit) as exit_info:
        check_rollback_safety.main([])

    assert exit_info.value.code == 1
    assert "REFUSED" in capsys.readouterr().out


def test_main_exits_zero_when_nothing_is_private(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scoreboard import check_rollback_safety

    async def _fake_run() -> tuple[str, int]:
        return "SAFE: ...", 0

    monkeypatch.setattr(check_rollback_safety, "_run", _fake_run)

    check_rollback_safety.main([])

    assert "SAFE" in capsys.readouterr().out


async def _run_against_the_test_database(monkeypatch: pytest.MonkeyPatch) -> tuple[str, int]:
    """Drive the real `_run`, borrowing the already-open test connection.

    WHY this exists: the two `main` tests above monkeypatch `_run`, so they prove the exit code is
    PROPAGATED and nothing proves it is DERIVED. Mutating `0 if not boards else 1` to a bare `0`
    left the suite green — the enforcement was untested exactly where it is decided (review of
    PR #719). `init_db`/`close_db` are stubbed because the `tortoise_db` fixture already holds a
    connection; everything between them is production's.
    """
    from scoreboard import check_rollback_safety

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(check_rollback_safety, "init_db", _noop)
    monkeypatch.setattr(check_rollback_safety, "close_db", _noop)
    return await check_rollback_safety._run()


@pytest.mark.asyncio
async def test_run_derives_a_failing_exit_code_from_a_private_board(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ScoreStore()
    await _register(store, "healthbench-worst30", "private")
    await store.submit(_submission("healthbench-worst30", "spec-1"), identity_verified=True)

    verdict, code = await _run_against_the_test_database(monkeypatch)

    assert code == 1
    assert "REFUSED" in verdict
    assert "healthbench-worst30" in verdict


@pytest.mark.asyncio
async def test_run_derives_a_passing_exit_code_when_every_board_is_public(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ScoreStore()
    await _register(store, "hle", "public")
    await store.submit(_submission("hle", "spec-1"))

    verdict, code = await _run_against_the_test_database(monkeypatch)

    assert code == 0
    assert "SAFE" in verdict


def test_the_refusal_points_at_a_section_that_exists() -> None:
    # INVARIANT: the refusal tells an operator where to go next, and a pointer to a heading that
    # has since been renamed is worse than no pointer — it reads as authoritative. This is the
    # cheapest thing that keeps the module and DEPLOYMENT.md in step.
    from pathlib import Path

    from scoreboard.check_rollback_safety import DEPLOYMENT_DOC

    doc = Path(__file__).resolve().parents[2] / "DEPLOYMENT.md"
    heading = DEPLOYMENT_DOC.split('"')[1]

    # A substring search over the whole file is NOT enough: the phrase also appears in the
    # cross-link under "Upgrade And Rollback", so renaming the heading left this green. Match a
    # HEADING line — found by mutating the heading and watching this pass anyway.
    headings = [
        line for line in doc.read_text().splitlines() if line.startswith("#") and heading in line
    ]

    assert headings, (
        f"`check_rollback_safety` sends operators to a {heading!r} section of DEPLOYMENT.md, and "
        "no heading by that name exists."
    )
