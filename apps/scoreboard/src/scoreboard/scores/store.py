from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple, cast
from uuid import UUID

from pypika_tortoise.analytics import RowNumber
from pypika_tortoise.enums import Order
from pypika_tortoise.queries import Query, QueryBuilder
from tortoise import Tortoise
from tortoise.exceptions import FieldError, IntegrityError
from tortoise.expressions import Q
from tortoise.query_api import execute_pypika
from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from scoreboard.classification.openness import Openness

from .models import Benchmark, IdempotencyKey, Score
from .pareto import ParetoEntry
from .schemas import (
    BenchmarkSchema,
    LeaderboardEntry,
    LeaderboardStoreEntry,
    ScoreSchema,
    ScoreSubmission,
    Visibility,
)

# INVARIANT: columns the raw leaderboard projection must convert itself. The
# projection bypasses the ORM, so nothing else will do it.
_RAW_ROW_FIELDS = ("ran_with_providers", "authors", "run_cost_usd")
# Columns whose DTO type admits None, so an unreadable value can degrade in place.
# Anything not listed here forces the row to be dropped instead — see _to_python_rows.
_NULLABLE_RAW_FIELDS = frozenset({"authors", "run_cost_usd"})

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL = timedelta(hours=24)


class _Unset:
    """Distinguish an omitted update field from an explicit database NULL."""


_UNSET = _Unset()


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
        case_count=model.case_count,
        # A pre-migration row can carry NULL; it was world-readable before the column existed,
        # so it reads as public. The column stays nullable so 0008 need not rebuild the table.
        visibility=cast(Visibility, model.visibility or "public"),
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
        authors=_resolved_authors(model.authors, model.submitted_by),
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


def _resolved_authors(authors: list[str] | None, submitted_by: str | None) -> list[str] | None:
    """The backwards-compatible author credit shown for one stored submission."""
    if authors is not None:
        return authors
    return [submitted_by] if submitted_by is not None else None


def _resolve_raw_row_authors(row: dict[str, Any]) -> None:
    """Apply legacy author fallback only when a raw projection selected the field."""
    if "authors" in row:
        row["authors"] = _resolved_authors(row.get("authors"), row.get("submitted_by"))


