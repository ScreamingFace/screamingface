"""Proving a Router step's context against what this occurrence really ran (C4, C8).

FEATURE: Router Recipe extension. A Router step reads documents and iterate rows that url4 hands
it, so a forged or replayed context could otherwise publish a record or reach a provider. Each
step therefore accepts only what the capture scope's provenance channel (`operation_provenance`)
recorded for this occurrence:

- ADMIT, the scoring CLASSIFY, DECIDE and JOIN each run once per binding, claimed before any
  work; ADMIT and DECIDE record their result with the typed value they validated it as;
  CLASSIFY, OPEN, DECIDE and JOIN accept an ADMIT result or a draft only when it is the recorded
  one, compared as canonical values, and then read that typed value instead of validating again;
- a scoring classification, a selector row and a branch row are accepted only as the recorded
  outcome of the call of that binding and Model, an answer only with its C8 attempt fact; the
  step then reads the recorded reply, never the caller's bytes.

INVARIANT: a missing or mismatched record is an Engine contract error, raised before any provider
call, any opening and any publication.
INVARIANT: outside a capture scope ADMIT refuses (`router_unsupported`, C4), so only a carried
failure can exist there; an accepted document or a decision is refused as forged.
"""

from __future__ import annotations

import json
from typing import Any

from screamingface_engine.benchmarks.failure_classes import benchmark_contract_error
from screamingface_engine.combine.ports import utf8_exceeds
from screamingface_engine.operation_provenance import (
    CallOutcome,
    ProvenanceConflict,
    RouterStep,
    Step,
    call_outcome,
    canonical_document,
    claim_step,
    latest_attempt_fact,
    provenance_open,
    record_step,
    recorded_step,
    step_payload,
)
from screamingface_engine.router_decision import RouterDraft
from screamingface_engine.router_vocabulary import strict_json
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.router_evidence import RowFailure, bounded_code, read_error_row
from screamingface_engine.world.router_steps import (
    MAX_ROUTER_CONTEXT_BYTES,
    ROUTER_CLASSIFY_ROUTE,
    Accepted,
    Admission,
    Carried,
    admit_document,
    admit_router,
    read_admit,
    read_draft,
    read_rows,
)

_CARRIED_PHASES = frozenset({"input", "admit"})


def first_run(step: RouterStep, binding: str) -> None:
    """Claim this occurrence's one ``step`` for ``binding``; a second one refuses, before any work.

    INVARIANT: call it before the step's first await, read, provider call or publication, so a
    sequential or concurrent duplicate is a contract error with no effect (`claim_step`).
    """
    try:
        claim_step(step, binding)
    except ProvenanceConflict as conflict:
        raise benchmark_contract_error(str(conflict)) from None


def remember(step: Step, binding: str, text: str, typed: Admission | RouterDraft) -> str:
    """Record ``text`` as this occurrence's ``step`` result (in a capture scope) and return it.

    ``typed`` is what the step validated ``text`` as; a later step that proves its context is
    ``text`` reads it back (`proven_admit`, `proven_draft`).
    """
    if not provenance_open():
        return text
    try:
        record_step(step, binding, strict_json(text), typed)
    except ProvenanceConflict as conflict:
        raise benchmark_contract_error(str(conflict)) from None
    return text


def proven_admit(value: object, step: str, binding: str | None = None) -> Admission:
    """ADMIT's result as ``step`` reads it, when it is the one ADMIT recorded for its router.

    ``binding`` is the step's own occurrence binding; CLASSIFY and OPEN have none, so a carried
    failure there (which runs and opens nothing) is read unproven, and DECIDE/JOIN prove it.
    """
    document = admit_document(value, step)
    typed = _typed("admit", binding if binding is not None else admit_router(document), document)
    if isinstance(typed, Accepted | Carried):
        return typed
    admission = read_admit(document, step)
    accepted = isinstance(admission, Accepted)
    router = admission.admitted.router if isinstance(admission, Accepted) else binding
    if binding is not None and router != binding:
        raise benchmark_contract_error(f"router {step} binding and admit name different routers")
    if router is None or not (provenance_open() or accepted):
        return admission
    if not provenance_open() or not _recorded("admit", router, value):
        raise benchmark_contract_error(f"router {step} admit is not this occurrence's ADMIT result")
    return admission


def proven_draft(value: object, step: str, binding: str | None = None) -> RouterDraft:
    """DECIDE's draft as ``step`` reads it, when it is the one DECIDE recorded for its router."""
    document = _draft_document(value)
    if document is not None:
        router = binding if binding is not None else document.get("router")
        typed = _typed("decide", router if isinstance(router, str) else None, document)
        if isinstance(typed, RouterDraft):
            return typed
    draft = read_draft(value, step)
    if binding is not None and draft.router != binding:
        raise benchmark_contract_error(f"router {step} binding and decision name different routers")
    carried = draft.failure is not None and draft.failure.phase in _CARRIED_PHASES
    if provenance_open() and _recorded("decide", draft.router, value):
        return draft
    if not provenance_open() and carried:
        return draft
    raise benchmark_contract_error(f"router {step} decision is not this occurrence's draft")


