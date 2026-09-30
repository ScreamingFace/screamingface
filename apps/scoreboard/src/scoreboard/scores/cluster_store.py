"""ClusterStore: the Tortoise adapter and transaction owner of the clustered submit.

FEATURE: OME-1307 (E14) — `POST /v1/scores` with clustering on (prd/submit-and-cluster.md). One
call decides which head a run belongs to, inserts the head when there is none, and always inserts
the run as a `ReportedResult`.

INVARIANT (I-S2, I-R3): a head row is never updated by a later run, and a result row is never
updated after insert. The one head write besides the insert is the legacy link (SC-D3), which
fills a NULL `system_revision_id`.

INVARIANT (OME-894): `IntegrityError` subclasses `OperationalError`, which the route maps to 503.
It never leaves `submit`; a lost race becomes a retry, an idempotent answer, or a 409.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from tortoise import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from scoreboard.core.paging import Cursor
from scoreboard.core.registry import (
    InvalidUrl4,
    RegistryService,
    RevisionRef,
    SystemRef,
    Url4TooLarge,
)
from scoreboard.core.replay_access import replay_access
from scoreboard.core.submissions.clustering import publication_needed
from scoreboard.core.submissions.receipts import ReceiptClaims

from .cluster_rules import (
    ResultFields,
    cluster_revision,
    clustered_notice,
    named_notice,
    result_fields,
)
from .cluster_types import (
    CacheVersionAlreadyBound,
    ClusterOutcome,
    InvalidReplayClaim,
    Kind,
    ReplayTarget,
    _Call,
    _column,
    _Placement,
    _revision_filter,
    load_result_chain,
)
from .models import Benchmark, CacheVersionPublication, IdempotencyKey, ReportedResult, Score
from .schemas import ReplayClaim, ScoreSubmission, SubmitNotice
from .store import (
    ConcurrentScoreUpdate,
    PrivateBoardRequiresIdentity,
    ScoreStore,
    _content_hash,
    _mapping_is_ours,
    _scoped_idempotency_key,
    _submission_to_kwargs,
)

# WHY: the import paths of the routes, SB-grants and SB-publish stay `scores.cluster_store`.
__all__ = [
    "CacheVersionAlreadyBound",
    "ClusterOutcome",
    "ClusterStore",
    "InvalidReplayClaim",
    "ReplayTarget",
]

_ATTEMPTS = 2


class ClusterStore:
    def __init__(self, score_store: ScoreStore, registry: RegistryService) -> None:
        self._score_store = score_store
        self._registry = registry

    async def submit(
        self,
        submission: ScoreSubmission,
        *,
        idempotency_key: str | None,
        identity_verified: bool,
        claims: ReceiptClaims | None,
    ) -> ClusterOutcome:
        """Cluster one run.

        INVARIANT: ONE read of `visibility` decides both the identity rule and the per-submitter
        scoping, exactly as `ScoreStore.submit` does. The write transaction then re-proves it
        under the benchmark row lock (`lock_visibility`).
        """
        benchmark = await Benchmark.get_or_none(id=submission.benchmark_id)
        per_submitter = benchmark is not None and benchmark.visibility == "private"
        if per_submitter and not identity_verified:
            raise PrivateBoardRequiresIdentity(submission.benchmark_id)
        call = _Call(
            submission=submission,
            per_submitter=per_submitter,
            identity_verified=identity_verified,
            stored_key=_scoped_idempotency_key(
                idempotency_key, submission.submitted_by, per_submitter=per_submitter
            ),
            claims=claims,
        )
        taken = await self._result_by_run_id(call.stored_key)
        hit = await self._idempotent_hit(call, taken)
        if hit is not None:
            return hit
        await self._check_bindings(call)
        # WHY None when the key is taken: the key is bound to a row this caller may not read. The
        # unique `run_id` would reject the insert, and the retry branch must never hand that row
        # back (OME-894). The run is stored as a NEW result with no run id.
        run_id = None if taken is not None else call.stored_key
        return await self._write_with_retry(call, run_id)

    async def results_page(
        self, score_id: UUID, *, after: Cursor | None, limit: int
    ) -> list[ReportedResult]:
        """Up to `limit + 1` results of a head, newest first: `(submitted_at, id)` descending.

        The extra row tells the caller that a next page exists.
        """
        rows = ReportedResult.filter(head_id=score_id)
        if after is not None:
            rows = rows.filter(
                Q(submitted_at__lt=after.submitted_at)
                | Q(submitted_at=after.submitted_at, id__lt=after.id)
            )
        return await rows.order_by("-submitted_at", "-id").limit(limit + 1)

    async def publication_states(self, result_ids: Sequence[UUID]) -> dict[str, str]:
        rows = await CacheVersionPublication.filter(result_id__in=list(result_ids)).values_list(
            "result_id", "state"
        )
        return {str(result_id): state for result_id, state in rows}

    async def load_replay_target(self, result_id: UUID) -> ReplayTarget | None:
        chain = await load_result_chain(result_id)
        if chain is None:
            return None
        result, head, board = chain
        states = await self.publication_states([result.id])
        return ReplayTarget(result, head, board, states.get(str(result.id)))

    # -- idempotency (SC-D1) -------------------------------------------------------------------

    async def _result_by_run_id(self, stored_key: str | None) -> ReportedResult | None:
        if stored_key is None:
            return None
        return await ReportedResult.get_or_none(run_id=stored_key)

    async def _idempotent_hit(
        self, call: _Call, taken: ReportedResult | None
    ) -> ClusterOutcome | None:
        """The answer of an earlier run with this key, when this caller may read its head."""
        if call.stored_key is None:
            return None
        if taken is not None:
            head = await Score.get_or_none(id=_column(taken, "head_id"))
            return await self._replay_outcome(call, head, taken)
        head = await self._legacy_head(call.stored_key)
        original = None
        if head is not None:
            original = await ReportedResult.get_or_none(head_id=head.id, is_original=True)
        return await self._replay_outcome(call, head, original)

    async def _legacy_head(self, stored_key: str) -> Score | None:
        # WHY: a mapping written by the legacy path has no `run_id` on any result (SC-1 stays true
        # after the flag flips). Only a live mapping that this code wrote is honoured.
        linked = (
            await IdempotencyKey.filter(key=stored_key, expires_at__gt=datetime.now(UTC))
            .prefetch_related("score")
            .first()
        )
        if linked is None or not _mapping_is_ours(stored_key, linked):
            return None
        return linked.score

    async def _replay_outcome(
        self, call: _Call, head: Score | None, result: ReportedResult | None
    ) -> ClusterOutcome | None:
        readable = await self._score_store.readable_by(
            head,
            submitted_by=call.submission.submitted_by,
            identity_verified=call.identity_verified,
        )
        if readable is None:
            return None
        return await self._outcome(readable, result, "replay_idempotent", [])

    # -- bindings, before any write (SC-E4, rule R) --------------------------------------------

    async def _check_bindings(self, call: _Call) -> None:
        if call.claims is not None and await ReportedResult.exists(
            cache_version_id=call.claims.vid
        ):
            raise CacheVersionAlreadyBound
        replay = call.submission.replay
        if replay is not None:
            await self._check_replay(call, replay)

    async def _check_replay(self, call: _Call, replay: ReplayClaim) -> None:
        """Rule R (C4 trust rule): the claim names a result this caller may replay."""
        target = await self.load_replay_target(replay.result_id)
        # WHY the version is compared for the replayed result only: the baseline is a result of its
        # own, so the claimed version is not compared with it.
        if (
            target is None
            or target.result.cache_version_id != replay.cache_version_id
            or not self._replay_allowed(call, target)
        ):
            raise InvalidReplayClaim
        # INVARIANT (X-SEC-1): the baseline is held to the same board and access rules as the
        # replayed result. The FK is NO ACTION (D8), so a baseline that names a result this caller
        # may not see would block its owner's delete or purge, and the 201/422 split would tell the
        # caller that the id exists.
        baseline = replay.pinned_baseline_result_id
        if baseline is not None:
            named = await self.load_replay_target(baseline)
            if named is None or not self._replay_allowed(call, named):
                raise InvalidReplayClaim

    @staticmethod
    def _replay_allowed(call: _Call, target: ReplayTarget) -> bool:
        # INVARIANT: the claim names a result of THIS board (C4 trust rule). A grant across
        # boards is refused too (C6/RP-E4), so no grant could have produced such a claim.
        if target.benchmark.id != call.submission.benchmark_id:
            return False
        access = replay_access(
            board_visibility=target.benchmark.visibility,
            redistributable=target.benchmark.redistributable,
            reporter=target.result.reporter,
            publication_state=target.publication_state,
            caller=call.submission.submitted_by,
            identity_verified=call.identity_verified,
        )
        return access == "allow"

    # -- the write (SC-D2, SR-D2) --------------------------------------------------------------

    async def _write_with_retry(self, call: _Call, run_id: str | None) -> ClusterOutcome:
        for _ in range(_ATTEMPTS):
            try:
                return await self._write(call, run_id)
            except IntegrityError:
                # WHY one retry: the loser of a race finds the winner's head or system on the
                # second pass and appends its run to it.
                continue
        return await self._lost_race(call)

    async def _lost_race(self, call: _Call) -> ClusterOutcome:
        hit = await self._idempotent_hit(call, await self._result_by_run_id(call.stored_key))
        if hit is not None:
            return hit
        if call.claims is not None and await ReportedResult.exists(
            cache_version_id=call.claims.vid
        ):
            raise CacheVersionAlreadyBound
        raise ConcurrentScoreUpdate(call.submission.benchmark_id)

    async def _write(self, call: _Call, run_id: str | None) -> ClusterOutcome:
        submission = call.submission
        async with in_transaction() as conn:
            # INVARIANT: locked and re-proved BEFORE the registry or a head is read, so the
            # `"public"` handed to `resolve_for_submit` is the state this transaction sees.
            await self._score_store.lock_visibility(
                submission.benchmark_id, call.per_submitter, connection=conn
            )
            placement = await self._place(call, conn)
            head, kind, notices = await self._head_for(call, placement, conn)
            result = await self._insert_result(call, head, kind, run_id, conn)
            return await self._outcome(head, result, kind, notices, conn)

    async def _place(self, call: _Call, conn: BaseDBAsyncClient) -> _Placement:
        if call.per_submitter:
            return await self._place_private(call, conn)
        if call.identity_verified:
            return await self._place_named(call, conn)
        return await self._place_unnamed(call, conn)

    async def _place_named(self, call: _Call, conn: BaseDBAsyncClient) -> _Placement:
        """Public board, verified identity (D5, production): the registry names the system."""
        submission = call.submission
        resolution = await self._registry.resolve_for_submit(
            submission.url4_expression,
            submission.spec_id,
            submission.revision_of,
            cast(str, submission.submitted_by),
            "public",
            connection=conn,
        )
        system, revision = (
            cast(SystemRef, resolution.system),
            cast(RevisionRef, resolution.revision),
        )
        named = submission.model_copy(update={"spec_id": system.name})
        head = await self._find_public_head(
            benchmark_id=submission.benchmark_id,
            benchmark_revision=cluster_revision(submission),
            system_revision_id=revision.id,
            connection=conn,
        )
        if head is None:
            head = await self._link_legacy_head(named, revision.id, conn)
        notices = [] if resolution.notice is None else [named_notice(resolution.notice)]
        return _Placement(head, named, revision.id, None, notices)

    async def _place_unnamed(self, call: _Call, conn: BaseDBAsyncClient) -> _Placement:
        """Public board, identity NOT verified (the `disabled` dev/local fallback, D5).

        INVARIANT: no registry call. An unverified name must never own a system (`System.owner` is
        NOT NULL and names are global, SR-D2). Today's dedup key, the content hash, still applies.
        `revision_of` is ignored.
        """
        submission = call.submission
        head = (
            await Score.filter(
                content_hash=_content_hash(submission, per_submitter=False),
                benchmark_id=submission.benchmark_id,
            )
            .using_db(conn)
            .first()
        )
        return _Placement(head, submission, None, None, [])

    async def _place_private(self, call: _Call, conn: BaseDBAsyncClient) -> _Placement:
        """Private board: cluster per submitter by a fingerprint the server recomputes.

        INVARIANT: recomputed from `url4_expression`, never read from `metadata.system_fingerprint`
        (a client can send any metadata, SR-D1). WHY no registry (I-N4, SR-D8): a private board
        never touches the registry, so `revision_of` names nothing here and is ignored.
        """
        submission = call.submission
        fingerprint = self._registry.identify(submission.url4_expression).fingerprint
        rows = Score.filter(
            benchmark_id=submission.benchmark_id,
            submitted_by=submission.submitted_by,
            system_revision_id__isnull=True,
        )
        candidates = (
            await _revision_filter(rows, cluster_revision(submission))
            .using_db(conn)
            .order_by("submitted_at", "id")
        )
        head = next(
            (
                row
                for row in candidates
                if self._same_system(row, submission.url4_expression, fingerprint)
            ),
            None,
        )
        metadata = {**(submission.metadata or {}), "system_fingerprint": fingerprint}
        return _Placement(head, submission, None, metadata, [])

    def _same_system(self, row: Score, expression: str, fingerprint: str) -> bool:
        # WHY the shortcut: the same expression has the same fingerprint, and identify is costly
        # under the board lock.
        if row.url4_expression == expression:
            return True
        try:
            return self._registry.identify(row.url4_expression).fingerprint == fingerprint
        except (InvalidUrl4, Url4TooLarge):
            return False

    async def _find_public_head(
        self,
        *,
        benchmark_id: str,
        benchmark_revision: str | None,
        system_revision_id: UUID,
        connection: BaseDBAsyncClient,
    ) -> Score | None:
        rows = Score.filter(benchmark_id=benchmark_id, system_revision_id=system_revision_id)
        return await _revision_filter(rows, benchmark_revision).using_db(connection).first()

    async def _link_legacy_head(
        self, named: ScoreSubmission, revision_id: UUID, conn: BaseDBAsyncClient
    ) -> Score | None:
        """SC-D3: a legacy head of the same recipe becomes this system's head, once."""
        content_hash = _content_hash(named, per_submitter=False)
        linked = (
            await Score.filter(
                content_hash=content_hash,
                benchmark_id=named.benchmark_id,
                system_revision_id__isnull=True,
            )
            .using_db(conn)
            .update(system_revision_id=revision_id)
        )
        if linked != 1:
            return None
        return await Score.filter(content_hash=content_hash).using_db(conn).first()

    async def _head_for(
        self, call: _Call, placement: _Placement, conn: BaseDBAsyncClient
    ) -> tuple[Score, Kind, list[SubmitNotice]]:
        if placement.head is not None:
            notices = [*placement.notices, clustered_notice(placement.head.id)]
            return placement.head, "reported_result", notices
        submission = placement.submission
        kwargs = _submission_to_kwargs(
            submission, _content_hash(submission, per_submitter=call.per_submitter)
        )
        if placement.metadata is not None:
            kwargs["metadata"] = placement.metadata
        head = await Score.create(
            using_db=conn, system_revision_id=placement.system_revision_id, **kwargs
        )
        return head, "new_head", placement.notices

    async def _insert_result(
        self,
        call: _Call,
        head: Score,
        kind: Kind,
        run_id: str | None,
        conn: BaseDBAsyncClient,
    ) -> ReportedResult:
        fields: ResultFields = result_fields(call.submission, run_id=run_id, claims=call.claims)
        columns = asdict(fields)
        receipt, replay = columns.pop("receipt"), columns.pop("replay")
        result = await ReportedResult.create(
            using_db=conn,
            head_id=head.id,
            is_original=kind == "new_head",
            **columns,
            **receipt,
            **replay,
        )
        if publication_needed(receipt):
            # SC-D8: every result that carries a cache version starts `private`.
            await CacheVersionPublication.create(
                using_db=conn, result_id=result.id, state="private"
            )
        return result

    async def _outcome(
        self,
        head: Score,
        result: ReportedResult | None,
        kind: Kind,
        notices: list[SubmitNotice],
        conn: BaseDBAsyncClient | None = None,
    ) -> ClusterOutcome:
        count = await ReportedResult.filter(head_id=head.id).using_db(conn).count()
        publication = (
            None
            if result is None
            else await CacheVersionPublication.filter(result_id=result.id).using_db(conn).first()
        )
        state = None if publication is None else publication.state
        return ClusterOutcome(head, result, state, count, notices, kind)
