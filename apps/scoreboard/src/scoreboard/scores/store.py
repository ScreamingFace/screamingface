from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import InvalidOperation
from typing import Any, NamedTuple, cast
from uuid import UUID

from pypika_tortoise.analytics import RowNumber
from pypika_tortoise.enums import Order
from pypika_tortoise.queries import Query, QueryBuilder
from tortoise import Tortoise
from tortoise.exceptions import FieldError, IntegrityError
from tortoise.query_api import execute_pypika
from tortoise.transactions import in_transaction

from scoreboard.classification.openness import Openness

from .models import Benchmark, IdempotencyKey, Score
from .schemas import (
    BenchmarkSchema,
    LeaderboardEntry,
    ScoreSchema,
    ScoreSubmission,
    Visibility,
)

# INVARIANT: columns the raw leaderboard projection must convert itself. The
# projection bypasses the ORM, so nothing else will do it.
_RAW_ROW_FIELDS = ("ran_with_providers", "run_cost_usd")
# Columns whose DTO type admits None, so an unreadable value can degrade in place.
# Anything not listed here forces the row to be dropped instead — see _to_python_rows.
_NULLABLE_RAW_FIELDS = frozenset({"run_cost_usd"})

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL = timedelta(hours=24)


def benchmark_to_schema(model: Benchmark) -> BenchmarkSchema:
    """The ONE Benchmark -> DTO mapping.

    WHY public: `routes/leaderboard.py` used to carry a second hand-written copy of this
    projection. Adding `focus` (OME-874) broke that copy and not this one — the same
    semantic-conflict shape that took main red in OME-852. One mapper, one place to update.
    """
    return BenchmarkSchema(
        id=model.id,
        display_name=model.display_name,
        description=model.description,
        focus=model.focus,
        dataset_url=model.dataset_url,
        revision=model.revision,
        visibility=cast(Visibility, model.visibility),
        created_at=model.created_at,
    )


def _score_to_schema(model: Score) -> ScoreSchema:
    return ScoreSchema(
        id=model.id,
        version=model.version,
        benchmark_id=cast(str, getattr(model, "benchmark_id")),
        benchmark_revision=model.benchmark_revision,
        spec_id=model.spec_id,
        url4_expression=model.url4_expression,
        submitted_by=model.submitted_by,
        submitted_at=model.submitted_at,
        score=model.score,
        total_questions=model.total_questions,
        correct_questions=model.correct_questions,
        ran_with_providers=model.ran_with_providers,
        ran_at_local=model.ran_at_local,
        client_name=model.client_name,
        client_version=model.client_version,
        client_platform=model.client_platform,
        verified_by_screamingface=model.verified_by_screamingface,
        metadata=model.metadata,
        # WHY: tortoise-orm >=1.1.8 types CharField as `str | None`, which no longer
        # satisfies the schema's `Openness | None`. The DB column is a bare CharField, so
        # the narrowing is ours to assert; Pydantic still rejects a junk value on
        # construction, which is what actually enforces the invariant at runtime.
        openness_override=cast(Openness | None, model.openness_override),
        run_cost_usd=model.run_cost_usd,
    )


def _resolve_benchmark_revision(submission: ScoreSubmission) -> str | None:
    # WHY: the deployed Client sends the Engine benchmark revision nested in the free-form
    # `metadata` dict, not as a typed field (packages/screamingface/.../leaderboards.py).
    # Reading only the typed field would silently drop it for every client in the field;
    # rejecting the metadata copy would 422 every live submission. So the typed field wins
    # when usable and metadata is the fallback (OME-775 D5).
    # INVARIANT: this reads metadata, it never mutates or strips it — the payload is stored
    # exactly as sent.
    if submission.benchmark_revision:
        return submission.benchmark_revision
    candidate = (submission.metadata or {}).get("benchmark_revision")
    # INVARIANT: metadata is client-supplied and unvalidated, so a non-string or empty value
    # is absent input, never an error.
    return candidate if isinstance(candidate, str) and candidate else None


