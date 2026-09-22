"""The corrective loop's generic runtime — six benchmark-neutral endpoints.

FEATURE: OME-796 — benchmark-independent corrective loop (engine half).
STORY: as a client-compiled `sf.CorrectiveLoop` candidate, my rounds fan out as
ordinary model calls and check-surface calls; these endpoints are the only
control flow and invocation boundaries that URL4 composes into the complete
Recipe: nested member/role invocation, conditional gating, verbatim selection,
chain collapse, and terminal-outcome projection.

Mental model: an exam room's clockwork. Drafts and their check records flow in
as data; these endpoints decide STOP/RETRY, pick the submitted draft word-for-
word, and hand the final answer back up the gated chain. They know NOTHING
about any benchmark: `passed` and `satisfaction` were computed behind the
benchmark's check-surface adapter, so the same routes serve IFEval today
and every rubric benchmark tomorrow. In execution order per round k:

1. The client-compiled expression calls `GATE_ROUTE` with `tie:k:max` — a
   0-or-1-item collection naming the drafts a judge must pick among (>=2
   passers, or a final-round exact satisfaction tie). Empty = no judge call.
2. `SELECT_ROUTE` picks round k's representative answer VERBATIM.
3. `GATE_ROUTE` with `continue:k:max` — one payload iff nobody passed and the
   round budget is not spent; the retry subtree iterates over it (empty = the
   subtree never executes — that is the whole cost story).
4. `ANSWER_ROUTE` collapses `{selected, next}` bottom-up: the deepest executed
   round's selection wins, because a continuation only exists when its round
   was bought by a no-pass gate.

Worked example (3 members, max_rounds=3): round 1 has one passer -> tie gate
[], select returns the passer, continue gate [], answer returns it. Total: 3
model calls, 3 checks, zero judge calls, zero retries.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from screamingface_engine.benchmarks.candidate_execution import record_candidate_execution
from screamingface_engine.benchmarks.contract import (
    CorrectiveExecution,
    decode_candidate_invocation,
)
from screamingface_engine.benchmarks.ensemble.policy import (
    ANSWER_ROUTE,
    CHECK_SURFACE_SCHEMA,
    GATE_ROUTE,
    MEMBER_ROUTE,
    RESULT_ROUTE,
    ROLE_ROUTE,
    SELECT_ROUTE,
    member_labels,
)
from screamingface_engine.benchmarks.evaluation import compact_json, json_array, json_object
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error as _contract_error,
)
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_definition_error as _definition_error,
)
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.model_outcomes import (
    ModelOutcome,
    bind_model_outcome,
    record_model_outcome,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_NESTED_INPUT_BINDING = "_sf_recipe_input"
_CORRECTIVE_OUTCOME_SCHEMA = "screamingface.corrective-outcome.v1"


def install_corrective_runtime(node: Url4Node) -> None:
    """Register the corrective loop's generic endpoints once per URL4 world."""

    routes = frozenset(node.processor_routes())
    endpoints = (
        (GATE_ROUTE, _gate),
        (SELECT_ROUTE, _select),
        (ANSWER_ROUTE, _answer),
        (MEMBER_ROUTE, _RecipeInvocation(node, role=False)),
        (ROLE_ROUTE, _RecipeInvocation(node, role=True)),
        (RESULT_ROUTE, _result),
    )
    for route, handler in endpoints:
        if route not in routes:
            node.endpoint(route)(handler)


class _RecipeInvocation:
    """Evaluate one nested Recipe without attributing sibling outcomes to its parent."""

    __slots__ = ("_node", "_role")

    def __init__(self, node: Url4Node, *, role: bool) -> None:
        self._node = node
        self._role = role

    async def __call__(self, request: Request) -> str:
        if request.params:
            raise _definition_error("corrective Recipe invocation does not accept parameters")
        if not request.intent.strip():
            raise _definition_error("corrective Recipe invocation expression must be non-empty")
        invocation = await evaluate_candidate_recipe(
            self._node,
            request.intent,
            request.context or "",
            isolated=True,
            input_binding=_NESTED_INPUT_BINDING,
        )
        if not self._role:
            return invocation
        output, _finish_reason, refusal = _invocation(invocation, "corrective role")
        if refusal is not None:
            raise ResolutionError(
                "a corrective-loop judge or coach refused its internal role",
                code="corrective_role_failed",
                permanent=False,
            )
        return output


