"""Send each outside leaderboard submitter's progress to the 😱 SOTA pipeline in HubSpot.

FEATURE: OME-1504 (spec docs/spec/2026-11-18-hubspot-submission-sync.md). Runs as a CronJob every
few minutes: `python -m scoreboard.hubspot_sync [--dry-run]`.

AIDEV-NOTE: do not run it by hand (without `--dry-run`) while the CronJob is enabled. Two runs at
the same moment can both create a card for the same new person; the next run then sees two
cards and stops at `ambiguous_card` until someone merges them in HubSpot.

One run:
1. Queue every score that has no `hubspot_sync` row yet. Ineligible ones (the team, anything that
   is not an email, private boards) are `skipped` with a reason and never looked at again. Each
   eligible one records, once, whether it earns the SOTA flag (rule B).
2. Group the due rows by submitter, so one person is one HubSpot update however many new scores
   they have, and write the card their eligible scores call for.
3. Mark that person's rows `sent`, or `failed` with backoff.

INVARIANT: the submit path never calls HubSpot; this table is the queue, so a HubSpot outage only
delays cards. INVARIANT: every write is computed from ALL of a person's eligible scores, so
repeating one is harmless and a crash between two writes heals on the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from tortoise import BaseDBAsyncClient
from tortoise.expressions import Q, Subquery
from tortoise.transactions import in_transaction

from . import logs
from .classification.recipe_shape import recipe_shape
from .config import Settings
from .crm.decisions import (
    PROP_STAGE,
    CardState,
    Stages,
    Submission,
    Target,
    card_changes,
    card_name,
    ineligible_reason,
    last_active_to_write,
    new_card_properties,
    target_for,
)
from .crm.dry_run import DryRunSink
from .crm.hubspot import HubSpotSink, build_client
from .crm.port import Contact, CrmAuthFailed, CrmError, CrmRateLimited, CrmSink
from .crm.settings import HubSpotSyncSettings
from .db import DEFAULT_CONNECTION, close_db, init_db
from .scores.models import Baseline, HubSpotSyncRecord, Score
from .scores.models.hubspot_sync import (
    DUE_STATUSES,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
)
from .scores.store import ScoreStore

# INVARIANT: a fixed name, not `__name__`. The CronJob runs `python -m scoreboard.hubspot_sync`,
# where `__name__` is "__main__", outside the `scoreboard` logger tree that `logs.configure()`
# sets up, so every INFO line (the run summary included) was dropped in prod.
logger = logging.getLogger("scoreboard.hubspot_sync")

BACKOFF_START = timedelta(minutes=5)
BACKOFF_CAP = timedelta(hours=6)


@dataclass(frozen=True)
class SyncConfig:
    stages: Stages
    base_url: str
    internal_emails: frozenset[str]


@dataclass
class SyncSummary:
    queued: int = 0
    skipped: int = 0
    sent: int = 0
    failed: int = 0
    # Scores not examined yet plus rows still due: what a run without a token leaves behind.
    waiting: int = 0
    rate_limited: bool = False

    def line(self) -> str:
        # INVARIANT: counts only; no email, contact or card id reaches the CronJob's log.
        return (
            f"hubspot sync: queued={self.queued} skipped={self.skipped} sent={self.sent} "
            f"failed={self.failed} waiting={self.waiting} rate_limited={self.rate_limited}"
        )


def backoff(attempts: int) -> timedelta:
    """How long a submitter waits after their `attempts`-th failure: 5 min doubling, 6 h at most."""
    return min(BACKOFF_START * 2 ** max(attempts - 1, 0), BACKOFF_CAP)


class _Rollback(Exception):  # noqa: N818 - control flow, not an error
    def __init__(self, summary: SyncSummary) -> None:
        self.summary = summary


@dataclass(frozen=True)
class _Board:
    scores_by_id: dict[str, float]
    best_solo: float | None


class _Boards:
    """Rule B's view of each board, read once per run."""

    def __init__(self, connection: BaseDBAsyncClient | None) -> None:
        self._connection = connection
        self._store = ScoreStore()
        self._cache: dict[str, _Board] = {}

    async def get(self, benchmark_id: str) -> _Board:
        if benchmark_id not in self._cache:
            self._cache[benchmark_id] = await self._read(benchmark_id)
        return self._cache[benchmark_id]

    async def _read(self, benchmark_id: str) -> _Board:
        # WHY the store's board: rule B compares against the rows the public board ranks, at the
        # registered revision and Case count, not against every run ever stored.
        rows = await self._store.leaderboard(benchmark_id, None, connection=self._connection)
        shapes = {
            str(row["id"]): recipe_shape(row["url4_expression"])
            for row in await Score.filter(id__in=[row.source_id for row in rows])
            .using_db(self._connection)
            .values("id", "url4_expression")
        }
        solo = [row.score for row in rows if shapes.get(row.source_id) == "solo"]
        baselines = await (
            Baseline.filter(benchmark_id=benchmark_id).using_db(self._connection).values("score")
        )
        solo.extend(float(row["score"]) for row in baselines)
        return _Board(
            scores_by_id={row.source_id: row.score for row in rows},
            best_solo=max(solo) if solo else None,
        )

    async def qualifies(self, score: dict[str, Any]) -> bool:
        """Rule B (Filip, 2026-11-20): a fusion that beats every solo reference on its board.

        Solo is one model called once; anything else, one model sampled and combined included,
        is a fusion (Filip and Irina, 2026-11-26), read from the run's Recipe.

        INVARIANT: a board with no solo reference gives no flag, and a tie is not a win.
        """
        if recipe_shape(score["url4_expression"]) != "fusion":
            return False
        board = await self.get(score["benchmark_id"])
        on_board = board.scores_by_id.get(str(score["id"]))
        return on_board is not None and board.best_solo is not None and on_board > board.best_solo