def _submission_to_kwargs(submission: ScoreSubmission, content_hash: str) -> dict[str, object]:
    return {
        "benchmark_id": submission.benchmark_id,
        "benchmark_revision": _resolve_benchmark_revision(submission),
        "version": submission.version,
        "spec_id": submission.spec_id,
        "url4_expression": submission.url4_expression,
        "submitted_by": submission.submitted_by,
        "authors": submission.authors,
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


def _content_hash(submission: ScoreSubmission, *, per_submitter: bool = False) -> str:
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
    if per_submitter:
        # FEATURE: OME-894 — on a PRIVATE board the submitter is part of identity. Excluding it
        # collapses two participants who ran the same recipe into one row, so the second sees
        # nothing of their own while the response hands them the first participant's url4,
        # metadata and id. Per-person idempotency still holds, because the same submitter
        # resubmitting produces the same hash.
        # INVARIANT: public boards are NOT affected. OME-391's identity-is-the-recipe rule stays
        # exactly as it was there — splitting it would let anyone resubmit an existing public
        # recipe under their own name and duplicate the board.
        # AIDEV-NOTE: a benchmark that later changes visibility invalidates its stored hashes for
        # future resubmissions, so a resubmitted old recipe creates a second row. Bounded, and
        # the same no-backfill trade-off OME-775 recorded for benchmark_revision.
        identity["submitted_by"] = submission.submitted_by
        # AIDEV-NOTE: defaults to False so this stays the OME-391 recipe hash for every existing
        # caller. `submit()` is the one production call site and resolves the flag from the
        # benchmark itself, so a new call site cannot silently opt a private board back into
        # cross-participant collapse by forgetting an argument — it would have to route around
        # submit() entirely.
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
            # NULL is not an empty credit line. It means a legacy/unspecified submission and
            # therefore reads exactly as the old UI did: the submitter is its sole author.
            _resolve_raw_row_authors(row)
            kept.append(row)
    return kept


# INVARIANT: the single definition of the server-owned namespaces. Migration `0009` clears exactly
# these of client-written rows, so a third prefix added here must not be forgotten there —
# `test_no_generated_storage_token_is_a_fixed_point_of_the_public_path` and
# `test_migration_0009_clears_both_reserved_namespaces` are what turn that omission red.
RESERVED_KEY_PREFIXES = ("sfp-", "sfu-")

# INVARIANT (OME-894): stamped on every mapping THIS code writes. A reserved-namespace mapping is
# honoured only when it carries this, because `main` stores client keys verbatim and an old replica
# serving through a rollout can bind a predictable `sfp-` token to a row an attacker chose. Nothing
# a client sends can set this column; an old pod's INSERT omits it and it reads back NULL.
KEY_SCHEME = "v2"


def _scoped_idempotency_key(
    idempotency_key: str | None, submitted_by: str | None, *, per_submitter: bool
) -> str | None:
    """Return a bounded, domain-separated storage token for a client idempotency key.

    INVARIANT: the stored value must survive `IdempotencyKey.key`, a VARCHAR(255) column, on
    PostgreSQL. An earlier version joined submitter and key with a literal NUL, which SQLite
    accepts and PostgreSQL rejects outright — `invalid byte sequence for encoding "UTF8": 0x00`,
    verified against postgres:16 — so every private submission carrying an Idempotency-Key would
    have failed only in production. Concatenation could also exceed 255 characters.

    Hashing solves both: separators survive only inside the digest input, never in the stored
    value, and the result is fixed-length printable ASCII. Public keys remain verbatim unless a
    caller tries to occupy the reserved `sfp-` private namespace. Such keys are escaped to a
    bounded `sfu-` token; otherwise a caller could submit the predictable private token as its raw
    public key and the key-first lookup would return the linked private score. This preserves the
    established global public-key representation while making private storage unreachable from
    client-controlled public values.

    AIDEV-NOTE: the value is opaque by design. Nothing reads it back to recover the submitter —
    `get_by_idempotency_key` has no production caller — so it is a lookup token, not a record.
    """
    if idempotency_key is None:
        return None
    if per_submitter:
        namespace = f"private\x00{submitted_by or ''}"
        prefix = "sfp-"
    elif idempotency_key.startswith(RESERVED_KEY_PREFIXES):
        # INVARIANT: BOTH server-owned prefixes are reserved, not just the private one. Escaping
        # only `sfp-` left the escaped form itself client-suppliable: a caller could send the
        # generated `sfu-<digest>` as an ordinary raw key, the `else` below stored it verbatim, and
        # two distinct client keys addressed ONE mapping — so the second POST replayed the first
        # caller's score. Any value that could collide now begins `sfu-` and is escaped in turn,
        # which makes the fixed point unreachable (review of PR #719).
        namespace = "public"
        prefix = "sfu-"
    else:
        return idempotency_key
    digest = hashlib.sha256(f"{namespace}\x00{idempotency_key}".encode()).hexdigest()
    return f"{prefix}{digest}"


class PrivateBoardRequiresIdentity(Exception):
    """A private board was asked to take a write whose submitter is not verified.

    INVARIANT (OME-894): raised from `submit()` at the SAME read of `visibility` that decides
    per-submitter semantics, so the refusal and the persistence cannot disagree. The route used to
    take this decision from its own earlier read; a board flipped public -> private in between —
    which the seed job does on every deploy — passed the guard and then persisted an unverified
    claim under private-board rules (review of PR #719). A third read would not have closed it;
    only reading once does.
    """


def _mapping_is_ours(stored_key: str, linked: IdempotencyKey) -> bool:
    """Whether a mapping in a RESERVED namespace was written by this code.

    INVARIANT (OME-894): `sfp-` and `sfu-` are server-owned, but `main` stores client keys verbatim,
    so an old replica serving through a rollout can bind a predictable `sfp-` token to a row an
    attacker chose. With a forged `submitted_by` on a PUBLIC target row, the ownership branch then
    honoured it for the verified owner it named — returning the attacker's score, with the
    attacker's metadata, in place of the victim's own private submission. Reproduced in review of
    PR #719.

    The earlier argument that a poisoned row could only ever cause a wrong replay of a PUBLIC score
    was wrong: the row is public, but the REQUEST is private, and that is what made it reachable.
    Provenance belongs here, at the lookup, where every other privacy decision in this work lives.

    Keys outside the reserved namespaces are untouched — those are ordinary client retry tokens and
    their semantics are not this ticket's to change.
    """
    if not stored_key.startswith(RESERVED_KEY_PREFIXES):
        return True
    return linked.scheme == KEY_SCHEME


class BenchmarkVisibilityChanged(Exception):
    """A benchmark's visibility changed while a submission to it was in flight.

    INVARIANT (OME-894): visibility decides BOTH the identity rule and the dedup hashing, and a
    request reads it once. A flip landing between that read and the write leaves the whole request
    running on stale rules — so it is refused rather than completed. The caller may retry, and the
    retry sees one consistent view.

    Reading once narrowed the window that two reads opened; it did not close it. This is what
    closes it, together with the row lock the insert takes (review of PR #719).
    """


class ConcurrentScoreUpdate(Exception):
    """A deduplicated row changed identity while its provenance was being corrected.

    INVARIANT (OME-1054): the update is filtered on the row's immutable identity — id, benchmark,
    content hash and submitter — so `rowcount != 1` means the row is no longer the one the request
    resolved. Refusing beats returning an in-memory correction the database never accepted.

    WHY its own type rather than `IntegrityError`: that subclasses `OperationalError`, which the
    route maps to **503 store-unavailable**. A lost race is not the store being down, and telling a
    client to come back later when the honest answer is "retry, someone else moved this row" sends
    them to the wrong remedy. Mapped to 409, for the same reason `BenchmarkVisibilityChanged` is.
    """


class SubmitOutcome(NamedTuple):
    score: ScoreSchema
    created: bool


def _build_leaderboard_query(
    benchmark_id: str,
    top_n: int | None,
    registered_revision: str | None,
    # WHY no default: a coverage guard that can be forgotten is a guard that reopens the hole one
    # call site over. `registered_revision` beside it is required for the same reason, and the
    # store already states this rule for `_content_hash(per_submitter=...)`. `None` still means
    # "this board has no registered count", which is a real state — it just has to be said.
    registered_case_count: int | None,
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
            scores.id,
            scores.spec_id,
            scores.benchmark_revision,
            scores.score,
            scores.total_questions,
            scores.ran_with_providers,
            scores.submitted_at,
            scores.submitted_by,
            scores.authors,
            scores.verified_by_screamingface,
            scores.url4_expression,
            scores.run_cost_usd,
            row_number,
        )
        .where(scores.benchmark_id == benchmark_id)
    )
    if registered_revision is not None:
        ranked = ranked.where(scores.benchmark_revision == registered_revision)
    # INVARIANT (OME-1056): a run covering fewer cases than the benchmark defines is not
    # comparable with a complete one, and is ADVANTAGED rather than merely different — fewer
    # cases makes a perfect score easier, so a one-case run scoring 1.0 outranked a 541-case run
    # scoring 0.85. A board declaring no count filters nothing, mirroring the revision rule
    # directly above, so legacy and non-Engine boards are untouched.
    #
    # WHY `>=` and not `==`: the predicate asks "did this cover the canonical set", so a run
    # reporting more cases than registered is anomalous but not a SUBSET, and excluding it would
    # hide a complete run because the board's count went stale.
    #
    # AIDEV-NOTE: this belongs in the INNER query, beside the revision filter and NOT after the
    # window. SQL evaluates WHERE before window functions, so an excluded row never receives a
    # row_number — which is the point. Applied outside, a spec whose PARTIAL run scored higher
    # than its own full run would give the partial row `rn = 1`, and the outer `rn = 1` filter
    # would then drop that spec's complete run entirely: the invisible-submission failure this
    # change exists to prevent, reintroduced one level up.
    if registered_case_count is not None:
        ranked = ranked.where(scores.total_questions >= registered_case_count)
    ranked = ranked.as_("ranked")

    query = (
        Query.from_(ranked)
        .select(
            ranked.id,
            ranked.spec_id,
            ranked.benchmark_revision,
            ranked.score,
            ranked.total_questions,
            ranked.ran_with_providers,
            ranked.submitted_at,
            ranked.submitted_by,
            ranked.authors,
            ranked.verified_by_screamingface,
            ranked.url4_expression,
            ranked.run_cost_usd,
        )
        .where(ranked.rn == 1)
        .orderby(ranked.score, order=Order.desc)
        # INVARIANT: on a tie, first to get there ranks higher (owner, 2026-09-01). Without a
        # secondary key the order among tied rows was whatever the backend returned —
        # alphabetical by spec_id on SQLite, insertion order on Postgres — so `rank` was not
        # stable across environments and which tied row fell outside `top` moved with it.
        #
        # WHY ascending here while the rn window above uses submitted_at DESC: they answer
        # different questions. The window picks WHICH submission represents a spec, and the
        # newest wins. This orders SPECS against each other, where the earlier claim to a score
        # ranks first.
        .orderby(ranked.submitted_at, order=Order.asc)
    )
    # WHY optional: the Pareto frontier must be computed over the WHOLE ranked board. This
    # ordering is by score alone, so truncating first can hide a row that ties the boundary
    # score at a lower cost and dominates a visible one (OME-923, review of PR #778).
    return query if top_n is None else query.limit(top_n)