def _gate(request: Request) -> str:
    """The loop's deterministic control flow, as 0-or-1-item collections.

    `continue:<attempt>:<max_rounds>` — one payload iff the attempt had NO
    passing check and the round budget is not spent; empty means the case
    STOPPED (early exit). `tie:<attempt>:<max_rounds>` — one payload naming the
    drafts a judge must pick among: the passers when two or more passed, or
    (final attempt only) the never-pass drafts tied on maximal satisfaction.

    INVARIANT: this endpoint is pure data -> data. Its decision-table tests pin
    what the expression cannot show: what each gate decides.
    """

    kind, attempt, max_rounds = _gate_intent(request.intent)
    members = _round_records(request.context, "gate round")
    passers = [member for member in members if member["passed"]]
    if kind == "continue":
        proceed = not passers and attempt < max_rounds
        payload = [{"attempt": attempt + 1}] if proceed else []
        return compact_json(payload)
    if len(passers) >= 2:
        pool = passers
    elif not passers and attempt == max_rounds:
        best = max(member["satisfaction"] for member in members)
        tied = [member for member in members if member["satisfaction"] == best]
        pool = tied if len(tied) >= 2 else []
    else:
        pool = []
    if not pool:
        return compact_json([])
    return compact_json(
        [
            {
                "attempt": attempt,
                "candidates": [
                    {"key": member["key"], "answer": member["answer"]} for member in pool
                ],
            }
        ]
    )


def _select(request: Request) -> str:
    """Select the round's representative Candidate Invocation.

    Rules, in order:
    1. Exactly one passer -> that answer; no judge involved.
    2. Two or more passers -> the tie-break judge's label chooses among the
       PASSERS; an invalid or missing label falls back to the first passer.
    3. No passer -> maximal satisfaction; an exact tie defers to the judge's
       label among the tied, else the first tied answer stands.

    INVARIANT: the selected envelope always carries a member's exact answer or
    refusal text. Selection can choose but never rewrite, and it preserves the
    terminal provider outcome that produced that text.
    """

    payload = json_object(request.context, "corrective selection")
    if set(payload) != {"round", "tie"}:
        raise _contract_error("corrective selection payload must carry exactly round and tie")
    members = _round_records(payload["round"], "selection round")
    label = _tie_label(payload["tie"], members)
    passers = [member for member in members if member["passed"]]
    if len(passers) == 1:
        chosen = passers[0]
    elif passers:
        chosen = _by_label(passers, label) or passers[0]
    else:
        best = max(member["satisfaction"] for member in members)
        tied = [member for member in members if member["satisfaction"] == best]
        chosen = tied[0] if len(tied) == 1 else (_by_label(tied, label) or tied[0])
    invocation = chosen["invocation"]
    assert isinstance(invocation, str)
    return compact_json(
        {
            "schema": _CORRECTIVE_OUTCOME_SCHEMA,
            "invocation": invocation,
            "round": _positive_int(request.intent, "round"),
            "passed": bool(passers),
        }
    )


def _answer(request: Request) -> str:
    """Collapse `{selected, next}` into one selected Candidate Invocation.

    `next` is the gated continuation's collection: empty (this round's
    selection stands — someone passed, or the budget is spent) or one deeper
    outcome envelope (a later round ran, and later rounds only run when this
    one had no passer, so the deeper invocation wins).
    """

    payload = json_object(request.context, "corrective answer")
    if set(payload) != {"selected", "next"}:
        raise _contract_error("corrective answer payload must carry exactly selected and next")
    selected = _corrective_outcome(payload["selected"], "corrective answer selected")
    next_value = payload["next"]
    items = json_array(next_value, "corrective continuation") if next_value != "" else []
    if len(items) > 1:
        raise _contract_error("corrective continuation must carry at most one outcome")
    if not items:
        return compact_json(selected)
    outcome = _corrective_outcome(items[0], "corrective continuation outcome")
    return compact_json(outcome)


def _result(request: Request) -> str:
    """Project the selected member invocation back into the outer Candidate scope."""

    if request.params:
        raise _definition_error("corrective result does not accept parameters")
    outcome = _corrective_outcome(request.context, "corrective result")
    output, finish_reason, refusal = _invocation(outcome["invocation"], "corrective result")
    record_candidate_execution(
        CorrectiveExecution(
            stop_reason="passed" if outcome["passed"] else "max_rounds",
            rounds_executed=outcome["round"],
        )
    )
    if refusal is not None:
        error = ResolutionError(refusal, code="provider_refusal", permanent=True)
        raise bind_model_outcome(error, ModelOutcome(finish_reason, refusal))
    record_model_outcome(finish_reason, None)
    return output


def _corrective_outcome(value: object, label: str) -> dict[str, Any]:
    outcome = json_object(value, label)
    expected = {"schema", "invocation", "round", "passed"}
    if set(outcome) != expected or outcome.get("schema") != _CORRECTIVE_OUTCOME_SCHEMA:
        raise _contract_error(f"{label} must be a {_CORRECTIVE_OUTCOME_SCHEMA} outcome")
    invocation = outcome["invocation"]
    _invocation(invocation, label)
    round_number = outcome["round"]
    if isinstance(round_number, bool) or not isinstance(round_number, int) or round_number < 1:
        raise _contract_error(f"{label} round must be a positive integer")
    passed = outcome["passed"]
    if not isinstance(passed, bool):
        raise _contract_error(f"{label} passed must be a boolean")
    return dict(outcome)