async def _queue(
    connection: BaseDBAsyncClient | None, config: SyncConfig, summary: SyncSummary
) -> None:
    unseen = await (
        Score.filter(~Q(id__in=Subquery(HubSpotSyncRecord.all().values("score_id"))))
        .using_db(connection)
        .values(
            "id",
            "submitted_by",
            "benchmark_id",
            "url4_expression",
            "regraded_from_id",
            "benchmark__visibility",
        )
    )
    boards = _Boards(connection)
    records: list[HubSpotSyncRecord] = []
    for score in unseen:
        reason = ineligible_reason(score["submitted_by"], internal_emails=config.internal_emails)
        # WHY: a private board exists to keep results unpublished; they never leave the
        # scoreboard (spec decision 5). An unknown visibility reads as public, as on the board.
        if reason is None and (score["benchmark__visibility"] or "public") != "public":
            reason = "private_board"
        # INVARIANT: a re-grade (OME-1909) is the same run graded again, not a new submission;
        # it must not move a card, its link or the person's activity date.
        if reason is None and score["regraded_from_id"] is not None:
            reason = "regrade"
        if reason is not None:
            records.append(
                HubSpotSyncRecord(score_id=score["id"], status=STATUS_SKIPPED, reason=reason)
            )
            summary.skipped += 1
            continue
        records.append(
            HubSpotSyncRecord(
                score_id=score["id"],
                status=STATUS_PENDING,
                sota_qualified=await boards.qualifies(score),
            )
        )
        summary.queued += 1
    if records:
        await HubSpotSyncRecord.bulk_create(records, using_db=connection)


# An unknown visibility reads as public, as on the board.
_ON_PUBLIC_BOARD = Q(score__benchmark__visibility="public") | Q(
    score__benchmark__visibility__isnull=True
)


async def _revalidate(connection: BaseDBAsyncClient | None, email: str) -> int:
    """Skip this person's due rows whose board has gone private since they were queued.

    INVARIANT: visibility is checked again right before any HubSpot write, not only when a score
    is queued; a result its board has since hidden never leaves the scoreboard.
    """
    hidden = await (
        HubSpotSyncRecord.filter(status__in=DUE_STATUSES, score__submitted_by__iexact=email)
        .filter(~_ON_PUBLIC_BOARD)
        .using_db(connection)
        .values("id")
    )
    if hidden:
        await (
            HubSpotSyncRecord.filter(id__in=[row["id"] for row in hidden])
            .using_db(connection)
            .update(status=STATUS_SKIPPED, reason="private_board", next_attempt_at=None)
        )
    return len(hidden)


async def _still_due(connection: BaseDBAsyncClient | None, email: str) -> bool:
    return await (
        HubSpotSyncRecord.filter(status__in=DUE_STATUSES, score__submitted_by__iexact=email)
        .using_db(connection)
        .exists()
    )