def _build_pareto_inputs_query(
    benchmark_id: str,
    registered_revision: str | None,
    registered_case_count: int | None,
) -> QueryBuilder:
    """Return every best-per-spec frontier input without loading display payloads."""
    scores = Score.get_table()
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
            scores.id,
            scores.spec_id,
            scores.benchmark_revision,
            scores.score,
            scores.run_cost_usd,
            row_number,
        )
        .where(scores.benchmark_id == benchmark_id)
    )
    if registered_revision is not None:
        ranked = ranked.where(scores.benchmark_revision == registered_revision)
    if registered_case_count is not None:
        ranked = ranked.where(scores.total_questions >= registered_case_count)
    ranked = ranked.as_("ranked")
    return (
        Query.from_(ranked)
        .select(
            ranked.id,
            ranked.spec_id,
            ranked.benchmark_revision,
            ranked.score,
            ranked.run_cost_usd,
        )
        .where(ranked.rn == 1)
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
        visibility: Visibility | None = None,
        case_count: int | None | _Unset = _UNSET,
    ) -> BenchmarkSchema:
        defaults: dict[str, object] = {
            "display_name": display_name,
            "description": description,
            "dataset_url": dataset_url,
            "revision": revision,
            "focus": focus,
        }
        if not isinstance(case_count, _Unset):
            # WHY a sentinel, unlike `visibility` below: direct callers may omit `case_count` to
            # leave an existing value alone, but an authoritative Engine seed passes explicit
            # None when its catalogue has no usable count. That must CLEAR a stale value; keeping
            # the old count beside a newly seeded revision would compare runs against a scope the
            # Engine no longer claims. A plain None default cannot express both states (OME-1056).
            defaults["case_count"] = case_count
        if visibility is not None:
            # WHY conditional (OME-894): seeding runs on every deploy, and an omitted visibility
            # must mean "leave it alone" rather than "reset to public" — otherwise a routine
            # deploy silently un-privates a running challenge. Stated explicitly, it still writes,
            # so a mis-seeded private board can be flipped back.
            defaults["visibility"] = visibility
        benchmark, _ = await Benchmark.update_or_create(defaults=defaults, id=benchmark_id)
        return benchmark_to_schema(benchmark)

    async def has_registered_revision(self) -> bool:
        """Has any benchmark row ever been registered with an Engine revision?

        INVARIANT: only a benchmark the Engine publishes carries a revision — the retained
        legacy demo entries have none — so a False answer means no successful Engine seed has
        ever run against this database (OME-904).
        """

        return await Benchmark.filter(revision__isnull=False).exists()

    async def set_visibility(self, benchmark_id: str, visibility: Visibility) -> bool:
        """Set an EXISTING benchmark's visibility, touching nothing else. False if absent.

        FEATURE: OME-894 — visibility is deployment-owned, so applying it must not depend on the
        Engine catalogue answering. `register_benchmark` needs a display name and would create the
        row; this updates one column of a row that already exists and never creates one, so
        benchmark existence and text stay Engine-owned (OME-904).
        """
        updated = await Benchmark.filter(id=benchmark_id).update(visibility=visibility)
        return bool(updated)

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
            if linked is not None and _mapping_is_ours(idempotency_key, linked):
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

    async def _resolve_owned(
        self,
        idempotency_key: str | None,
        content_hash: str,
        *,
        per_submitter: bool,
        submitted_by: str | None,
        identity_verified: bool,
    ) -> tuple[Score | None, Score | None]:
        # INVARIANT (OME-894): a KEY-resolved row is returned only when this caller may READ it.
        # `_scoped_idempotency_key` reserves the server-owned namespaces going forward, and `0009`
        # clears
        # what was already there, but neither can vouch for the ROLLOUT WINDOW: the migrate Job is
        # a `pre-upgrade` hook, so it completes before the new pods roll, and old replicas keep
        # storing client keys verbatim until they terminate. A row written in that window outlives
        # the migration. Checking ownership here makes the isolation hold whatever the table
        # contains, which the prefix alone cannot (review of PR #719).
        #
        # WHY a wrapper rather than parameters on `_resolve_existing`: that method is the shared
        # primitive for the pre-insert check and the IntegrityError handler, and its signature is
        # pinned by a prior test. The ownership rule belongs to the private-board caller anyway,
        # not to key resolution in general.
        existing = await self._resolve_existing(idempotency_key, content_hash)
        if existing is None:
            return None, None
        # INVARIANT: PRIVACY IS DECIDED FIRST, and a private target is refused outright — the
        # caller's claimed ownership never enters into it. An earlier version short-circuited on
        # `existing.submitted_by == submitted_by` before this test, and under `auth_mode=disabled`
        # the body's `submitted_by` is trusted, so naming the victim was enough to be handed their
        # private row through a stale public mapping (review of PR #719).
        #
        # The genuine owner loses only the KEY fast path: the per-submitter content hash below can
        # match nobody but them, so their retry still replays. That is a far smaller price than
        # trusting an unverified string, and it needs no verified-identity plumbing down here.
        #
        # The privacy read comes FIRST and decides which rule applies.
        if await self._links_to_a_private_board(existing):
            # A private target is honoured ONLY for its verified owner. An earlier revision refused
            # every private target outright, because `submitted_by` is forgeable under
            # `auth_mode=disabled` and comparing it meant nothing — but that broke `same key
            # replays the original` on every private board, which is the contract a key exists to
            # provide and the content hash cannot (it only catches an IDENTICAL retry).
            #
            # `identity_verified` is what makes the comparison sound: an unverified caller never
            # reaches it, so claiming the victim's address buys nothing. Note a private-board
            # request always arrives verified — `submit()` refuses it otherwise — so this gate
            # bites only on a PUBLIC request whose key points at a private row (review of #719).
            honour = (
                identity_verified
                and submitted_by is not None
                and existing.submitted_by == submitted_by
            )
        else:
            # A public target: the established global-key retry semantics, not this ticket's to
            # change. Honouring a forged claim costs nothing here — the row is public either way.
            honour = existing.submitted_by == submitted_by or not per_submitter
        if honour:
            return existing, None
        # AIDEV-NOTE: passing None for the key deliberately re-runs the SAME method down its
        # content-hash branch — the only other way in. On a private board that hash carries the
        # submitter, so it can match nobody but the caller; on a public one it is the ordinary
        # recipe hash and matching a public row is correct. Either way it skips the re-bind, which
        # must not move a mapping pointing at a row this caller could not read.
        #
        # Returning the refused row alongside the fallback is what lets `submit()` reclaim THIS
        # key's slot without clobbering a mapping some concurrent request bound in the meantime.
        # INVARIANT: the fallback passes the SAME privacy gate as the key path above. It used to
        # return whatever the content hash found, ungated — so a stale public hash matching a
        # now-private row handed that row over, url4 and metadata included. The key path was gated
        # and the fallback beside it was not (review of PR #719).
        fallback = await self._resolve_existing(None, content_hash)
        return await self._readable_by(
            fallback, submitted_by=submitted_by, identity_verified=identity_verified
        ), existing

    async def _readable_by(
        self,
        score: Score | None,
        *,
        submitted_by: str | None,
        identity_verified: bool,
    ) -> Score | None:
        """`score`, or None when this caller may not read it.

        One definition of "may read", so a second return path cannot quietly skip it. A public row
        is readable by anyone; a private one only by its verified owner.
        """
        if score is None or not await self._links_to_a_private_board(score):
            return score
        if identity_verified and submitted_by is not None and score.submitted_by == submitted_by:
            return score
        return None

    async def _insert_new_score(
        self,
        connection: Any,
        *,
        submission: ScoreSubmission,
        content_hash: str,
        stored_key: str | None,
        refused: Score | None,
        now_ts: datetime,
        expires_at: datetime,
    ) -> Score:
        """Write the row and bind its idempotency key, inside the caller's transaction."""
        if stored_key is not None:
            # Clear only what this request is entitled to clear: an EXPIRED mapping, or the exact
            # row `_resolve_owned` observed and refused.
            #
            # WHY not simply `filter(key=stored_key).delete()`: two requests sharing a key but
            # carrying different recipes both clear the precheck, and an unconditional delete lets
            # the second remove the mapping the first just bound — both insert, both report
            # `created`, and the key ends up on the last writer, breaking same-key-replays-original.
            # Narrowing to the observed row leaves a concurrent rebind standing, so this insert
            # trips the unique constraint and replays it through the caller's handler, which is the
            # correct outcome (review of PR #719).
            #
            # WHY expiry is still cleared unconditionally: an expired mapping is nobody's, and
            # leaving it would deny the write for the rest of its TTL.
            reclaimable = Q(expires_at__lte=now_ts)
            if refused is not None:
                reclaimable = reclaimable | Q(score_id=refused.pk)
            if stored_key.startswith(RESERVED_KEY_PREFIXES):
                # A reserved-namespace row without our scheme is a legacy or old-replica mapping.
                # The lookup refuses to honour it — and it must also be RECLAIMABLE, or it silently
                # denies this caller their own write for the rest of its TTL. That is the same
                # denial the narrowed reclaim was written to avoid, reintroduced one layer up by
                # the provenance gate; caught by two of this PR's own tests (review of PR #719).
                #
                # The slot is the caller's by construction: `sfp-` is derived from their verified
                # identity, `sfu-` from their own key. Reclaiming it takes nothing from anyone else.
                reclaimable = reclaimable | Q(scheme__isnull=True) | ~Q(scheme=KEY_SCHEME)
            await IdempotencyKey.filter(reclaimable, key=stored_key).using_db(connection).delete()

        score = await Score.create(
            using_db=connection, **_submission_to_kwargs(submission, content_hash)
        )

        if stored_key is not None:
            await IdempotencyKey.create(
                using_db=connection,
                key=stored_key,
                score=score,
                expires_at=expires_at,
                scheme=KEY_SCHEME,
            )
        return score

    async def _confirm_replayable(
        self,
        existing: Score,
        submission: ScoreSubmission,
        *,
        content_hash: str,
        per_submitter: bool,
        identity_verified: bool,
    ) -> Score:
        """Re-check both boards before a replay leaves: the request's, and the ROW's.

        INVARIANT: these are not the same benchmark. A global public key resolves by key alone, so
        it can return a row belonging to a DIFFERENT board — and revalidating only
        `submission.benchmark_id` then passed a row whose own board had just turned private.
        Reproduced: key resolves a victim row on board B, request targets board A, B flips, A is
        unchanged, and B's row goes out with its metadata (review of PR #719).

        The privacy gate in `_resolve_owned` does read the row's board, but it runs BEFORE the
        flip. This is the same gate re-applied after the final visibility decision.
        """
        await self._revalidate_visibility(submission.benchmark_id, per_submitter)
        readable = await self._readable_by(
            existing,
            submitted_by=submission.submitted_by,
            identity_verified=identity_verified,
        )
        if readable is None:
            raise BenchmarkVisibilityChanged(cast(str, getattr(existing, "benchmark_id")))

        # FEATURE: OME-1054 — recipe identity deliberately excludes mutable provenance. A
        # corrected explicit author list or metadata object therefore updates the deduped row,
        # rather than pretending success while discarding the correction.
        #
        # INVARIANT: a public content hash is global across submitters. Requiring the SAME stored
        # hash, benchmark and submitter prevents someone who copied another team's candidate (or
        # merely reused its idempotency key) from rewriting that team's credit. In production the
        # submitter is mesh-verified; disabled mode explicitly trusts this field for development.
        updates: dict[str, object] = {}
        same_candidate_owner = (
            existing.content_hash == content_hash
            and cast(str, getattr(existing, "benchmark_id")) == submission.benchmark_id
            and submission.submitted_by is not None
            and existing.submitted_by == submission.submitted_by
        )
        if same_candidate_owner:
            # None means "not specified", so an old client replay cannot erase newer provenance.
            # Empty containers remain meaningful explicit replacements where the wire contract
            # permits them (metadata may be {}, while authors=[] is rejected at validation).
            if submission.authors is not None:
                updates["authors"] = submission.authors
            if submission.metadata is not None:
                updates["metadata"] = submission.metadata

        if not updates:
            return readable

        async with in_transaction() as connection:
            # This is now a write path. Take the same benchmark lock as insertion so a visibility
            # flip cannot turn a public, unverified replay into a private-row mutation mid-write.
            await self._revalidate_visibility(
                submission.benchmark_id,
                per_submitter,
                connection=connection,
                lock=True,
            )
            updated = await (
                Score.filter(
                    id=existing.id,
                    benchmark_id=submission.benchmark_id,
                    content_hash=content_hash,
                    submitted_by=submission.submitted_by,
                )
                .using_db(connection)
                .update(**updates)
            )
            if updated != 1:
                # The row's immutable identity changing would violate the model contract. Refuse
                # instead of returning an in-memory correction the database did not accept.
                raise ConcurrentScoreUpdate("deduplicated score changed while updating metadata")

        for name, value in updates.items():
            setattr(readable, name, value)
        return readable

    def visibility_query(
        self,
        benchmark_id: str,
        *,
        connection: Any = None,
        lock: bool = False,
    ) -> QuerySet[Benchmark]:
        """The query `_revalidate_visibility` runs, exposed so a test can render its SQL.

        INVARIANT: a MODEL projection, never `values_list()`. `select_for_update()` sets lock state
        on the QuerySet and `values_list()` builds a fresh `ValuesListQuery` without copying it, so
        projecting silently dropped `FOR UPDATE` and the lock this path claims was never taken —
        while the PR description and a review reply both said it was. `.only(...).first()` keeps it.

        WHY this is a method rather than inline: the lock cannot be observed on SQLite, so the only
        available check is rendering the SQL on the asyncpg dialect — and a test that builds its own
        query proves nothing about this one. `test_the_persist_path_really_locks_the_row` renders
        exactly what runs here (review of PR #719).
        """
        rows = Benchmark.filter(id=benchmark_id)
        if connection is not None:
            rows = rows.using_db(connection)
        if lock:
            rows = rows.select_for_update()
        return rows.only("visibility")

    async def _revalidate_visibility(
        self,
        benchmark_id: str,
        per_submitter: bool,
        *,
        connection: Any = None,
        lock: bool = False,
    ) -> None:
        """Refuse if `visibility` no longer matches what this request decided against."""
        row = await self.visibility_query(benchmark_id, connection=connection, lock=lock).first()
        # A benchmark deleted mid-flight reads as not-private, which is the same conclusion the
        # RESTRICT foreign key would force a moment later.
        still_private = row is not None and row.visibility == "private"
        if still_private != per_submitter:
            raise BenchmarkVisibilityChanged(benchmark_id)

    async def _links_to_a_private_board(self, score: Score) -> bool:
        # `benchmark_id` is the foreign key's shadow column and not a declared attribute, so it is
        # read the way every other call site in this module reads it.
        benchmark = await Benchmark.get_or_none(id=cast(str, getattr(score, "benchmark_id")))
        # Fails closed: a row whose board cannot be established is treated as private rather than
        # served. Unreachable behind the RESTRICT foreign key, kept so it cannot become reachable.
        return benchmark is None or benchmark.visibility == "private"

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
                    scheme=KEY_SCHEME,
                )
        except IntegrityError:
            pass

    async def submit(
        self,
        submission: ScoreSubmission,
        idempotency_key: str | None = None,
        *,
        identity_verified: bool = False,
    ) -> SubmitOutcome:
        """Persist a submission, or replay the one an earlier identical request created.

        `identity_verified` says whether the caller's `submitted_by` came from a trusted source
        rather than the request body. It defaults to FALSE deliberately: a call site that forgets
        it makes private boards REFUSE writes, which is loud and safe, where the opposite default
        would silently reopen the forged-write hole this argument exists to close (owner decision,
        2026-08-27). Public boards are unaffected either way.
        """
        now_ts = datetime.now(UTC)
        # INVARIANT: ONE read of `visibility`, and every decision that depends on it is taken here
        # — both the identity rule and per-submitter dedup. The route used to read it separately
        # for the identity rule, which raced the seed job (review of PR #719).
        benchmark = await Benchmark.get_or_none(id=submission.benchmark_id)
        per_submitter = benchmark is not None and benchmark.visibility == "private"
        if per_submitter and not identity_verified:
            raise PrivateBoardRequiresIdentity(submission.benchmark_id)
        content_hash = _content_hash(submission, per_submitter=per_submitter)
        # INVARIANT (OME-894): on a private board the idempotency key is scoped to its submitter.
        # `_resolve_existing` consults the key BEFORE the content hash, and the key is stored
        # globally, so without this a second participant reusing a key — guessed, observed, or
        # simply a client that reuses a constant — received the FIRST participant's stored row,
        # url4 and metadata included, and created nothing of their own. The per-submitter content
        # hash cannot help, because the key short-circuits ahead of it.
        # Public boards keep the global key: it is a client's retry token there, and its existing
        # semantics are not this ticket's to change.
        stored_key = _scoped_idempotency_key(
            idempotency_key, submission.submitted_by, per_submitter=per_submitter
        )

        existing, refused = await self._resolve_owned(
            stored_key,
            content_hash,
            per_submitter=per_submitter,
            submitted_by=submission.submitted_by,
            identity_verified=identity_verified,
        )
        if existing is not None:
            # Detection, not prevention: nothing is being written here, but the row was chosen
            # under a view of `visibility` that may since have changed, so returning it would be
            # answering a question we no longer know the rules for.
            confirmed = await self._confirm_replayable(
                existing,
                submission,
                content_hash=content_hash,
                per_submitter=per_submitter,
                identity_verified=identity_verified,
            )
            return SubmitOutcome(score=_score_to_schema(confirmed), created=False)

        expires_at = now_ts + IDEMPOTENCY_TTL
        try:
            async with in_transaction() as connection:
                # Prevention, on PostgreSQL: the lock is held until this transaction commits, so a
                # concurrent flip must wait for the insert rather than racing it. SQLite does not
                # implement the lock, so the suite exercises the revalidation behaviourally and
                # `test_the_persist_path_really_locks_the_row` renders THIS query's SQL on the
                # asyncpg dialect to prove `FOR UPDATE` is actually emitted. That check exists
                # because it once was not, unnoticed (review of PR #719).
                await self._revalidate_visibility(
                    submission.benchmark_id, per_submitter, connection=connection, lock=True
                )
                score = await self._insert_new_score(
                    connection,
                    submission=submission,
                    content_hash=content_hash,
                    stored_key=stored_key,
                    refused=refused,
                    now_ts=now_ts,
                    expires_at=expires_at,
                )

            return SubmitOutcome(score=_score_to_schema(score), created=True)
        except IntegrityError:
            # A concurrent request may have won the race on either constraint.
            # INVARIANT: the SCOPED key, matching the pre-insert lookup above. Using the raw key
            # here re-opened the cross-participant leak this ticket closed, for exactly the
            # concurrent case this branch exists to handle (found in review of PR #719).
            existing, _ = await self._resolve_owned(
                stored_key,
                content_hash,
                per_submitter=per_submitter,
                submitted_by=submission.submitted_by,
                identity_verified=identity_verified,
            )
            # Revalidated before BOTH exits, not just the replay. This branch is reached BECAUSE
            # something changed concurrently, so it is the least safe place to trust a read taken
            # before the failed insert — and the persist-path check that already passed cannot
            # speak for the time spent failing.
            #
            # WHY it must also guard the `raise`: `IntegrityError` SUBCLASSES `OperationalError`,
            # so re-raising it is caught by the route's store-unavailable handler and answered
            # `503 score store unavailable`. Nothing is unavailable — the board changed — and a
            # flip is the likeliest reason nothing resolved here, since the privacy gate stops the
            # winner's row being readable once the board is private (review of PR #719).
            if existing is not None:
                confirmed = await self._confirm_replayable(
                    existing,
                    submission,
                    content_hash=content_hash,
                    per_submitter=per_submitter,
                    identity_verified=identity_verified,
                )
                return SubmitOutcome(score=_score_to_schema(confirmed), created=False)
            await self._revalidate_visibility(submission.benchmark_id, per_submitter)
            raise

    async def get_by_idempotency_key(self, key: str) -> ScoreSchema | None:
        """Return the score a live public idempotency key points at, if any.

        INVARIANT (OME-894): this takes NO caller identity, so it cannot scope a read to an owner —
        and therefore it must never serve a private board's row. A caller that needs private access
        has an identity and belongs on `get_score` or `list_owned_entries`, both of which compare
        it. Left unguarded this was a public store method returning any score to whoever held its
        key, bypassing every check the rest of this work added; it has no production caller, which
        is the only reason that was not already a leak (self-review of PR #719).
        """
        now_ts = datetime.now(UTC)
        stored_key = _scoped_idempotency_key(key, None, per_submitter=False)
        linked = await IdempotencyKey.get_or_none(
            key=stored_key,
            expires_at__gt=now_ts,
        ).prefetch_related("score")
        if linked is None or await self._links_to_a_private_board(linked.score):
            return None
        return _score_to_schema(linked.score)

    async def cleanup_expired_idempotency_keys(self, now: datetime) -> int:
        return await IdempotencyKey.filter(expires_at__lte=now).delete()

    async def leaderboard(
        self,
        benchmark_id: str,
        top_n: int | None = 50,
        *,
        registered_revision: str | None | _Unset = _UNSET,
        registered_case_count: int | None | _Unset = _UNSET,
    ) -> list[LeaderboardStoreEntry]:
        """The ranked display board. ``top_n=None`` remains available to internal callers."""
        conn = Tortoise.get_connection("default")
        # The board is defined by the revision its benchmark is registered at; entries measured
        # against anything else are not comparable to it and do not rank (OME-775).
        # INVARIANT: when the caller supplies the revision, it is NOT read again. The route
        # decides whether to compute a frontier at all from `Benchmark.revision`, and this query
        # filters on it — two independent SELECTs of one row meant a re-registration landing
        # between them could open the gate on one value while the query filtered on another,
        # computing a frontier over mixed revisions and reopening the cohort-of-one gap D12
        # closes. One read now decides both (found in review, 2026-09-01).
        if isinstance(registered_revision, _Unset) or isinstance(registered_case_count, _Unset):
            benchmark = await Benchmark.get_or_none(id=benchmark_id)
            if isinstance(registered_revision, _Unset):
                registered_revision = benchmark.revision if benchmark else None
            if isinstance(registered_case_count, _Unset):
                registered_case_count = benchmark.case_count if benchmark else None
        assert not isinstance(registered_revision, _Unset)
        assert not isinstance(registered_case_count, _Unset)
        result = await execute_pypika(
            _build_leaderboard_query(
                benchmark_id,
                top_n,
                registered_revision,
                registered_case_count,
            ),
            using_db=conn,
        )
        rows = _to_python_rows(result.rows)
        for row in rows:
            row["source_id"] = str(row.pop("id"))
        return [LeaderboardStoreEntry(**row) for row in rows]

    async def leaderboard_pareto_inputs(
        self,
        benchmark_id: str,
        *,
        registered_revision: str | None,
        registered_case_count: int | None,
    ) -> list[ParetoEntry]:
        """The unbounded, minimal projection needed for a public Pareto frontier."""
        conn = Tortoise.get_connection("default")
        result = await execute_pypika(
            _build_pareto_inputs_query(
                benchmark_id,
                registered_revision,
                registered_case_count,
            ),
            using_db=conn,
        )
        rows = _to_python_rows(result.rows)
        return [
            ParetoEntry(
                source_id=str(row["id"]),
                spec_id=cast(str, row["spec_id"]),
                benchmark_revision=cast(str | None, row["benchmark_revision"]),
                score=cast(float, row["score"]),
                run_cost_usd=cast(Decimal | None, row["run_cost_usd"]),
            )
            for row in rows
        ]

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

    async def list_owned_entries(self, benchmark_id: str, owner: str) -> list[LeaderboardEntry]:
        """Every submission `owner` made to `benchmark_id`, newest first, nothing collapsed.

        FEATURE: OME-894 — what a participant sees of their own work on a private board.

        WHY not `leaderboard(owner=...)`: that query is the RANKING, so it collapses to
        best-per-spec (`rn == 1`) and is bounded by the board's `top`. Routing a private view
        through it silently dropped a participant's earlier submission to the same spec, which is
        the invisible-submission failure this ticket exists to avoid — reintroduced one level
        down. Nothing here is ranked, so nothing is collapsed and nothing is capped: these are the
        caller's own rows and the caller is authenticated.
        """
        rows = (
            await Score.filter(benchmark_id=benchmark_id, submitted_by=owner)
            .order_by("-submitted_at")
            .all()
        )
        return [
            LeaderboardEntry(
                spec_id=row.spec_id,
                benchmark_revision=row.benchmark_revision,
                score=row.score,
                total_questions=row.total_questions,
                ran_with_providers=row.ran_with_providers,
                submitted_at=row.submitted_at,
                submitted_by=row.submitted_by,
                # A private board is currently the ONLY surface where a participant sees a credit
                # line at all (OME-894 D2 scopes reads to the submitter, and `entries` is empty
                # for everyone), so omitting this dropped the feature exactly where it matters and
                # degraded silently rather than raising, because the DTO field has a default.
                authors=_resolved_authors(row.authors, row.submitted_by),
                verified_by_screamingface=row.verified_by_screamingface,
                url4_expression=row.url4_expression,
                run_cost_usd=row.run_cost_usd,
            )
            for row in rows
        ]

    async def list_all_for_benchmark(self, benchmark_id: str) -> list[ScoreSchema]:
        """Every Score row for a benchmark, chronologically — unlike `leaderboard()`
        (best-per-spec only), this is what OME-323's frontier trend needs: the full
        submission history across all specs, deliberately benchmark-wide (spec §6's
        frontier-scope resolution).
        """
        rows = await Score.filter(benchmark_id=benchmark_id).order_by("submitted_at")
        return [_score_to_schema(score) for score in rows]

    async def mark_verified(self, score_id: UUID | str) -> None:
        await Score.filter(id=score_id).update(verified_by_screamingface=True)
