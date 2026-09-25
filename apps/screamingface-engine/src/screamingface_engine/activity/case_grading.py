"""Bounded case-phase records, distinct from timed endpoint operations."""

from hashlib import sha256

from screamingface_engine.activity.contract import PREFIX, SCHEMA, Emitter, facts
from screamingface_engine.activity.session import ActivitySession
from screamingface_engine.benchmarks.contract import CaseId
from screamingface_engine.benchmarks.grading_activity import GradingState

MAX_PENDING_CASES = 1024


def emit_case_grading(
    session: ActivitySession | None,
    sink: Emitter | None,
    case_id: CaseId,
    state: GradingState,
    pending: dict[str, bool],
) -> None:
    if session is None or not session.active or sink is None:
        return
    # INVARIANT: one selected Case per run; normalize integer/string wire IDs, not "007".
    # Track only active cases: record-only endpoints must not report grading completion.
    identity = "case-grading-" + sha256(str(case_id).encode()).hexdigest()
    prepaid = pending.get(identity, False)
    if not _transition(session, pending, identity, state):
        return
    admitted = session.emit(
        sink,
        f"Grading {state}",
        {
            PREFIX + "schema": SCHEMA,
            PREFIX + "id": identity,
            PREFIX + "kind": "grading",
            PREFIX + "state": state,
            PREFIX + "revision": 1 if state == "started" else 2,
            PREFIX + "elapsed_ms": 0,
            PREFIX + "observed_at_ms": int(session.wall() * 1000),
            PREFIX + "scope": "case",
            **facts({"case_id": case_id}),
        },
        reserve_terminal=state == "started",
        prepaid_terminal=state != "started" and prepaid,
    )
    if state == "started":
        pending[identity] = admitted


def _transition(
    session: ActivitySession, pending: dict[str, bool], identity: str, state: GradingState
) -> bool:
    accepted = False
    if state == "started":
        if identity not in pending:
            if len(pending) >= MAX_PENDING_CASES:
                session.suppress("rate")
            else:
                pending[identity] = False
                accepted = True
    elif identity in pending:
        del pending[identity]
        accepted = True
    return accepted
