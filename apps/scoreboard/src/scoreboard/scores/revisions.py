"""The revision history of each benchmark: recording revisions and listing them for the selector.

FEATURE: OME-1708 — the revision selector on each leaderboard. `Benchmark` keeps only the
current revision; this module keeps every revision's own record (`BenchmarkRevision`) and
serves the list the selector shows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict
from tortoise import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError

from .models import BenchmarkRevision

if TYPE_CHECKING:
    from .store import ScoreStore

#: A safety bound on the revision note text the board stores (OME-2001). NOT the style target:
#: an author aims for about 120 characters and nothing fails on that. This only stops another
#: service's catalogue from putting unbounded text into the database and onto the page.
REVISION_NOTE_STORAGE_BOUND = 500


def usable_revision_note(value: object) -> str | None:
    """The note when it is one non-empty line within the storage bound, else None.

    One rule for both boundaries: the catalogue reader drops what this refuses, and
    `record_revision` raises on it.
    """

    if not isinstance(value, str):
        return None
    note: str = value.strip()
    if not note or len(note) > REVISION_NOTE_STORAGE_BOUND or not note.isprintable():
        return None
    return note


class RevisionSummary(BaseModel):
    """One revision as the selector shows it."""

    model_config = ConfigDict(extra="forbid")

    revision: str
    first_seen_at: datetime
    first_seen_inferred: bool
    # The next chronological first-seen time; None for current or an unknown end date.
    until: datetime | None
    case_count: int | None
    case_count_inferred: bool
    # INVARIANT: the number of rows that revision's board shows (best complete run per spec),
    # read through the board's own query, so the label never promises a count the board lacks.
    result_count: int
    current: bool
    # OME-2001: what changed in this revision and whether scores still compare, as the Engine
    # published it. None when no note was published; plain text, never markup.
    note: str | None = None


async def record_revision(
    benchmark_id: str, revision: str, case_count: int | None, note: str | None = None
) -> None:
    """Record a revision the first time the board sees it; fill only what is still unknown.

    INVARIANTS:
    - `first_seen_at` never moves: the seed job runs on every deploy, and a moving date would
      label every revision "since today".
    - A count the Engine gave is never rewritten. The Engine's count replaces a count that is
      unknown or was inferred by the migration (largest question count among results), because
      for the revision it still publishes the Engine's own count is authoritative.
    - The note follows the Engine (OME-2001): a note given here REPLACES the stored one, so a
      typo fixed on the Engine's row reaches the page; None KEEPS the stored one, so an Engine
      that serves no note never erases a reason readers already see.

    Raises:
        ValueError: `note` is given but is not one non-empty line within
            `REVISION_NOTE_STORAGE_BOUND` characters. Nothing is written.
    """

    if note is not None and usable_revision_note(note) != note:
        raise ValueError(
            "revision note must be one non-empty line of at most "
            f"{REVISION_NOTE_STORAGE_BOUND} characters"
        )
    existing = await BenchmarkRevision.get_or_none(benchmark_id=benchmark_id, revision=revision)
    if existing is None:
        try:
            await BenchmarkRevision.create(
                benchmark_id=benchmark_id,
                revision=revision,
                first_seen_at=datetime.now(UTC),
                case_count=case_count,
                note=note,
            )
        except IntegrityError:
            # WHY: two seed passes can race on the first sighting; the unique rule keeps one row
            # and the loser falls through to the fill step below.
            existing = await BenchmarkRevision.get(benchmark_id=benchmark_id, revision=revision)
        else:
            return
    changed: list[str] = []
    if case_count is not None and (existing.case_count is None or existing.case_count_inferred):
        existing.case_count = case_count
        existing.case_count_inferred = False
        changed += ["case_count", "case_count_inferred"]
    if note is not None and existing.note != note:
        existing.note = note
        changed.append("note")
    if changed:
        await existing.save(update_fields=changed)


async def find_revision(
    benchmark_id: str, revision: str, *, connection: BaseDBAsyncClient | None = None
) -> tuple[str, int | None, bool] | None:
    """Revision, Case count and whether it can support frontier claims; None if unknown."""

    rows = await (
        BenchmarkRevision.filter(benchmark_id=benchmark_id, revision=revision)
        .using_db(connection)
        .values("revision", "case_count", "case_count_inferred")
    )
    if not rows:
        return None
    row = rows[0]
    count = cast("int | None", row["case_count"])
    # INVARIANT: a client-supplied revision/count cannot establish a best-value claim.
    return cast("str", row["revision"]), count, count is not None and not row["case_count_inferred"]


async def list_revisions(
    store: ScoreStore,
    benchmark_id: str,
    *,
    registered_revision: str | None,
    registered_case_count: int | None,
    connection: BaseDBAsyncClient | None = None,
) -> list[RevisionSummary]:
    """Current first, then historical revisions by first sighting, with SQL-ranked counts."""

    if registered_revision is None:
        return []

    rows = await (
        BenchmarkRevision.filter(benchmark_id=benchmark_id)
        .using_db(connection)
        .order_by("-first_seen_at", "-id")
    )
    summaries: list[RevisionSummary] = []
    newer_seen_at: datetime | None = None
    for row in rows:
        current = row.revision == registered_revision
        # WHY: the seed can clear/change the live count without rewriting historical metadata.
        count = registered_case_count if current else row.case_count
        result_count = await store.leaderboard_count(
            benchmark_id,
            registered_revision=row.revision,
            registered_case_count=count,
            connection=connection,
        )
        summaries.append(
            RevisionSummary(
                revision=row.revision,
                first_seen_at=row.first_seen_at,
                first_seen_inferred=row.first_seen_inferred,
                until=None if current else newer_seen_at,
                case_count=count,
                case_count_inferred=False if current else row.case_count_inferred,
                result_count=result_count,
                current=current,
                note=row.note,
            )
        )
        newer_seen_at = row.first_seen_at
    # WHY: first sighting is not activation order. Empty Latest and rollbacks can have an
    # older first sighting than historical rows; preserve dates without mislabelling Latest.
    return sorted(summaries, key=lambda summary: not summary.current)
