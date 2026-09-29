"""Deleting named scores from a public board (OME-1385, for OME-1384).

The second operator module here that destroys, after `retire_benchmark`. The tests are ordered
around the risk: what SURVIVES is pinned before what is deleted.

INVARIANT under every test below: nothing is deleted unless the operator passed `confirmed` AND
the selection matched exactly the count they stated. Every refusal leaves every row in place.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tortoise import BaseDBAsyncClient

from scoreboard.delete_scores import Deletion, DeletionRefused, delete_scores
from scoreboard.export_private_submissions import format_jsonl_bytes
from scoreboard.scores.models import IdempotencyKey, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "draco-3pass"
OTHER = "ifeval"
OLD = datetime(2026, 9, 8, 15, tzinfo=UTC)
NEW = datetime(2026, 9, 25, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 9, tzinfo=UTC)


def _submission(benchmark_id: str, spec_id: str) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=benchmark_id,
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{spec_id}",
        submitted_by="irina@example.test",
        score=0.5,
        total_questions=100,
        correct_questions=50,
        ran_with_providers=["openrouter"],
        run_cost_usd=Decimal("0.000000"),
        run_cost_status="complete",
    )


async def _score(benchmark_id: str, spec_id: str, submitted_at: datetime) -> uuid.UUID:
    outcome = await ScoreStore().submit(
        _submission(benchmark_id, spec_id), idempotency_key=f"key-{benchmark_id}-{spec_id}"
    )
    # `submitted_at` is auto_now_add, so the age the cutoff reads is set after insertion.
    await Score.filter(id=outcome.score.id).update(submitted_at=submitted_at)
    return outcome.score.id


async def _seed() -> dict[str, uuid.UUID]:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id=BOARD, display_name="Draco 3-pass")
    await store.register_benchmark(benchmark_id=OTHER, display_name="IFEval")
    return {
        "old_a": await _score(BOARD, "old-a", OLD),
        "old_b": await _score(BOARD, "old-b", OLD),
        "new": await _score(BOARD, "new", NEW),
        "other_old": await _score(OTHER, "other-old", OLD),
    }


async def _confirm(
    benchmark_id: str,
    *,
    expected: int,
    score_ids: list[uuid.UUID] | None = None,
    submitted_before: datetime | None = None,
) -> Deletion:
    """Delete the way an operator must: dry run, then confirm with that run's backup digest."""
    reviewed = await delete_scores(
        benchmark_id, score_ids=score_ids, submitted_before=submitted_before, expected=expected
    )
    return await delete_scores(
        benchmark_id,
        score_ids=score_ids,
        submitted_before=submitted_before,
        expected=expected,
        confirmed=True,
        expected_sha256=reviewed.sha256(),
    )


async def _remaining() -> set[uuid.UUID]:
    return {score.id for score in await Score.all()}


# --- Nothing is deleted by default --------------------------------------------------------------


async def test_a_dry_run_reports_the_selection_and_deletes_nothing(tortoise_db: None) -> None:
    ids = await _seed()

    result = await delete_scores(BOARD, submitted_before=CUTOFF, expected=2)

    assert not result.deleted
    assert {row.id for row in result.rows} == {ids["old_a"], ids["old_b"]}
    assert await _remaining() == set(ids.values())
    assert "would delete 2" in result.describe()


async def test_a_count_mismatch_refuses_and_deletes_nothing_even_when_confirmed(
    tortoise_db: None,
) -> None:
    """INVARIANT: `--expect` is the operator's statement of what they reviewed.

    A filter that matches more, or fewer, than that is exactly the mistake this guards.
    """
    ids = await _seed()

    for expected in (1, 3):
        with pytest.raises(DeletionRefused, match="matched 2"):
            await delete_scores(
                BOARD,
                submitted_before=CUTOFF,
                expected=expected,
                confirmed=True,
                expected_sha256="0" * 64,
            )

    assert await _remaining() == set(ids.values())


# --- What is deleted -----------------------------------------------------------------------------


async def test_confirming_deletes_exactly_the_selection(tortoise_db: None) -> None:
    ids = await _seed()

    result = await _confirm(BOARD, submitted_before=CUTOFF, expected=2)

    assert result.deleted
    # The same board's newer row and another board's equally old row both survive.
    assert await _remaining() == {ids["new"], ids["other_old"]}
    assert "deleted 2" in result.describe()