def _submission_to_kwargs(submission: ScoreSubmission, content_hash: str) -> dict[str, object]:
    return {
        "benchmark_id": submission.benchmark_id,
        "benchmark_revision": _resolve_benchmark_revision(submission),
        "version": submission.version,
        "spec_id": submission.spec_id,
        "url4_expression": submission.url4_expression,
        "submitted_by": submission.submitted_by,
        "score": submission.score,
        "total_questions": submission.total_questions,
        "correct_questions": submission.correct_questions,
        "ran_with_providers": submission.ran_with_providers,
        "ran_at_local": submission.ran_at_local,
        "client_name": submission.client.name if submission.client else None,
        "client_version": submission.client.version if submission.client else None,
        "client_platform": submission.client.platform if submission.client else None,
        "metadata": submission.metadata,
        # Deliberately absent from _content_hash: cost is a property of one
        # execution, not of the recipe. Two runs of the same recipe can cost
        # different amounts and must still dedup to a single row (OME-391).
        "run_cost_usd": submission.run_cost_usd,
        "content_hash": content_hash,
    }


def _content_hash(submission: ScoreSubmission) -> str:
    # WHY: identity is the recipe (what was run + its result), not who ran it or
    # when — submitted_by/client_*/ran_at_local/metadata are deliberately excluded.
    # Provider order is kept as submitted (not sorted) since it's part of what
    # actually happened, not incidental serialization (OME-391 / C28). `version` is
    # also excluded — currently a no-op since ScoreSubmission.version is pinned to
    # Literal[1], but revisit this if a future schema version is ever accepted, since
    # two payloads differing only in version would otherwise dedupe together.
    # OME-866: the submitted score is hashed EXACTLY as sent. The Engine benchmark is
    # the sole scoring authority and the route no longer tolerates approximate values,
    # so two payloads reporting different floats are genuinely different results.
    # correct_questions is deliberately absent — it is an optional binary-era detail,
    # not identity, and its presence or absence must not split dedup.
    # OME-775: the benchmark revision IS identity, unlike the rest of `metadata` it may arrive
    # in — a different dataset/protocol revision is a different thing measured, not incidental
    # provenance. It reads the RESOLVED value, not the wire position, so a client migrating
    # from the metadata form to the typed form does not duplicate its whole history.
    # AIDEV-NOTE: stored content_hash values predating this were computed WITHOUT the revision
    # and were deliberately not backfilled (D3). The bounded consequence: resubmitting a recipe
    # that predates this change creates a second row instead of deduping. Accepted over the
    # alternative, which silently discarded a second revision's result entirely.
    identity = {
        "benchmark_id": submission.benchmark_id,
        "benchmark_revision": _resolve_benchmark_revision(submission),
        "spec_id": submission.spec_id,
        "url4_expression": submission.url4_expression,
        "score": submission.score,
        "total_questions": submission.total_questions,
        "ran_with_providers": submission.ran_with_providers,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _to_python_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw projection rows to Python types, column by column.

    WHY: `_build_leaderboard_query` is raw pypika, so it returns whatever the
    driver hands back — on SQLite a DECIMAL column comes out as TEXT. Only
    `ran_with_providers` used to be converted; `run_cost_usd` reached
    LeaderboardEntry as a string and validated purely because Pydantic coerces
    str -> Decimal in lax mode.

    INVARIANT: rows are fully typed BEFORE validation, because spec 2.5 requires
    the cheapest-run stat to be computed in Python over Decimal — SQLite compares
    this column as TEXT, so `ORDER BY run_cost_usd` there ranks $1000 below $3.50.
    Anything reading these rows ahead of the DTO must not get a string.
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        drop = False
        for name in _RAW_ROW_FIELDS:
            if name not in row:
                continue
            try:
                # to_python_value maps None -> None for a nullable field, keeping
                # the absent-is-not-zero distinction (D5) intact.
                row[name] = Score._meta.fields_map[name].to_python_value(row[name])
            except (InvalidOperation, ValueError, FieldError) as exc:
                # INVARIANT: one corrupt row must never fail the whole read path.
                # DecimalField.to_python_value quantizes, and quantize RAISES on a
                # value outside DECIMAL(12, 6) — which surfaced as HTTP 500 for
                # EVERY entry on the board, not just the bad one. On SQLite the
                # column is VARCHAR(40) with no database-level guard, so raw SQL
                # can produce this; the ORM path and Postgres both reject it on
                # write. FieldError is in the tuple because JSONField raises it and
                # it is NOT a ValueError (found in review) — so corrupt JSON in
                # ran_with_providers used to 500 the board despite this guard.
                #
                # Logged at warning, never silently swallowed: a corrupt row is a
                # real problem and has to stay visible. Specific exceptions only.
                if name in _NULLABLE_RAW_FIELDS:
                    # Degrade to "unknown", a state the schema already models.
                    logger.warning(
                        "Unreadable %s on spec_id=%s (%r); serving it as null. The "
                        "stored value is outside the column's type and can only have "
                        "been written by raw SQL.",
                        name,
                        row.get("spec_id"),
                        row[name],
                        exc_info=exc,
                    )
                    row[name] = None
                else:
                    # INVARIANT: a non-nullable column cannot degrade. LeaderboardEntry
                    # types ran_with_providers as list[str], so None would fail
                    # validation and re-raise the 500 this guard exists to prevent. The
                    # only options are dropping the row or serving nothing, and one
                    # unreadable row must not cost every other row on the board.
                    #
                    # This DOES silently change what the board shows — a corrupt row
                    # disappears rather than appearing broken — which is why it is
                    # logged at WARNING with the spec_id, so the omission is traceable.
                    logger.warning(
                        "Unreadable %s on spec_id=%s (%r); DROPPING the row from this "
                        "response because the column is not nullable. The board will "
                        "be short one entry until the stored value is repaired.",
                        name,
                        row.get("spec_id"),
                        row[name],
                        exc_info=exc,
                    )
                    drop = True
                    break
        if not drop:
            kept.append(row)
    return kept


class SubmitOutcome(NamedTuple):
    score: ScoreSchema
    created: bool


def _build_leaderboard_query(
    benchmark_id: str,
    top_n: int,
    registered_revision: str | None,
    owner: str | None = None,
) -> QueryBuilder:
    scores = Score.get_table()
    # INVARIANT: every entry the board ranks was measured against the revision the benchmark is
    # REGISTERED at. The board presents a single ordered ranking, so admitting a second revision
    # would assert that two incomparable numbers can be compared — a stale-revision score could
    # hold rank 1 on a board registered elsewhere (OME-775).
    #
    # WHY partitioning alone was not enough: the window below stops one revision displacing
    # another in the best-per-spec collapse, but the outer query still orders every surviving
    # row into ONE score ranking. Both are needed — the partition keeps each revision's best
    # intact, the filter decides which revision the board is actually about.
    #
    # AIDEV-NOTE: a benchmark with NO registered revision filters nothing — the retained legacy
    # demo entries (hle/livetruth) have no Engine revision, and filtering would empty their
    # boards. Once a benchmark DOES declare one, a row that cannot be asserted comparable to it
    # (including a NULL row predating this column) does not rank.
    row_number = (
        RowNumber()
        .over(scores.spec_id, scores.benchmark_revision)
        .orderby(scores.score, order=Order.desc)
        .orderby(scores.submitted_at, order=Order.desc)
        .as_("rn")
    )
    ranked = (
        Query.from_(scores)
        .select(
            scores.spec_id,
            scores.benchmark_revision,
            scores.score,
            scores.total_questions,
            scores.ran_with_providers,
            scores.submitted_at,
            scores.submitted_by,
            scores.verified_by_screamingface,
            scores.url4_expression,
            scores.run_cost_usd,
            row_number,
        )
        .where(scores.benchmark_id == benchmark_id)
    )
    if owner is not None:
        # FEATURE: OME-894 — a private board shows the caller their own submissions and nobody
        # else's. Scoped in the QUERY: a post-filter would read every participant's row into
        # memory to serve one person, and would collide with `top_n` below by counting rows it
        # then discarded.
        ranked = ranked.where(scores.submitted_by == owner)
    if registered_revision is not None and owner is None:
        # INVARIANT (OME-894 D8): the revision filter above exists to stop incomparable numbers
        # being RANKED against each other. An owner-scoped read presents no ranking — a private
        # board suppresses rank entirely — so the filter has no purpose there, and applying it
        # would hide a participant's own submission with no explanation. That silent
        # disappearance is the failure that stranded a real DRACO run on 2026-08-19 (OME-909).
        ranked = ranked.where(scores.benchmark_revision == registered_revision)
    ranked = ranked.as_("ranked")

    return (
        Query.from_(ranked)
        .select(
            ranked.spec_id,
            ranked.benchmark_revision,
            ranked.score,
            ranked.total_questions,
            ranked.ran_with_providers,
            ranked.submitted_at,
            ranked.submitted_by,
            ranked.verified_by_screamingface,
            ranked.url4_expression,
            ranked.run_cost_usd,
        )
        .where(ranked.rn == 1)
        .orderby(ranked.score, order=Order.desc)
        .limit(top_n)
    )


class ScoreStore:
    async def register_benchmark(
        self,
        benchmark_id: str,
        display_name: str,
        description: str | None = None,
        dataset_url: str | None = None,
        revision: str | None = None,
        focus: str | None = None,
        visibility: Visibility = "public",
    ) -> BenchmarkSchema:
        benchmark, _ = await Benchmark.update_or_create(
            defaults={
                "display_name": display_name,
                "description": description,
                "dataset_url": dataset_url,
                "revision": revision,
                "focus": focus,
                # WHY in defaults, not only on create: seeding is idempotent, so a benchmark
                # mis-seeded as private must be able to flip back (OME-894).
                "visibility": visibility,
            },
            id=benchmark_id,
        )
        return benchmark_to_schema(benchmark)

    async def has_registered_revision(self) -> bool:
        """Has any benchmark row ever been registered with an Engine revision?

        INVARIANT: only a benchmark the Engine publishes carries a revision — the retained
        legacy demo entries have none — so a False answer means no successful Engine seed has
        ever run against this database (OME-904).
        """

        return await Benchmark.filter(revision__isnull=False).exists()

    async def list_benchmarks(self) -> list[BenchmarkSchema]:
        rows = await Benchmark.all().order_by("id")
        return [benchmark_to_schema(benchmark) for benchmark in rows]

    async def _resolve_existing(
        self,
        idempotency_key: str | None,
        content_hash: str,
    ) -> Score | None:
        # Shared by the pre-insert check and the post-IntegrityError race handler —
        # idempotency_key (a fast path keyed to one client's retry) takes priority
        # when present; content_hash is the unconditional backstop (OME-391 / C28).
        now_ts = datetime.now(UTC)
        if idempotency_key is not None:
            linked = await IdempotencyKey.get_or_none(
                key=idempotency_key,
                expires_at__gt=now_ts,
            ).prefetch_related("score")
            if linked is not None:
                return linked.score

        existing = await Score.get_or_none(content_hash=content_hash)
        if existing is not None and idempotency_key is not None:
            # INVARIANT: a content-hash hit with an idempotency_key attached must
            # bind that key to the found score NOW. Without this, the key stays
            # unbound and a later, unrelated submission reusing it would silently
            # rebind it to different content — breaking "the same key always
            # replays the same original result" (found in PR review, OME-391 / C28).
            await self._bind_idempotency_key(idempotency_key, existing, now_ts)
        return existing

    async def _bind_idempotency_key(
        self,
        idempotency_key: str,
        score: Score,
        now_ts: datetime,
    ) -> None:
        # Any stale (expired) row for this key is cleared first so it can be rebound
        # cleanly. IntegrityError on create means a concurrent request already won
        # this exact bind — the desired end state (key bound to this score) holds
        # either way, so it's safe to ignore.
        try:
            async with in_transaction() as connection:
                await (
                    IdempotencyKey.filter(key=idempotency_key, expires_at__lte=now_ts)
                    .using_db(connection)
                    .delete()
                )
                await IdempotencyKey.create(
                    using_db=connection,
                    key=idempotency_key,
                    score=score,
                    expires_at=now_ts + IDEMPOTENCY_TTL,
                )
        except IntegrityError:
            pass

    async def submit(
        self,
        submission: ScoreSubmission,
        idempotency_key: str | None = None,
    ) -> SubmitOutcome:
        now_ts = datetime.now(UTC)
        content_hash = _content_hash(submission)

        existing = await self._resolve_existing(idempotency_key, content_hash)
        if existing is not None:
            return SubmitOutcome(score=_score_to_schema(existing), created=False)

        expires_at = now_ts + IDEMPOTENCY_TTL
        try:
            async with in_transaction() as connection:
                if idempotency_key is not None:
                    await (
                        IdempotencyKey.filter(
                            key=idempotency_key,
                            expires_at__lte=now_ts,
                        )
                        .using_db(connection)
                        .delete()
                    )

                score = await Score.create(
                    using_db=connection,
                    **_submission_to_kwargs(submission, content_hash),
                )

                if idempotency_key is not None:
                    await IdempotencyKey.create(
                        using_db=connection,
                        key=idempotency_key,
                        score=score,
                        expires_at=expires_at,
                    )

            return SubmitOutcome(score=_score_to_schema(score), created=True)
        except IntegrityError:
            # A concurrent request may have won the race on either constraint.
            existing = await self._resolve_existing(idempotency_key, content_hash)
            if existing is not None:
                return SubmitOutcome(score=_score_to_schema(existing), created=False)
            raise

    async def get_by_idempotency_key(self, key: str) -> ScoreSchema | None:
        now_ts = datetime.now(UTC)
        linked = await IdempotencyKey.get_or_none(
            key=key,
            expires_at__gt=now_ts,
        ).prefetch_related("score")
        if linked is None:
            return None
        return _score_to_schema(linked.score)

    async def cleanup_expired_idempotency_keys(self, now: datetime) -> int:
        return await IdempotencyKey.filter(expires_at__lte=now).delete()

    async def leaderboard(
        self, benchmark_id: str, top_n: int = 50, owner: str | None = None
    ) -> list[LeaderboardEntry]:
        conn = Tortoise.get_connection("default")
        # The board is defined by the revision its benchmark is registered at; entries measured
        # against anything else are not comparable to it and do not rank (OME-775).
        benchmark = await Benchmark.get_or_none(id=benchmark_id)
        result = await execute_pypika(
            _build_leaderboard_query(
                benchmark_id,
                top_n,
                benchmark.revision if benchmark else None,
                owner,
            ),
            using_db=conn,
        )
        rows = _to_python_rows(result.rows)

        return [LeaderboardEntry(**row) for row in rows]

    async def list_for_spec(
        self,
        benchmark_id: str,
        spec_id: str,
        limit: int = 50,
        owner: str | None = None,
    ) -> list[ScoreSchema]:
        # OME-894: `owner` scopes the history to one participant on a private board. Applied as
        # a queryset filter, so the limit counts only rows the caller may see.
        query = Score.filter(benchmark_id=benchmark_id, spec_id=spec_id)
        if owner is not None:
            query = query.filter(submitted_by=owner)
        rows = await query.order_by("-submitted_at").limit(limit)
        return [_score_to_schema(score) for score in rows]

    async def list_all_for_benchmark(
        self, benchmark_id: str, owner: str | None = None
    ) -> list[ScoreSchema]:
        """Every Score row for a benchmark, chronologically — unlike `leaderboard()`
        (best-per-spec only), this is what OME-323's frontier trend needs: the full
        submission history across all specs, deliberately benchmark-wide (spec §6's
        frontier-scope resolution).
        """
        query = Score.filter(benchmark_id=benchmark_id)
        if owner is not None:
            # OME-894: scoped so no aggregate over other participants can be derived from it.
            query = query.filter(submitted_by=owner)
        rows = await query.order_by("submitted_at")
        return [_score_to_schema(score) for score in rows]

    async def mark_verified(self, score_id: UUID | str) -> None:
        await Score.filter(id=score_id).update(verified_by_screamingface=True)