async def _submissions(connection: BaseDBAsyncClient | None, email: str) -> list[Submission]:
    # INVARIANT: only scores on boards that are public NOW count, and never a re-grade; a sent
    # row on a board that later went private drops out of the count.
    rows = await (
        HubSpotSyncRecord.filter(score__submitted_by__iexact=email)
        .exclude(status=STATUS_SKIPPED)
        .filter(_ON_PUBLIC_BOARD, score__regraded_from_id__isnull=True)
        .using_db(connection)
        .values("score__benchmark_id", "score__spec_id", "score__submitted_at", "sota_qualified")
    )
    return [
        Submission(
            benchmark_id=row["score__benchmark_id"],
            spec_id=row["score__spec_id"],
            submitted_at=row["score__submitted_at"],
            sota_qualified=bool(row["sota_qualified"]),
        )
        for row in rows
    ]


def _fields(properties: dict[str, str]) -> str:
    # WHY names only: the values are public leaderboard links and counts, but a card name is a
    # person's name; the log says WHAT changed, HubSpot holds the values.
    return ", ".join(sorted(key for key in properties if key not in ("dealname", "dealstage")))


def _refusal(cards: list[CardState], stages: Stages) -> str | None:
    if len(cards) > 1:
        return "ambiguous_card"
    if cards and cards[0].stage_id == stages.dropped_out:
        return "dropped_out"
    return None


def _describe(stage_id: str, changes: dict[str, str]) -> str:
    parts = []
    if PROP_STAGE in changes:
        parts.append(f"stage {stage_id} -> {changes[PROP_STAGE]}")
    if _fields(changes):
        parts.append(f"set {_fields(changes)}")
    return ", ".join(parts) or "no change"


async def _write_card(
    sink: CrmSink,
    contact: Contact,
    card: CardState | None,
    properties: dict[str, str],
    *,
    announce: bool,
) -> None:
    """Update the person's card with `properties`, or create it when `card` is None."""
    if card is not None:
        await sink.update_card(card.id, properties)
        if announce:
            logger.info(
                "hubspot sync: card %s for contact %s: %s",
                card.id,
                contact.id,
                _describe(card.stage_id, properties),
            )
        return
    card_id = await sink.create_card(contact.id, properties)
    if announce:
        logger.info(
            "hubspot sync: created card %s for contact %s in stage %s, set %s",
            card_id,
            contact.id,
            properties[PROP_STAGE],
            _fields(properties),
        )


async def _apply(
    sink: CrmSink, email: str, target: Target, stages: Stages, *, announce: bool = False
) -> str | None:
    """Bring one person's contact and card in line with `target`; returns a non-send reason.

    INVARIANT (Bennett's rules): match the contact by email and create one only if none exists;
    update the person's one SOTA card rather than add another; never touch a Dropped out card.
    The two refusals are decided BEFORE anything is created.
    """
    contact = await sink.find_contact(email)
    cards = await sink.sota_cards(contact.id) if contact else []
    refusal = _refusal(cards, stages)
    if refusal is not None:
        if announce and contact is not None:
            logger.info("hubspot sync: contact %s left alone (%s)", contact.id, refusal)
        return refusal
    if contact is None:
        contact = await sink.create_contact(email)
        if announce:
            logger.info("hubspot sync: created contact %s", contact.id)
    day = last_active_to_write(contact.last_active, target.last_active)
    if day is not None:
        await sink.set_last_active(contact.id, day)
    if cards:
        properties = card_changes(cards[0], target, stages) or {}
    else:
        name = card_name(contact.first_name, contact.last_name, email)
        properties = new_card_properties(target, name=name)
    await _write_card(
        sink, contact, cards[0] if cards else None, dict(properties), announce=announce
    )
    return None


async def _mark(
    connection: BaseDBAsyncClient | None,
    email: str,
    *,
    status: str,
    reason: str | None,
    now: datetime,
) -> datetime | None:
    rows = HubSpotSyncRecord.filter(
        status__in=DUE_STATUSES, score__submitted_by__iexact=email
    ).using_db(connection)
    if status != STATUS_FAILED:
        await rows.update(status=status, reason=reason, next_attempt_at=None)
        return None
    # WHY one backoff per person: their rows succeed or fail together in one HubSpot update.
    attempts = 1 + max((int(row["attempts"]) for row in await rows.values("attempts")), default=0)
    next_attempt = now + backoff(attempts)
    await rows.update(
        status=STATUS_FAILED,
        reason=reason,
        attempts=attempts,
        next_attempt_at=next_attempt,
    )
    return next_attempt