async def test_selection_by_id_is_scoped_to_the_named_board(tortoise_db: None) -> None:
    """An id from another board is not matched, so the count check refuses the whole call."""
    ids = await _seed()

    with pytest.raises(DeletionRefused, match="matched 1"):
        await delete_scores(
            BOARD,
            score_ids=[ids["old_a"], ids["other_old"]],
            expected=2,
            confirmed=True,
            expected_sha256="0" * 64,
        )
    assert await _remaining() == set(ids.values())

    await _confirm(BOARD, score_ids=[ids["old_a"]], expected=1)
    assert await _remaining() == {ids["old_b"], ids["new"], ids["other_old"]}


async def test_a_deleted_scores_idempotency_keys_go_with_it(tortoise_db: None) -> None:
    ids = await _seed()

    await _confirm(BOARD, score_ids=[ids["old_a"]], expected=1)

    remaining_keys = {getattr(key, "score_id") for key in await IdempotencyKey.all()}
    assert ids["old_a"] not in remaining_keys
    assert ids["old_b"] in remaining_keys


# --- The backup ----------------------------------------------------------------------------------


async def test_the_backup_is_the_export_format_of_exactly_the_selection(tortoise_db: None) -> None:
    """WHY the export format: one format for "every field of a score", already staff-facing."""
    ids = await _seed()

    result = await delete_scores(BOARD, submitted_before=CUTOFF, expected=2)

    backup = result.backup()
    assert backup == format_jsonl_bytes(result.rows)
    lines = [json.loads(line) for line in backup.decode().splitlines()]
    assert {line["id"] for line in lines} == {str(ids["old_a"]), str(ids["old_b"])}
    # The FULL submitter address, which the public API would trim to its local part.
    assert {line["submitted_by"] for line in lines} == {"irina@example.test"}


async def test_the_backup_is_taken_before_the_rows_are_gone(tortoise_db: None) -> None:
    await _seed()

    result = await _confirm(BOARD, submitted_before=CUTOFF, expected=2)

    assert len(result.backup().decode().splitlines()) == 2


# --- Refusals ------------------------------------------------------------------------------------


async def test_an_unknown_board_is_a_lookup_error(tortoise_db: None) -> None:
    await _seed()

    with pytest.raises(LookupError, match="unknown benchmark_id"):
        await delete_scores("draco-3pas", submitted_before=CUTOFF, expected=2)


async def test_a_private_board_is_refused(tortoise_db: None) -> None:
    """Private boards have their own export-verified purge (OME-1027); this is no way round it."""
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="healthbench-worst30", display_name="HB", visibility="private"
    )

    with pytest.raises(DeletionRefused, match="purge_private_benchmark"):
        await delete_scores("healthbench-worst30", submitted_before=CUTOFF, expected=1)


@pytest.mark.parametrize(
    ("score_ids", "submitted_before"),
    [(None, None), ([uuid.uuid4()], CUTOFF)],
)
async def test_exactly_one_selector_is_required(
    tortoise_db: None, score_ids: list[uuid.UUID] | None, submitted_before: datetime | None
) -> None:
    await _seed()

    with pytest.raises(ValueError, match="exactly one"):
        await delete_scores(
            BOARD, score_ids=score_ids, submitted_before=submitted_before, expected=1
        )


async def test_a_selection_of_nothing_is_refused(tortoise_db: None) -> None:
    """Deleting zero rows is never what an operator meant, so `expected` must be positive."""
    await _seed()

    with pytest.raises(ValueError, match="at least 1"):
        await delete_scores(BOARD, submitted_before=CUTOFF, expected=0)


async def test_a_naive_cutoff_is_refused(tortoise_db: None) -> None:
    """A cutoff with no timezone means a different instant on every host. Refuse, never guess."""
    await _seed()

    with pytest.raises(ValueError, match="timezone"):
        await delete_scores(BOARD, submitted_before=datetime(2026, 9, 9), expected=2)


