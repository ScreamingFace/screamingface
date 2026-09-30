"""Every exit of a visibility-dependent function is guarded, or listed here with a reason.

FEATURE: OME-894 — `visibility` is the only authorisation input in this app that another process
can change while a request is in flight, so a decision taken from it goes stale. Four review rounds
found the same defect at four layers: the write path, then every read path, then a response body
carrying a stale copy, then one exit of one branch. Each time the named instance was fixed and the
CLASS was not.

This is the class, asserted. The analysis walks every function that reads `visibility` or takes a
decision derived from it, and for each `return`/`raise` asks whether a revalidation must have run
first. Exits that legitimately need no guard are enumerated below with the reason. A NEW unguarded
exit fails this test, and the author has to either guard it or argue it onto the list.

AIDEV-NOTE: keyed on (function, exit kind, count), never line numbers — those move with every edit
and a guard nobody can keep green gets deleted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src/scoreboard"
# Calls that constitute "the decision was re-checked". `_confirm_replayable` belongs here because
# it revalidates the request's board AND re-gates the returned row — a replay guarded by it is
# guarded more thoroughly than one guarded by `_revalidate_visibility` alone.
REVAL = ("_revalidate_visibility", "turned_private", "_confirm_replayable")

pytestmark = pytest.mark.anyio

# Each entry: (function, exit kind) -> how many exits legitimately need no revalidation.
#
# RESTRICTIVE — returns the private shape or refuses. Going stale can only mean the board OPENED,
# so the caller receives less than it could have, never more.
#   _private_leaderboard / get_leaderboard   the private response itself
#   get_spec_history / get_frontier          the 404s a private board answers with
#   get_score                                404 for a private row, 404 unknown id, 503 store down
#   submit                                   PrivateBoardRequiresIdentity
#
# PURE — no request, no I/O, nothing to go stale between.
#   benchmark_to_schema, _content_hash, _scoped_idempotency_key
#
# WRITER — visibility is an INPUT here, not a decision read back.
#   register_benchmark, set_visibility
#
# CALLER-GUARANTEED — a helper whose caller revalidates before ITS exits.
#   _resolve_owned (submit() guards every path out)
#   metadata_store.metadata_history  its one Return hands the page and the board id to the route,
#                                    which re-checks the decision before a public answer; its two
#                                    Raises are the RESTRICTIVE 404s
#
# READS IT FRESH — consults `visibility` at call time, so it cannot hold a stale value.
#   _readable_by, _links_to_a_private_board
#   metadata_store.update_metadata   reads `visibility` INSIDE the write's own transaction, after
#                                    the row lock, so the decision and the write see one state
#
# CONFIG-DRIVEN — reads visibility from deployment configuration, immutable within a seed pass.
#   the seed.py functions
#
# OPERATOR TOOL — a one-shot CLI, not a request path. `check_rollback_safety` REPORTS what
# `visibility` says so a human can decide; there is no later action for a stale read to
# authorise, and a board flipped a second after it runs is caught by the next run. Revalidating
# would only narrow a window that has nothing on the other side of it.
#   check_rollback_safety.private_boards / format_verdict / running_version
#   backfill_systems._public_unlinked_heads — reads which heads are public so the one-shot command
#   never touches a private head; a board flipped a second later is caught by the next run.
#
# REGISTRY INPUT — visibility arrives as an argument (`board_visibility`) that the caller read; the
# registry takes no decision from a stored copy. The caller (SB-submit) owns the revalidation of the
# board; this function only receives the value it was given.
#   service.py::resolve_for_submit (core/registry)
#
# QUERY BUILDER — returns an unevaluated locking query, not visibility data or a decision. Its
# caller awaits the query and refuses immediately unless the freshly locked row is private; the
# PostgreSQL SQL assertion below separately proves that this exact query retains `FOR UPDATE`.
#   purge_private_benchmark._purge_visibility_query
#
# SUBMIT PATH (E14, SB-submit) — the clustered submit owns the revalidation that REGISTRY INPUT
# above hands to its caller. Three layers:
#   (1) `ClusterStore._write` re-proves the decision under the benchmark row lock
#       (`ScoreStore.lock_visibility`, that is `_revalidate_visibility(lock=True)` under a wrapper)
#       BEFORE the registry or any head is read;
#   (2) the route (`_cluster` in routes/scores.py, and `list_results` in routes/results.py) calls
#       `turned_private` before any public answer leaves; this guard recognises both because that
#       call comes first;
#   (3) the pure rules take only values.
#   cluster_store.py::submit Raise       RESTRICTIVE — PrivateBoardRequiresIdentity refuses a
#                                        private write with no verified identity, as
#                                        store.py::submit does
#   cluster_store.py::submit Return x2   CALLER-GUARANTEED — an idempotent hit (gated by
#                                        `readable_by`, which reads visibility fresh) and the write
#                                        result; the route re-checks with `turned_private` before
#                                        the answer leaves
#   cluster_store.py::_write Return      GUARDED BY LOCK — returns after `lock_visibility`; this
#                                        guard only knows the private name it wraps
#   cluster_store.py::_replay_allowed    PURE — a decision over values the caller loaded (rule R).
#                                        It feeds only the stored provenance columns; no answer
#                                        carries the replayed result's data
#   replay_access.py::is_owner / replay_access   PURE — no request, no I/O (core/replay_access.py).
#                                        `board_visibility` is an INPUT the caller read; SB-grants
#                                        owns the revalidation of its own use
#   results.py::_readable_head Raise x3  RESTRICTIVE — the 404s of a missing or not-yours head and
#                                        the 503 of a store that is down
#   results.py::_readable_head Return    CALLER-GUARANTEED — `list_results` re-checks with
#                                        `turned_private` before a public answer
#   store.py::readable_by                READS IT FRESH — delegates to `_readable_by`
#
# REPLAY GRANTS (E14, SB-grants) — recorded in docs/work/2026-09-29-e14-sb-grants.md.
# `POST /v1/replay-grants` decides from ONE read of the board row (`ReplayPinResolver.resolve`);
# the route re-checks with `turned_private` before it signs a grant for a non-owner.
#   replay_resolver.py::resolve Raise x1    RESTRICTIVE — an unknown board answers PinNotFound, the
#                                           same 404 as an unknown pin
#   replay_resolver.py::resolve Return x2   CALLER-GUARANTEED — `issue_replay_grant` re-checks with
#                                           `turned_private` before it signs for a non-owner
#                                           (`ResolvedReplay.via_owner` is False)
#   replay_resolver.py::_access Return      PURE — a decision over values the caller loaded
#                                           (`benchmark`, the row's `reporter`, the state)
#
# PUBLISH PATH (E14, SB-publish) — `POST /v1/results/{id}/publish` reads the board visibility to
# decide who may publish. The decision is re-checked before it acts: `publish_result` calls
# `turned_private` after the checks and before `request_publish`, so the state changes only for a
# board that is still public. That function has no row (the guard recognises the call).
#   eligibility.py::publish_refusal Return  PURE — `next(...)` over values the caller read; an
#                                           unknown visibility is refused (fail closed)
#   publish.py::_load Return x3             CALLER-GUARANTEED — hands the loaded rows to
#                                           `publish_result`, which re-checks with `turned_private`
#                                           before `request_publish`
#   publish.py::_check_owner Return x1 / Raise x2
#                                           RESTRICTIVE — the 404 of a private result of another
#                                           caller and the 403 of a non-owner; going stale can only
#                                           mean the board OPENED, so the caller learns less
#   publish.py::_check_publishable Return x1 / Raise x3
#                                           RESTRICTIVE — the 409 refusals; a stale read can only
#                                           refuse a result whose board has since opened
EXPECTED_UNGUARDED: dict[tuple[str, str], int] = {
    ("leaderboard.py::_private_leaderboard", "Return"): 1,
    ("leaderboard.py::get_leaderboard", "Return"): 1,
    ("leaderboard.py::get_spec_history", "Raise"): 2,
    ("leaderboard.py::get_frontier", "Raise"): 1,
    ("scores.py::get_score", "Raise"): 3,
    ("store.py::benchmark_to_schema", "Return"): 1,
    ("store.py::_content_hash", "Return"): 1,
    ("store.py::_scoped_idempotency_key", "Return"): 3,
    ("store.py::register_benchmark", "Return"): 1,
    ("store.py::set_visibility", "Return"): 1,
    ("store.py::_resolve_owned", "Return"): 3,
    ("store.py::_readable_by", "Return"): 3,
    ("store.py::_links_to_a_private_board", "Return"): 1,
    ("metadata_store.py::update_metadata", "Raise"): 3,
    ("metadata_store.py::update_metadata", "Return"): 2,
    ("metadata_store.py::metadata_history", "Raise"): 2,
    ("metadata_store.py::metadata_history", "Return"): 1,
    ("store.py::submit", "Raise"): 1,
    ("seed.py::_apply_orphan_visibility", "Return"): 1,
    ("seed.py::_classify_configured", "Return"): 1,
    ("seed.py::_with_configured_visibility", "Return"): 1,
    ("seed.py::seed_from_sources", "Return"): 1,
    ("seed.py::seed_benchmarks", "Return"): 1,
    ("check_rollback_safety.py::private_boards", "Return"): 1,
    ("check_rollback_safety.py::format_verdict", "Return"): 2,
    ("check_rollback_safety.py::running_version", "Return"): 2,
    ("purge_private_benchmark.py::_purge_visibility_query", "Return"): 1,
    ("backfill_systems.py::_public_unlinked_heads", "Return"): 1,
    ("service.py::resolve_for_submit", "Return"): 3,
    ("service.py::resolve_for_submit", "Raise"): 1,
    ("cluster_store.py::submit", "Raise"): 1,
    ("cluster_store.py::submit", "Return"): 2,
    ("cluster_store.py::_write", "Return"): 1,
    ("cluster_store.py::_replay_allowed", "Return"): 2,
    ("replay_access.py::is_owner", "Return"): 2,
    ("replay_access.py::replay_access", "Return"): 3,
    ("results.py::_readable_head", "Raise"): 3,
    ("results.py::_readable_head", "Return"): 1,
    ("store.py::readable_by", "Return"): 1,
    ("replay_resolver.py::resolve", "Raise"): 1,
    ("replay_resolver.py::resolve", "Return"): 2,
    ("replay_resolver.py::_access", "Return"): 1,
    ("eligibility.py::publish_refusal", "Return"): 1,
    ("publish.py::_load", "Return"): 3,
    ("publish.py::_check_owner", "Return"): 1,
    ("publish.py::_check_owner", "Raise"): 2,
    ("publish.py::_check_publishable", "Return"): 1,
    ("publish.py::_check_publishable", "Raise"): 3,
}


def _revalidates(node: ast.AST) -> bool:
    return any(name in ast.unparse(node) for name in REVAL)


def _always_exits(body: list[ast.stmt]) -> bool:
    return any(isinstance(st, ast.Return | ast.Raise) for st in body)


_SIMPLE = (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)


class _ExitWalker:
    """Collect the exits a revalidation does NOT dominate.

    Split into one small method per statement kind because the flat version tripped `C901`, and the
    limit is right: the propagation rules are the substance of this guard and each deserves reading
    on its own.
    """

    def __init__(self) -> None:
        self.unguarded: list[str] = []

    def walk(self, stmts: list[ast.stmt], revalidated: bool) -> None:
        for st in stmts:
            revalidated = self._visit(st, revalidated)

    def _visit(self, st: ast.stmt, revalidated: bool) -> bool:
        # A dispatch table rather than a chain of `return`s: the chain tripped `PLR0911`, and the
        # limit is fair — the interesting part is each rule, not the branching to reach it.
        for kinds, handler in (
            (ast.Return | ast.Raise, self._visit_exit),
            (_SIMPLE, self._visit_simple),
            (ast.If, self._visit_if),
            (ast.Try, self._visit_try),
            (ast.With | ast.AsyncWith, self._visit_with),
            (_LOOPS, self._visit_loop),
        ):
            if isinstance(st, kinds):
                return handler(st, revalidated)
        return revalidated

    def _visit_exit(self, st: ast.stmt, revalidated: bool) -> bool:
        if not revalidated:
            self.unguarded.append(type(st).__name__)
        return revalidated

    def _visit_simple(self, st: ast.stmt, revalidated: bool) -> bool:
        return revalidated or _revalidates(st)

    def _visit_loop(self, st: ast.stmt, revalidated: bool) -> bool:
        assert isinstance(st, _LOOPS)
        self.walk(st.body, revalidated)
        return revalidated

    def _visit_if(self, st: ast.stmt, revalidated: bool) -> bool:
        assert isinstance(st, ast.If)
        guard = _revalidates(st.test)
        self.walk(st.body, revalidated or guard)
        self.walk(st.orelse, revalidated)
        # A guard in the TEST whose body always exits means falling through IS the revalidated
        # path: the check ran and reported no change.
        return revalidated or (guard and _always_exits(st.body))

    def _visit_try(self, st: ast.stmt, revalidated: bool) -> bool:
        assert isinstance(st, ast.Try)
        for block in (st.body, st.orelse, st.finalbody):
            self.walk(block, revalidated)
        for handler in st.handlers:
            self.walk(handler.body, revalidated)
        return revalidated

    def _visit_with(self, st: ast.stmt, revalidated: bool) -> bool:
        assert isinstance(st, ast.With | ast.AsyncWith)
        self.walk(st.body, revalidated)
        # The body must finish before control leaves the block, so a revalidation inside it
        # dominates everything after — this is how the insert path is guarded.
        return revalidated or any(
            isinstance(s, ast.Expr | ast.Assign) and _revalidates(s) for s in st.body
        )


def _unguarded_exits(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    walker = _ExitWalker()
    walker.walk(fn.body, False)
    return walker.unguarded


def _visibility_dependent(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if any(marker in fn.name for marker in ("revalidate", "turned_private")):
        return False
    body = ast.unparse(fn)
    params = {arg.arg for arg in fn.args.args + fn.args.kwonlyargs}
    return (
        "visibility" in body
        or "is_private" in body
        or bool(params & {"per_submitter", "identity_verified"})
    )


def _survey() -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not _visibility_dependent(node):
                continue
            for kind in _unguarded_exits(node):
                counts[(f"{path.name}::{node.name}", kind)] = (
                    counts.get((f"{path.name}::{node.name}", kind), 0) + 1
                )
    return counts


def test_no_visibility_dependent_exit_is_unguarded_without_a_recorded_reason() -> None:
    actual = _survey()

    new = {k: v for k, v in actual.items() if k not in EXPECTED_UNGUARDED}
    grown = {
        k: (EXPECTED_UNGUARDED[k], v)
        for k, v in actual.items()
        if k in EXPECTED_UNGUARDED and v > EXPECTED_UNGUARDED[k]
    }
    assert not new, (
        "a visibility-dependent function gained an UNGUARDED exit: "
        f"{sorted(new)}. Either revalidate before it, or add it to EXPECTED_UNGUARDED with the "
        "reason it needs no guard."
    )
    assert not grown, (
        f"these functions gained further unguarded exits: {grown}. Same choice: guard them, or "
        "record why they are safe."
    )


def test_the_recorded_reasons_have_not_gone_stale() -> None:
    # The other direction: an entry that no longer matches means an exit was guarded or removed, and
    # the list should shrink rather than quietly over-permit the next one.
    actual = _survey()
    stale = {k: v for k, v in EXPECTED_UNGUARDED.items() if actual.get(k, 0) != v}

    assert not stale, (
        f"EXPECTED_UNGUARDED is out of date: {stale}. Each key maps to how many unguarded exits "
        "that function is allowed; lower it when one gets guarded."
    )


# --- baselines stay visible on a private board (owner decision, 2026-08-27) -------------------

BASELINE_PUBLISHED_FIELDS = frozenset(
    {
        "benchmark_id",
        "id",
        "imported_at",
        "metadata",
        "model_name",
        "openness_override",
        "score",
        "source",
        "source_url",
    }
)


def test_a_baseline_publishes_nothing_participant_derived() -> None:
    # DECISION (owner, 2026-08-27): baselines stay visible on a private board. A private board hides
    # participants' submissions from each other; an imported LMArena / Artificial Analysis number is
    # published third-party data about a public model. The entry challenge also needs a line to
    # beat: `entries` is empty there, so without it a participant cannot judge their own score.
    #
    # INVARIANT: that reasoning holds only while a baseline carries nothing participant-derived. It
    # has no submitter, no url4 expression and no spec today, and only
    # `python -m scoreboard.import_baselines` can create one — there is no route. This pins the
    # published field set so ADDING one forces the decision to be retaken rather than inherited.
    #
    # `metadata` is the live risk: a free-form blob. It is published deliberately, and importing a
    # baseline whose metadata carries a participant's run details would leak it on a private board.
    # That is an import-time discipline, not something the schema can enforce.
    from scoreboard.scores.schemas import BaselineSchema

    assert set(BaselineSchema.model_fields) == BASELINE_PUBLISHED_FIELDS, (
        "BaselineSchema's published fields changed. Baselines are served on PRIVATE boards, so a "
        "new field is visible to every participant — confirm it carries nothing derived from "
        "another participant's submission, then update BASELINE_PUBLISHED_FIELDS."
    )
    for leak in ("submitted_by", "submitter", "url4_expression", "spec_id", "email"):
        assert leak not in BaselineSchema.model_fields, (
            f"{leak!r} would be published on a private board through the baseline list"
        )


# --- the persist and purge paths really take the PostgreSQL row lock ---------------------------


async def test_the_persist_and_purge_paths_really_lock_the_row() -> None:
    """Both production visibility-lock paths must emit `FOR UPDATE` on PostgreSQL.

    INVARIANT: the lock is the only thing that CLOSES the flip window on the persist and purge paths
    — revalidation alone narrows it to the commit interval. SQLite does not implement the lock, so
    no behavioural test can hold this; rendering the SQL can, and does.

    WHY this test exists at all: the first version of that code called `select_for_update()` and
    then `values_list()`. The former sets lock state on the QuerySet; the latter builds a fresh
    query without copying it. So `FOR UPDATE` was silently dropped and the path had no lock, while
    the description and a review reply both claimed it did. The claim was made about a dialect and
    never rendered against that dialect. This is that check (review of PR #719).
    """
    from tortoise import Tortoise

    from scoreboard.purge_private_benchmark import _purge_visibility_query
    from scoreboard.scores.models import Benchmark
    from scoreboard.scores.store import ScoreStore

    await Tortoise.init(
        db_url="asyncpg://user:pass@127.0.0.1:1/unused",
        modules={"models": ["scoreboard.scores.models"]},
        _create_db=False,
    )
    try:
        store = ScoreStore()
        # The query PRODUCTION runs, not one this test builds — a hand-built query would keep
        # passing while `_revalidate_visibility` regressed underneath it.
        # Rendered without `.first()`: that returns a typed single-row wrapper which does not
        # declare `.sql()`. `.first()` only adds a LIMIT, and it was checked separately not to
        # strip the lock — `.select_for_update().only(...)` and `.first()` both preserve it, while
        # `.values()` and `.values_list()` are the two that drop it.
        locked = store.visibility_query("any-benchmark", lock=True).sql()
        purge_locked = _purge_visibility_query(
            Tortoise.get_connection("default"), "any-benchmark"
        ).sql()
        unlocked = store.visibility_query("any-benchmark").sql()
        projected = (
            Benchmark.filter(id="any-benchmark")
            .select_for_update()
            .values_list("visibility", flat=True)
            .sql()
        )
    finally:
        await Tortoise.close_connections()

    assert "FOR UPDATE" in locked.upper(), f"the locking revalidation query lost its lock: {locked}"
    assert "FOR UPDATE" in purge_locked.upper(), (
        f"the private-board purge query lost its lock: {purge_locked}"
    )
    assert "FOR UPDATE" not in unlocked.upper(), (
        "the read-only revalidation must NOT lock — it runs on every dedup hit"
    )
    # Pinned as the trap, not as an aspiration: if a future Tortoise starts carrying lock state
    # through `values_list()` this fails, and the comment above can be simplified.
    assert "FOR UPDATE" not in projected.upper(), (
        "values_list() now preserves select_for_update(); the workaround in "
        "_revalidate_visibility can be simplified and this test updated"
    )
