"""Router JOIN: the single publisher of a Router occurrence's completed record (C4, C5, C8, C11).

FEATURE: Router Recipe extension. JOIN reads ADMIT's result, DECIDE's draft and the iterate rows
of the branch OPEN chose, checks that they describe one occurrence, completes the C5 record from
the C8 attempt facts of the spec's `Calls` bindings, publishes it under ``?binding=router_N`` (as
`record_gate_call` does for a Gate), and only then returns the answer, returns ``""`` for an
abstention, or raises the failing operation's code and permanence.

STORY: as a benchmark reader, every Router occurrence leaves exactly one record that names what
was decided, which Models answered and where it failed, and never the question or the answer.

INVARIANT: a binding is never inferred from a label or a default Model from an attempt; roles come
from ``admit.spec``. A malformed context raises before anything is published.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from screamingface_engine.benchmarks.failure_classes import benchmark_contract_error
from screamingface_engine.budget import call_charge
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import (
    AttemptFact,
    latest_attempt_fact,
    latest_operation_call,
    record_router_call,
)
from screamingface_engine.router_decision import (
    DECISION_SCHEMA,
    RouterDecision,
    RouterDecisionError,
    RouterDraft,
    parse_router_decision,
)
from screamingface_engine.router_vocabulary import RouterPolicy
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.router_decide import candidate_slot
from screamingface_engine.world.router_evidence import RowFailure
from screamingface_engine.world.router_provenance import (
    bound_row,
    first_run,
    proven_admit,
    proven_draft,
)
from screamingface_engine.world.router_spec import AdmittedSpec, LlmSelector, RegexSelector
from screamingface_engine.world.router_steps import (
    ROUTER_JOIN_ROUTE,
    Accepted,
    Carried,
    StepCall,
    compact_json,
    read_rows,
    step_binding,
    step_object,
)

logger = logging.getLogger(__name__)

_FIXED_KEYS = frozenset({"admit", "decision"})
_DEFAULT_SLOT = "d"
_BODY_SLOTS = frozenset({_DEFAULT_SLOT, "panel"})
Status = Literal["answered", "abstained", "failed"]


@dataclass(frozen=True, slots=True)
class _Failure:
    phase: str
    code: str
    permanent: bool


@dataclass(frozen=True, slots=True)
class _Ending:
    """How the occurrence ended, and the calls that ran for it."""

    text: str
    status: Status
    failure: _Failure | None = None
    branches: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    classifier_call: dict[str, object] | None = None


def join(call: StepCall) -> str:
    """Publish the completed C5 record, then return the answer, ``""`` or raise its failure.

    Raises:
        RunnerRequestError: the occurrence failed: the failing operation's code and permanence.
        ResolutionError: `benchmark_contract_error` for a malformed context; nothing published.
    """
    router = step_binding(call.params, "join")
    # INVARIANT (C4, C5): one JOIN per occurrence and scope, claimed before anything is read,
    # so a second JOIN for the binding publishes no second record.
    first_run("join", router)
    if call.intent:
        raise benchmark_contract_error("router join takes no intent")
    context = step_object(call.context, "join")
    if not _FIXED_KEYS <= context.keys():
        raise benchmark_contract_error("router join context has its admit and decision")
    # INVARIANT: JOIN publishes only for the ADMIT result and draft this occurrence
    # recorded, each naming its own binding.
    admission = proven_admit(context["admit"], "join", router)
    draft = proven_draft(context["decision"], "join", router)
    slots = {key: value for key, value in context.items() if key not in _FIXED_KEYS}
    if isinstance(admission, Carried):
        ending = _carried(admission, draft, slots)
        record = _record(draft, None, ending)
    else:
        ending = _accepted(admission, draft, slots)
        record = _record(draft, admission.admitted, ending)
    record_router_call(ROUTER_JOIN_ROUTE, {"binding": router}, ending.text, record)
    logger.info("router=%s outcome=%s status=%s", router, draft.outcome, ending.status)
    failure = ending.failure
    if failure is not None:
        raise RunnerRequestError(
            f"the Router {router} failed at {failure.phase}",
            code=failure.code,
            permanent=failure.permanent,
        )
    return ending.text


# --- agreement ------------------------------------------------------------------------------------


def _carried(admission: Carried, draft: RouterDraft, slots: dict[str, object]) -> _Ending:
    """An occurrence ADMIT did not accept: its draft copies the carried failure; nothing ran."""
    failure = draft.failure
    carried = (admission.phase, admission.code, admission.permanent)
    if failure is None or (failure.phase, failure.code, failure.permanent) != carried:
        raise benchmark_contract_error("router join decision does not carry the admit failure")
    for key, value in slots.items():
        if (candidate_slot(key) is None and key not in _BODY_SLOTS) or read_rows(value, "join"):
            raise benchmark_contract_error("router join: an unadmitted occurrence ran a branch")
    return _Ending("", "failed", _Failure(*carried))


def _accepted(admission: Accepted, draft: RouterDraft, slots: dict[str, object]) -> _Ending:
    admitted = admission.admitted
    _check_agrees(admitted, draft)
    opened = _opened(admitted, draft)
    if slots.keys() != _slot_names(admitted):
        raise benchmark_contract_error("router join context has one slot per candidate and default")
    rows = {key: read_rows(value, "join") for key, value in slots.items()}
    if any(found for key, found in rows.items() if key != opened):
        raise benchmark_contract_error("router join: a branch it did not choose ran")
    classifier_call = _classifier_call(admitted, draft)
    if draft.failure is not None:
        failure = draft.failure
        ending = _Failure(failure.phase, failure.code, failure.permanent)
        return _Ending("", "failed", ending, classifier_call=classifier_call)
    if opened is None:
        return _Ending("", "abstained", classifier_call=classifier_call)
    if len(rows[opened]) != 1:
        raise benchmark_contract_error("router join: the chosen branch left one row")
    return _branch(admitted, opened, rows[opened][0], classifier_call)


def _check_agrees(admitted: AdmittedSpec, draft: RouterDraft) -> None:
    definition = admitted.definition
    failure = draft.failure
    if (
        draft.revision != admitted.revision
        or draft.policy != definition.policy
        or (failure is not None and failure.phase in ("input", "admit"))
        or any(index >= len(definition.candidates) for index in draft.selected)
        or (draft.outcome == "default" and definition.default is None)
    ):
        raise benchmark_contract_error("router join decision and admit describe different routers")


def _opened(admitted: AdmittedSpec, draft: RouterDraft) -> str | None:
    """The slot OPEN opened for ``draft``: the selected candidate, the default, or none."""
    if draft.outcome == "selected":
        if _subset(admitted):
            # WHY (C4): a selected subset's panel and record are Unit 6's.
            raise benchmark_contract_error("router join: a selected subset is not joined here")
        (index,) = draft.selected
        return f"c{index}"
    return _DEFAULT_SLOT if draft.outcome == "default" else None


def _slot_names(admitted: AdmittedSpec) -> set[str]:
    candidates = len(admitted.definition.candidates)
    names = {"panel"} if _subset(admitted) else {f"c{index}" for index in range(candidates)}
    return names | {_DEFAULT_SLOT} if admitted.definition.default is not None else names


def _subset(admitted: AdmittedSpec) -> bool:
    policy = admitted.definition.policy
    return isinstance(policy, RouterPolicy) and policy.select == "all"


# --- the record -----------------------------------------------------------------------------------


def _branch(
    admitted: AdmittedSpec, slot: str, row: str, classifier_call: dict[str, object] | None
) -> _Ending:
    """The chosen branch's answer or failure, and its attempts when its call made any (C8)."""
    index = candidate_slot(slot)
    calls, definition = admitted.calls, admitted.definition
    if index is None:
        default, binding, phase = definition.default, calls.default, "default"
        if default is None or binding is None:
            raise benchmark_contract_error("router join: a default slot without a default")
        entry: dict[str, object] = {"role": "default", "index": None, "label": None}
        entry["model"] = default.model
    else:
        candidate = definition.candidates[index]
        binding, phase = calls.candidates[index], "generate"
        entry = {"role": "candidate", "index": index, "label": candidate.label}
        entry["model"] = candidate.model.model
    # INVARIANT (C8): the row is proven by its call's recorded outcome and attempt fact,
    # and the answer is the recorded reply; a call with no HTTP attempt has no branch entry.
    read = bound_row(row, binding, str(entry["model"]), "join")
    fact = latest_attempt_fact(binding)
    code = read.code if isinstance(read, RowFailure) else None
    branches = (
        [] if fact is None else [{**entry, "status": fact.status, "code": code, **_attempts(fact)}]
    )
    if isinstance(read, RowFailure):
        failure = _Failure(phase, read.code, read.permanent)
        return _Ending("", "failed", failure, branches, classifier_call)
    return _Ending(read, "answered", None, branches, classifier_call)