async def test_a_short_delete_rolls_back_every_row(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: selection, count check and delete are one transaction.

    If the delete removes fewer rows than were selected (a row changed underneath it), the call
    refuses and the rows it DID remove come back. A half-done delete is never reported or kept.
    """
    from scoreboard import delete_scores as module

    ids = await _seed()
    real = module._delete_rows

    async def _deletes_only_the_first(
        connection: BaseDBAsyncClient, score_ids: list[uuid.UUID]
    ) -> int:
        return await real(connection, score_ids[:1])

    monkeypatch.setattr(module, "_delete_rows", _deletes_only_the_first)

    with pytest.raises(DeletionRefused, match="deleted 1 of 2"):
        await _confirm(BOARD, submitted_before=CUTOFF, expected=2)

    assert await _remaining() == set(ids.values())


async def test_the_public_check_locks_the_board_inside_the_deleting_transaction(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT (OME-894): visibility is re-read LOCKED, on the connection that deletes.

    Read outside the transaction, a board flipped private in between would lose its rows without
    the export proof `purge_private_benchmark` demands. That `visibility_query(lock=True)` really
    emits `FOR UPDATE` on PostgreSQL is proven by
    `guards/test_visibility_exit_guard.py::test_the_persist_and_purge_paths_really_lock_the_row`;
    this pins that the delete path asks for it, on the transaction's own connection.
    """
    await _seed()
    calls: list[tuple[object, bool]] = []
    real = ScoreStore.visibility_query

    def _recording(
        self: ScoreStore, benchmark_id: str, *, connection: object = None, lock: bool = False
    ) -> object:
        calls.append((connection, lock))
        return real(self, benchmark_id, connection=connection, lock=lock)

    monkeypatch.setattr(ScoreStore, "visibility_query", _recording)

    await _confirm(BOARD, submitted_before=CUTOFF, expected=2)

    # The dry run and the confirmed run each check; the deleting one is the last.
    assert len(calls) == 2
    connection, lock = calls[-1]
    assert lock is True
    assert connection is not None


# --- Review round 1 (2026-09-26): the delete is bound to the backup the operator reviewed -------
#
# The first version deleted, committed, and only then wrote the backup to stdout. A dropped
# `kubectl exec`, a full disk or a failed write in that window lost the rows AND the backup. The
# confirmed run now proves it is deleting exactly what the dry run showed: the SHA-256 of the
# selected rows' JSONL must equal the digest of the reviewed backup, checked inside the deleting
# transaction. The backup that matters is the one already on the operator's disk.


async def test_the_dry_run_reports_the_digest_of_its_backup(tortoise_db: None) -> None:
    await _seed()

    result = await delete_scores(BOARD, submitted_before=CUTOFF, expected=2)

    assert result.sha256() == hashlib.sha256(result.backup()).hexdigest()
    assert result.sha256() in result.describe()


async def test_confirming_without_the_reviewed_digest_is_refused(tortoise_db: None) -> None:
    ids = await _seed()

    with pytest.raises(ValueError, match="expected_sha256"):
        await delete_scores(BOARD, submitted_before=CUTOFF, expected=2, confirmed=True)

    assert await _remaining() == set(ids.values())


async def test_a_malformed_digest_is_refused(tortoise_db: None) -> None:
    await _seed()

    with pytest.raises(ValueError, match="64 hexadecimal"):
        await delete_scores(
            BOARD, submitted_before=CUTOFF, expected=2, confirmed=True, expected_sha256="abc"
        )


async def test_a_selection_that_changed_since_review_is_refused(tortoise_db: None) -> None:
    """INVARIANT: same count is not same rows. The digest catches a changed row the count cannot."""
    ids = await _seed()
    reviewed = await delete_scores(BOARD, submitted_before=CUTOFF, expected=2)
    await Score.filter(id=ids["old_a"]).update(score=0.99)

    with pytest.raises(DeletionRefused, match="changed since"):
        await delete_scores(
            BOARD,
            submitted_before=CUTOFF,
            expected=2,
            confirmed=True,
            expected_sha256=reviewed.sha256(),
        )

    assert await _remaining() == set(ids.values())


async def test_the_digest_is_compared_case_insensitively(tortoise_db: None) -> None:
    """`shasum` prints lower case; a pasted upper-case digest is the same statement."""
    ids = await _seed()
    reviewed = await delete_scores(BOARD, submitted_before=CUTOFF, expected=2)

    await delete_scores(
        BOARD,
        submitted_before=CUTOFF,
        expected=2,
        confirmed=True,
        expected_sha256=reviewed.sha256().upper(),
    )

    assert await _remaining() == {ids["new"], ids["other_old"]}