def proven_classification(evidence: object, router: str) -> CallOutcome:
    """The scoring CLASSIFY outcome ``evidence`` must be: recorded under ``router``, and equal.

    INVARIANT (C8): the classify step's own document (an answer or its failure document); an
    answered classification has its attempt fact. A call that ended without a document (a
    control-plane ending, a cancellation) gave DECIDE nothing to read.
    """
    outcome = _outcome(router, "decide")
    if (
        outcome is None
        or outcome.path != ROUTER_CLASSIFY_ROUTE
        or not outcome.output
        or not _same_document(evidence, outcome.output)
        or (outcome.status == "answered" and not _answered_fact(router))
    ):
        raise benchmark_contract_error("router decide evidence is not this occurrence's scores")
    return outcome


def bound_row(row: str, binding: str, model: str, step: str) -> str | RowFailure:
    """A bound call's iterate row, proven by the call's recorded outcome and attempt fact.

    Returns the recorded reply (its bytes, not url4's re-encoding) for an answered call, or the
    failure: the fact's origin code when an HTTP attempt was made (a Gateway refusal is
    `aigateway_http_<status>`), else the recorded code, bounded (C11), and the permanence.

    INVARIANT (C11): an answer row is the reply even when shaped like an error row, so a model
    cannot forge a failure; a failure row needs its recorded failure, so no row can forge one.
    """
    outcome = _outcome(binding, step)
    if (
        outcome is None
        or outcome.status == "cancelled"
        or decode_route_id(outcome.path.removeprefix("/")) != model
    ):
        raise benchmark_contract_error(
            f"router {step}: a row with no call of its binding and Model"
        )
    fact = latest_attempt_fact(binding)
    if outcome.status == "answered":
        if not _answered_fact(binding) or url4_row(outcome.output) != row:
            raise benchmark_contract_error(f"router {step}: an answer row is not its call's reply")
        return outcome.output
    recorded = RowFailure(bounded_code(outcome.code), permanent=outcome.permanent is not False)
    if read_error_row(row) != recorded or (fact is not None and fact.status != "failed"):
        raise benchmark_contract_error(f"router {step}: a failure row is not its call's failure")
    code = recorded.code if fact is None or fact.code is None else bounded_code(fact.code)
    return RowFailure(code, recorded.permanent)


def url4_row(output: str) -> str:
    """The row text a reply becomes once url4 collects it and `read_rows` reads it back.

    WHY: url4 embeds a visibly structured row (``[``/``{`` that parses) as a JSON value
    (`_rows_to_json`, `_maybe_json`), so its text comes back re-encoded; prose stays itself.
    """
    value: Any = output
    if output[:1] in ("[", "{"):
        try:
            value = json.loads(output)
        except (ValueError, RecursionError):
            value = output
    return read_rows(json.dumps([value]), "row")[0]


def _outcome(binding: str, step: str) -> CallOutcome | None:
    try:
        return call_outcome(binding)
    except ProvenanceConflict:
        raise benchmark_contract_error(f"router {step}: a bound call ended twice") from None


def _answered_fact(binding: str) -> bool:
    fact = latest_attempt_fact(binding)
    return fact is not None and fact.status == "answered"


def _typed(step: Step, binding: str | None, document: object) -> object | None:
    """The typed value ``step`` recorded for ``binding``, when ``document`` is its document.

    INVARIANT: canonical equality precedes the typed value (`step_payload`); outside a scope
    (whose channel `step_payload` cannot see), or for a document recorded without its value,
    there is none and the caller reads the document itself.
    """
    return None if binding is None else step_payload(step, binding, canonical_document(document))


def _draft_document(value: object) -> dict[str, object] | None:
    """A draft context's strict JSON object, or None when `read_draft` would refuse it."""
    if not isinstance(value, str) or utf8_exceeds(value, MAX_ROUTER_CONTEXT_BYTES):
        return None
    try:
        document = strict_json(value)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def _recorded(step: Step, binding: str, value: object) -> bool:
    recorded = recorded_step(step, binding)
    return recorded is not None and _canonical(value) == recorded


def _same_document(value: object, recorded: str) -> bool:
    """Equal strict JSON values (canonical text), or equal text when either is not strict JSON."""
    if not isinstance(value, str):
        return False
    try:
        return canonical_document(strict_json(value)) == canonical_document(strict_json(recorded))
    except ValueError:
        return value == recorded


def _canonical(value: object) -> str | None:
    try:
        return canonical_document(strict_json(value)) if isinstance(value, str) else None
    except ValueError:
        return None


__all__ = [
    "bound_row",
    "first_run",
    "proven_admit",
    "proven_classification",
    "proven_draft",
    "remember",
    "url4_row",
]