def _classifier_call(admitted: AdmittedSpec, draft: RouterDraft) -> dict[str, object] | None:
    """The classifier's call from its attempt fact; null for regex or when it made no attempt.

    INVARIANT (C5): evidence exists only because its call answered, so evidence with no
    attempt fact is lost execution state, never a record with invented attempts.
    """
    classifier = admitted.definition.classifier
    if isinstance(classifier, RegexSelector):
        return None
    # INVARIANT (C8): a scoring classification's fact carries the occurrence binding router_N.
    binding = admitted.calls.classifier if isinstance(classifier, LlmSelector) else admitted.router
    fact = None if binding is None else latest_attempt_fact(binding)
    if binding is None or fact is None:
        if draft.evidence is not None:
            raise benchmark_contract_error("router join: evidence without its classifier's call")
        return None
    return {"binding": binding, "cost": _cost(binding), **_attempts(fact)}


def _cost(binding: str) -> float | None:
    """The call's USD charge by the Budget's rule (`budget.charge`); unknown stays null."""
    wanted = ("binding", binding)
    call = latest_operation_call(lambda found: found.is_provider and wanted in found.params)
    if call is None:
        return None
    return call_charge(call.signal_accounting or SignalAccounting()).usd


def _attempts(fact: AttemptFact) -> dict[str, object]:
    return {
        "engine_attempts": fact.engine_attempts,
        "upstream_attempts": fact.upstream_attempts,
        "possibly_billed": fact.possibly_billed,
    }


def _record(draft: RouterDraft, admitted: AdmittedSpec | None, ending: _Ending) -> RouterDecision:
    document = draft.document()
    selected: list[dict[str, object]] = []
    if admitted is not None:
        candidates = admitted.definition.candidates
        selected = [
            {
                "index": index,
                "label": candidates[index].label,
                "model": candidates[index].model.model,
            }
            for index in draft.selected
        ]
    failure = ending.failure
    document.update(
        schema=DECISION_SCHEMA,
        selected=selected,
        classifier_call=ending.classifier_call,
        branches=ending.branches,
        quorum=None,
        synthesis=None,
        status=ending.status,
        failure=None if failure is None else {"phase": failure.phase, "code": failure.code},
    )
    try:
        return parse_router_decision(compact_json(document))
    except RouterDecisionError:
        # INVARIANT: the parts are checked above, so an inconsistent record is an Engine defect.
        raise benchmark_contract_error("router join completed no valid record") from None


__all__ = ["join"]