async def _process(
    sink: CrmSink,
    connection: BaseDBAsyncClient | None,
    config: SyncConfig,
    now: datetime,
    summary: SyncSummary,
    *,
    announce: bool = False,
) -> None:
    due = await (
        HubSpotSyncRecord.filter(status__in=DUE_STATUSES)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .using_db(connection)
        .values_list("score__submitted_by", flat=True)
    )
    for email in sorted({str(address).lower() for address in due}):
        summary.skipped += await _revalidate(connection, email)
        submissions = await _submissions(connection, email)
        if not submissions or not await _still_due(connection, email):
            continue
        target = target_for(submissions, config.stages, config.base_url)
        try:
            refusal = await _apply(sink, email, target, config.stages, announce=announce)
        except CrmRateLimited:
            # WHY no attempt spent: HubSpot asked us to slow down; the next run carries on.
            summary.rate_limited = True
            return
        except CrmAuthFailed:
            raise
        except CrmError as error:
            retry = await _mark(connection, email, status=STATUS_FAILED, reason=str(error), now=now)
            if announce and retry is not None:
                # INVARIANT: no email in the log; the failed rows name the person in the database.
                logger.info(
                    "hubspot sync: one submitter failed (%s), next attempt %s",
                    error,
                    retry.isoformat(),
                )
            summary.failed += 1
            continue
        if refusal == "ambiguous_card":
            # WHY failed, not skipped: once a person merges the cards, the retry succeeds.
            await _mark(connection, email, status=STATUS_FAILED, reason=refusal, now=now)
            summary.failed += 1
            continue
        # WHY `sent` for Dropped out: the rows are handled; if the team brings the card back,
        # they must still count toward the person's submissions.
        await _mark(connection, email, status=STATUS_SENT, reason=refusal, now=now)
        summary.sent += 1


async def _waiting(now: datetime) -> int:
    unseen = await Score.filter(
        ~Q(id__in=Subquery(HubSpotSyncRecord.all().values("score_id")))
    ).count()
    due = (
        await HubSpotSyncRecord.filter(status__in=DUE_STATUSES)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .count()
    )
    return unseen + due


async def run_sync(
    sink: CrmSink | None, config: SyncConfig, *, now: datetime, dry_run: bool = False
) -> SyncSummary:
    """One sync run. `sink=None` (no token) only counts; `dry_run` reads HubSpot, writes nothing.

    INVARIANT: a dry run changes no row either: it runs in one transaction that is rolled back.
    """
    summary = SyncSummary()
    if sink is None:
        summary.waiting = await _waiting(now)
        return summary
    if not dry_run:
        await _queue(None, config, summary)
        await _process(sink, None, config, now, summary, announce=True)
        summary.waiting = await _waiting(now)
        return summary
    try:
        async with in_transaction(DEFAULT_CONNECTION) as connection:
            await _queue(connection, config, summary)
            await _process(DryRunSink(sink), connection, config, now, summary)
            raise _Rollback(summary)
    except _Rollback as rollback:
        return rollback.summary


async def _main(dry_run: bool) -> SyncSummary:
    settings = Settings()
    sync_settings = HubSpotSyncSettings()
    config = SyncConfig(
        stages=sync_settings.stages() if sync_settings.token else Stages((), ("", "", ""), ""),
        base_url=sync_settings.public_base_url,
        internal_emails=sync_settings.internal_emails,
    )
    await init_db(settings.database_url)
    try:
        if sync_settings.token is None:
            return await run_sync(None, config, now=datetime.now(UTC))
        async with build_client(sync_settings.token.get_secret_value()) as client:
            sink = HubSpotSink(
                client,
                pipeline_id=sync_settings.pipeline_id or "",
                app_id=sync_settings.app_id,
            )
            return await run_sync(sink, config, now=datetime.now(UTC), dry_run=dry_run)
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Send outside leaderboard submitters' progress to the SOTA pipeline in HubSpot."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read HubSpot and log every change it would make; send nothing and change no row",
    )
    args = parser.parse_args(argv)
    logs.configure()
    try:
        summary = asyncio.run(_main(args.dry_run))
    except CrmAuthFailed as error:
        # WHY loud: no submitter can succeed with a bad token; a failed CronJob run is the alert.
        raise SystemExit(f"hubspot sync stopped: HubSpot refused the token ({error})") from error
    logger.info(summary.line())
    if summary.waiting and not HubSpotSyncSettings().token:
        logger.info("hubspot sync: no token configured, nothing was sent")


if __name__ == "__main__":
    main()