def _gate_intent(intent: str) -> tuple[str, int, int]:
    kind, sep, rest = (intent or "").partition(":")
    if not sep or kind not in {"continue", "tie"}:
        raise _unsupported("corrective gate", intent)
    attempt_part, sep, max_part = rest.partition(":")
    if not sep:
        raise _unsupported("corrective gate", intent)
    attempt = _positive_int(attempt_part, "attempt")
    max_rounds = _positive_int(max_part, "max_rounds")
    if attempt > max_rounds:
        raise _definition_error(f"corrective attempt {attempt} exceeds max_rounds {max_rounds}")
    return kind, attempt, max_rounds


def _round_records(value: object, label: str) -> list[dict[str, Any]]:
    """Decode one round: an object mapping consecutive member labels to records."""

    payload = json_object(value, label)
    if not payload:
        raise _contract_error(f"{label} must carry at least one member record")
    expected = member_labels(len(payload))
    if tuple(payload) != expected:
        raise _contract_error(f"{label} member labels must be consecutive from 'a'")
    return [
        _surface_record(payload[key], f"{label} member {key!r}", key=key.upper())
        for key in expected
    ]


def _surface_record(value: object, label: str, *, key: str) -> dict[str, Any]:
    """Validate one check-surface port record (accepted as JSON text or object)."""

    record = _decoded_record(value, label)
    passed = record["passed"]
    if not isinstance(passed, bool):
        raise _contract_error(f"{label} passed must be a boolean")
    satisfaction = record["satisfaction"]
    if (
        isinstance(satisfaction, bool)
        or not isinstance(satisfaction, int | float)
        or not 0.0 <= satisfaction <= 1.0
    ):
        raise _contract_error(f"{label} satisfaction must be a number in [0, 1]")
    feedback = record["feedback"]
    if not isinstance(feedback, str):
        raise _contract_error(f"{label} feedback must be text")
    answer = record["answer"]
    if not isinstance(answer, str):
        raise _contract_error(f"{label} answer must be text")
    invocation = record["invocation"]
    output, _finish_reason, refusal = _invocation(invocation, label)
    invocation_answer = refusal if refusal is not None else output
    if invocation_answer != answer:
        raise _contract_error(f"{label} answer must equal its Candidate Invocation text")
    return {
        "key": key,
        "passed": passed,
        "satisfaction": float(satisfaction),
        "feedback": feedback,
        "answer": answer,
        "invocation": invocation,
    }


def _decoded_record(value: object, label: str) -> dict[str, Any]:
    """Decode the record envelope and pin its closed key set.

    The closed key set is deliberate: this record flows inside a client-compiled
    expression, so an adapter smuggling extra fields through it would widen the
    sealed-envelope surface for every benchmark at once.
    """

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise _contract_error(f"{label} must be a JSON check-surface record: {exc}") from None
    if not isinstance(value, dict) or value.get("schema") != CHECK_SURFACE_SCHEMA:
        raise _contract_error(f"{label} must be a {CHECK_SURFACE_SCHEMA} check-surface record")
    expected = {"schema", "passed", "satisfaction", "feedback", "answer", "invocation"}
    if set(value) != expected:
        raise _contract_error(
            f"{label} must carry exactly schema, passed, satisfaction, feedback, answer, "
            "and invocation"
        )
    return value


def _invocation(value: object, label: str) -> tuple[str, str | None, str | None]:
    if not isinstance(value, str):
        raise _contract_error(f"{label} Candidate Invocation must be text")
    try:
        return decode_candidate_invocation(value)
    except (TypeError, ValueError) as exc:
        raise _contract_error(f"{label} has an invalid Candidate Invocation: {exc}") from exc


def _tie_label(value: object, members: list[dict[str, Any]]) -> str | None:
    """The judge's label from the 0-or-1-item tie-pick collection, if any."""

    items = json_array(value, "tie picks") if value not in (None, "") else []
    if not items:
        return None
    selected = {member["key"]: member for member in members}
    return _judge_label(items[0], selected)


def _by_label(pool: list[dict[str, Any]], label: str | None) -> dict[str, Any] | None:
    if label is None:
        return None
    for member in pool:
        if member["key"] == label:
            return member
    return None


def _judge_label(reply: object, selected: Mapping[str, object]) -> str | None:
    """Accept only an unambiguous member-label judge reply; prose gets no vote.

    A label names a member answer (``a`` = member 1's answer, ``b`` = member
    2's, and so on). Anything else — prose, an empty reply, a label outside
    the answer set — returns None so `_select`'s deterministic fallbacks apply.
    """

    raw = str(reply or "").strip().upper()
    if not raw:
        return None
    token = raw.split()[0].strip(".,:;!()[]'\"")
    return token if token in selected else None


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise _contract_error(f"corrective {label} must be an integer, got {value!r}")
    try:
        selected = int(value)
    except ValueError:
        raise _contract_error(f"corrective {label} must be an integer, got {value!r}") from None
    if selected < 1:
        raise _contract_error(f"corrective {label} must be positive, got {selected}")
    return selected


def _unsupported(label: str, intent: str) -> ResolutionError:
    return ResolutionError(
        f"unsupported {label} operation {intent!r}",
        code="benchmark_operation_unsupported",
        permanent=True,
    )


__all__ = ["install_corrective_runtime"]
