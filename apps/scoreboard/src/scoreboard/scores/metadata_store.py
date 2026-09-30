"""Score metadata edits: the Tortoise adapter behind `PATCH /v1/scores/{id}` (E14a).

FEATURE: OME-1307 (E14a) — the owner of a submission edits `authors` and `paper_url` after
submit. The route (`routes/score_metadata.py`) is the inbound adapter and owns every FastAPI
concern; this module owns every Tortoise one. The scoreboard has no metadata port today and the
PRD does not ask for one.

INVARIANT: an edit never touches the recipe identity (`content_hash`, `score`, `spec_id`, rank).
The only columns written on a `Score` are `authors`, `paper_url`, `metadata_revision` and
`metadata_updated_at`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import NamedTuple, cast
from uuid import UUID

from tortoise import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent
from scoreboard.scores.schemas import MetadataHistoryEvent, MetadataValues, ScoreSchema
from scoreboard.scores.store import _score_to_schema


class MetadataEditOutcome(NamedTuple):
    score: ScoreSchema
    # False for the MD-D4 idempotent resend: the values already matched, nothing was written.
    changed: bool


class MetadataHistoryPage(NamedTuple):
    events: list[MetadataHistoryEvent]
    next_revision: int | None
    # The board the decision was taken from, so the route can re-check it before a public answer.
    benchmark_id: str
    # The board was private when the store decided, and the reader is its owner.
    private: bool


class ScoreNotFound(Exception):
    """Unknown id, or a private score the caller does not own (one refusal for both, OME-894)."""


class NotSubmissionOwner(Exception):
    """Public board, and the caller is not the owner of the submission."""


class MetadataRevisionConflict(Exception):
    """The `If-Match` revision is not the stored one. Carries the current state for the 412."""

    def __init__(self, current: ScoreSchema) -> None:
        super().__init__("metadata revision conflict")
        self.current = current


async def _lock_row(conn: BaseDBAsyncClient, score_id: UUID) -> Score | None:
    # WHY a module-level function: the PostgreSQL MD-6 test replaces it to pause the first editor
    # while it holds the row lock (pattern `_delete_rows` in `delete_scores.py`).
    # INVARIANT: a MODEL read (`.first()`), never `values()` or `exists()`, which build a fresh
    # query and silently drop the lock.
    return await Score.filter(id=score_id).using_db(conn).select_for_update().first()


def _benchmark_id(row: Score) -> str:
    return cast(str, getattr(row, "benchmark_id"))


def _authorize(row: Score, private: bool, editor: str | None) -> None:
    """Who may edit `row` (MD-E1, MD-D7). The owner is `Score.submitted_by` and nobody else.

    INVARIANT: a `ReportedResult.reporter` is never an owner (MD-D7), so this never reads one.
    """
    if private:
        # WHY `editor is None` is a refusal too: in `disabled` mode a private board stays inert,
        # the same rule `submit` applies (`PrivateBoardRequiresIdentity`).
        if editor is None or editor != row.submitted_by:
            raise ScoreNotFound
        return
    # `editor is None` on a public board is the disabled dev/local fallback only (MD-E2): in
    # `cloudflare_headers` mode `WriteIdentity` answers 401 before the store runs.
    if editor is not None and editor != row.submitted_by:
        raise NotSubmissionOwner


async def _conflict(conn: BaseDBAsyncClient, score_id: UUID) -> MetadataRevisionConflict:
    current = await Score.filter(id=score_id).using_db(conn).get()
    return MetadataRevisionConflict(_score_to_schema(current))


class ScoreMetadataStore:
    async def update_metadata(
        self,
        score_id: UUID,
        *,
        changes: Mapping[str, object],
        expected_revision: int,
        editor: str | None,
    ) -> MetadataEditOutcome:
        """Apply `changes` (only the keys the client sent) if `expected_revision` is current.

        INVARIANT (MD-D3): the row update and the event insert share one transaction; a failure
        of either rolls back both.
        INVARIANT (MD-D2): the update is conditional on the revision it read, so of two editors
        holding the same `If-Match` exactly one wins. The row lock serializes them on PostgreSQL;
        the `WHERE` holds on SQLite, where `select_for_update` is a no-op.
        """
        async with in_transaction() as conn:
            row = await _lock_row(conn, score_id)
            if row is None:
                raise ScoreNotFound
            benchmark = (
                await Benchmark.filter(id=_benchmark_id(row))
                .using_db(conn)
                .only("visibility")
                .first()
            )
            # A board that turns private between the caller's read and this write is decided
            # once, here, inside the same transaction as the write.
            private = benchmark is None or benchmark.visibility == "private"
            _authorize(row, private, editor)

            before = {"authors": row.authors, "paper_url": row.paper_url}
            after = {**before, **changes}
            # INVARIANT (MD-D4): checked BEFORE the revision, so a resend after a lost response
            # is a 200 even though its `If-Match` is now stale. No event is written.
            if after == before:
                return MetadataEditOutcome(_score_to_schema(row), changed=False)
            if row.metadata_revision != expected_revision:
                raise MetadataRevisionConflict(_score_to_schema(row))

            updated = await (
                Score.filter(id=score_id, metadata_revision=expected_revision)
                .using_db(conn)
                .update(
                    **changes,
                    metadata_revision=expected_revision + 1,
                    metadata_updated_at=datetime.now(UTC),
                )
            )
            if updated != 1:
                raise await _conflict(conn, score_id)
            await ScoreMetadataEvent.create(
                using_db=conn,
                score_id=score_id,
                actor=editor,
                from_revision=expected_revision,
                to_revision=expected_revision + 1,
                before=before,
                after=after,
            )
            current = await Score.filter(id=score_id).using_db(conn).get()
            return MetadataEditOutcome(_score_to_schema(current), changed=True)

    async def metadata_history(
        self,
        score_id: UUID,
        *,
        reader: str | None,
        before_revision: int | None,
        limit: int,
    ) -> MetadataHistoryPage:
        """Newest-first events of one score, and the cursor of the next page (or `None`).

        INVARIANT: the same read rule as `GET /v1/scores/{id}` — a private board's history is
        readable only by the owner, and everyone else gets the one `ScoreNotFound` refusal.
        INVARIANT (OME-894): the events are read AFTER the visibility decision, so the page carries
        the decision (`private`, `benchmark_id`) and the route re-checks it before a public answer
        leaves.
        AIDEV-NOTE: never name the re-check helper in this docstring. The exit guard test matches
        source text, so the name would count as a revalidation this function does not perform.
        """
        row = await Score.get_or_none(id=score_id)
        if row is None:
            raise ScoreNotFound
        benchmark_id = _benchmark_id(row)
        benchmark = await Benchmark.get_or_none(id=benchmark_id)
        private = benchmark is None or benchmark.visibility == "private"
        if private and (reader is None or reader != row.submitted_by):
            raise ScoreNotFound
        query = ScoreMetadataEvent.filter(score_id=score_id)
        if before_revision is not None:
            query = query.filter(to_revision__lt=before_revision)
        rows = await query.order_by("-to_revision").limit(limit + 1)
        page = rows[:limit]
        return MetadataHistoryPage(
            events=[
                MetadataHistoryEvent(
                    actor=event.actor,
                    at=event.at,
                    from_revision=event.from_revision,
                    to_revision=event.to_revision,
                    before=MetadataValues.model_validate(event.before),
                    after=MetadataValues.model_validate(event.after),
                )
                for event in page
            ],
            next_revision=page[-1].to_revision if len(rows) > limit else None,
            benchmark_id=benchmark_id,
            private=private,
        )
