"""Router DECIDE and OPEN (contracts C4, C5, C6; Unit 5.2).

FEATURE: Router Recipe extension. DECIDE reads ADMIT's result and the classifier's output, turns
it into C6 evidence (`router_evidence`), applies the pure policy (`routing_policy.decide`) and
returns the internal C5 draft. OPEN reads ADMIT's result (``classify``) or the draft (``c<K>``,
``default``) and returns ``[{}]`` only for the branch the occurrence takes, as E4c OPEN does.

STORY: as a Router author, an unselected candidate, an unselected default and a refused
occurrence's selector make zero calls, and the record says what was decided and why.

INVARIANT: pure given the context and this Case's recorded provenance: no model call, no clock.
DECIDE never raises for a Router outcome: a classifier failure fails at ``classify``, unreadable
evidence at ``decide`` with `router_evidence_invalid`. Only a malformed step context, or one this
occurrence did not record (`router_provenance`), raises.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypeGuard

from screamingface_engine.benchmarks.failure_classes import benchmark_contract_error
from screamingface_engine.router_decision import (
    DRAFT_SCHEMA,
    REVISION_SCHEME,
    RouterDecisionError,
    parse_router_draft,
)
from screamingface_engine.router_vocabulary import RouterPolicy, strict_json
from screamingface_engine.world.router_evidence import (
    RowFailure,
    bounded_code,
    read_keywords,
    read_llm_reply,
)
from screamingface_engine.world.router_keywords import keyword_labels
from screamingface_engine.world.router_provenance import (
    bound_row,
    first_run,
    proven_admit,
    proven_classification,
    proven_draft,
    remember,
)
from screamingface_engine.world.router_spec import (
    SCORES_CONTRACT,
    AdmittedSpec,
    ChoiceScoring,
    FixedScoring,
    LlmSelector,
    RegexSelector,
)
from screamingface_engine.world.router_steps import (
    NOT_RUN,
    Accepted,
    Carried,
    StepCall,
    check_keys,
    compact_json,
    read_rows,
    step_binding,
    step_object,
)
from screamingface_engine.world.routing_policy import (
    ROUTER_EVIDENCE_INVALID,
    ClassifierFailure,
    Evidence,
    PolicyResult,
    PolicyRule,
    ScoringEvidence,
)
from screamingface_engine.world.routing_policy import (
    decide as apply_policy,
)

_DECIDE_KEYS = frozenset({"admit", "evidence"})
_CLASSIFICATION_KEYS = frozenset({"object", "model", "contract", "scores"})
_SCORE_KEYS = frozenset({"label", "score"})
_FAILURE_KEYS = frozenset({"code", "permanent"})
_CANDIDATE_SLOT = re.compile(r"c(0|[1-9][0-9]*)")
_OPEN = "[{}]"
_CLOSED = "[]"
_FAILED: Mapping[str, object] = {
    "outcome": "failed",
    "reason": None,
    "selected": [],
    "unknown_labels": [],
}


def candidate_slot(name: str) -> int | None:
    """The candidate index an OPEN intent or a JOIN key ``c<K>`` names, or None."""
    match = _CANDIDATE_SLOT.fullmatch(name)
    return None if match is None else int(match.group(1))


# --- OPEN -----------------------------------------------------------------------------------------


def open_branch(call: StepCall) -> str:
    """``[{}]`` iff the occurrence takes the intent's branch, else ``[]`` (C4).

    ``classify`` opens a selector's call when ADMIT accepted; ``c<K>`` and ``default`` open the
    branch the draft chose. ``panel`` never opens here: a selected subset (``select="all"``) runs
    its panel in Unit 6, so OPEN refuses it rather than open any of its members.
    """
    if call.params:
        raise benchmark_contract_error("router open takes no param")
    if call.intent == "classify":
        return _open_selector(call.context)
    return _open_body(call.intent, call.context)


def _open_selector(context: str) -> str:
    admission = proven_admit(context, "open")
    if isinstance(admission, Carried):
        return _CLOSED
    if isinstance(admission.admitted.definition.classifier, FixedScoring | ChoiceScoring):
        raise benchmark_contract_error("router open classify gates a selector")
    return _OPEN


def _open_body(intent: str, context: str) -> str:
    index = candidate_slot(intent)
    if index is None and intent not in ("default", "panel"):
        raise benchmark_contract_error("router open intent is classify, c<K>, default or panel")
    # INVARIANT: only the draft DECIDE recorded for its router opens a branch.
    draft = proven_draft(context, "open")
    subset = draft.policy is not None and draft.policy.select == "all"
    if draft.outcome == "selected" and (intent == "panel" or subset):
        # WHY (C4): a selected subset runs its panel in Unit 6; 5.2 opens none.
        raise benchmark_contract_error("router open: a selected subset's panel is not run here")
    taken = (
        draft.outcome == "default"
        if index is None
        else draft.outcome == "selected" and index in draft.selected
    )
    return _OPEN if taken and intent != "panel" else _CLOSED


# --- DECIDE ---------------------------------------------------------------------------------------


def decide(call: StepCall) -> str:
    """The C5 draft: the C6 decision over the classifier's output, or where it failed."""
    router = step_binding(call.params, "decide")
    if call.intent:
        raise benchmark_contract_error("router decide takes no intent")
    # INVARIANT: one DECIDE per occurrence and scope, over the recorded ADMIT result
    # and the recorded classifier outcome; its draft is recorded for OPEN and JOIN.
    first_run("decide", router)
    context = step_object(call.context, "decide")
    check_keys(context, _DECIDE_KEYS, _DECIDE_KEYS, "decide")
    admission = proven_admit(context["admit"], "decide", router)
    evidence = context["evidence"]
    if isinstance(admission, Carried):
        return remember("decide", router, _carried(router, admission, evidence))
    admitted = admission.admitted
    read = _evidence(admission, evidence)
    if read is None:
        return remember("decide", router, _invalid(router, admitted))
    result = apply_policy(
        _rule(admitted),
        read,
        labels=admitted.definition.labels,
        has_default=admitted.definition.default is not None,
    )
    return remember("decide", router, _decided(router, admitted, read, result))


def _carried(router: str, admission: Carried, evidence: object) -> str:
    """The failed draft of an occurrence ADMIT did not accept: nothing ran after it."""
    if evidence not in (NOT_RUN, _CLOSED):
        raise benchmark_contract_error("router decide: an unadmitted occurrence ran a classifier")
    failure = {"phase": admission.phase, "code": admission.code, "permanent": admission.permanent}
    return _draft(router, None, _FAILED, None, failure)


def _rule(admitted: AdmittedSpec) -> PolicyRule:
    policy = admitted.definition.policy
    if not isinstance(policy, RouterPolicy):
        # INVARIANT: a router spec carries a router-policy (`router_spec.RouterSpec`).
        raise benchmark_contract_error("router decide reads a router-policy")
    return PolicyRule(kind="router-policy", match=policy.match, select=policy.select)


def _evidence(admission: Accepted, evidence: object) -> Evidence | None:
    """The classifier's output as C6 evidence, or None when it is not evidence at all."""
    if evidence == NOT_RUN:
        return None  # WHY (C4): ``not_run`` beside an accepted ADMIT is invalid evidence.
    admitted = admission.admitted
    classifier = admitted.definition.classifier
    if isinstance(classifier, FixedScoring | ChoiceScoring):
        # INVARIANT (C4): the scores are the recorded classification's, read from the record.
        outcome = proven_classification(evidence, admitted.router)
        return _scoring(outcome.output, classifier.model)
    return _selector(admission, classifier, _one_row(evidence))


def _selector(admission: Accepted, classifier: LlmSelector | RegexSelector, row: str) -> Evidence:
    if isinstance(classifier, RegexSelector):
        return _regex(row, classifier, admission.question)
    binding = admission.admitted.calls.classifier
    if binding is None:
        raise benchmark_contract_error("router decide: an llm selector without its call binding")
    read = bound_row(row, binding, classifier.model.model, "decide")
    # INVARIANT (C11): the selector's recorded outcome and attempt fact decide its row.
    if isinstance(read, RowFailure):
        return ClassifierFailure(read.code, read.permanent)
    return read_llm_reply(read, classifier.labels, multi=classifier.multi)


def _regex(row: str, classifier: RegexSelector, question: str) -> Evidence:
    """The KEYWORDS labels, when they are the ones KEYWORDS gives the admitted question.

    INVARIANT (C4): KEYWORDS is pure (`router_keywords`), so its row is recomputed rather
    than trusted; an error row or other labels cannot come from it.
    """
    labels = tuple(rule.label for rule in classifier.rules)
    found = read_keywords(row, labels, multi=classifier.multi)
    if found.labels != keyword_labels(classifier, question):
        raise benchmark_contract_error("router decide keywords are not the question's keywords")
    return found


def _one_row(evidence: object) -> str:
    rows = read_rows(evidence, "decide evidence")
    if len(rows) != 1:
        # WHY a contract error: OPEN opened the selector, so a missing or extra row is lost
        # execution state, not a classifier outcome.
        raise benchmark_contract_error("router decide evidence holds the selector's one row")
    return rows[0]


def _scoring(evidence: object, model: str) -> Evidence | None:
    """The scoring CLASSIFY result: its scores, its failure, or None when it is neither."""
    document = _json_object(evidence)
    if document is not None and set(document) == {"failed"}:
        failure = document["failed"]
        # INVARIANT (C11): a Router code never comes from a classifier.
        return (
            ClassifierFailure(bounded_code(failure["code"]), failure["permanent"])
            if _failure_shape(failure)
            else None
        )
    if document is None or not _classification(document, model):
        return None
    return ScoringEvidence(
        model, SCORES_CONTRACT, [(row["label"], row["score"]) for row in document["scores"]]
    )


def _json_object(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        document = strict_json(value)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def _classification(document: dict[str, Any], model: str) -> bool:
    """Exactly the classification document of this occurrence's classifier (C7)."""
    scores = document.get("scores")
    return (
        set(document) == _CLASSIFICATION_KEYS
        and document["object"] == "classification"
        and document["model"] == model
        and document["contract"] == SCORES_CONTRACT
        and isinstance(scores, list)
        and all(isinstance(row, dict) and set(row) == _SCORE_KEYS for row in scores)
    )


def _failure_shape(value: object) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(value, dict)
        and set(value) == _FAILURE_KEYS
        and isinstance(value["code"], str)
        and isinstance(value["permanent"], bool)
    )


def _decided(router: str, admitted: AdmittedSpec, evidence: Evidence, result: PolicyResult) -> str:
    if result.failure is not None:
        failure = result.failure
        document = {"phase": failure.phase, "code": failure.code, "permanent": failure.permanent}
        return _draft(router, admitted, _FAILED, None, document)
    decision = {
        "outcome": result.outcome,
        "reason": result.reason,
        "selected": list(result.selected),
        "unknown_labels": list(result.unknown_labels),
    }
    try:
        return _draft(router, admitted, decision, _record(evidence), None)
    except RouterDecisionError:
        # WHY: evidence the policy read but the record cannot hold (a returned label over the
        # label bound, say) is invalid evidence, never a coerced record.
        return _invalid(router, admitted)


def _record(evidence: Evidence) -> Mapping[str, object]:
    """The C5 evidence form a successful draft keeps."""
    if isinstance(evidence, ScoringEvidence):
        return {
            "source": "scoring",
            "model": evidence.model,
            "contract": evidence.contract,
            "scores": [{"label": label, "score": score} for label, score in evidence.scores],
        }
    if isinstance(evidence, ClassifierFailure):
        raise benchmark_contract_error("router decide keeps no evidence of a failure")
    return {
        "source": evidence.source,
        "labels": list(evidence.labels),
        "unknown": list(evidence.unknown),
        "parse": evidence.parse,
    }


def _invalid(router: str, admitted: AdmittedSpec) -> str:
    failure = {"phase": "decide", "code": ROUTER_EVIDENCE_INVALID, "permanent": True}
    return _draft(router, admitted, _FAILED, None, failure)


def _draft(
    router: str,
    admitted: AdmittedSpec | None,
    decision: Mapping[str, object],
    evidence: Mapping[str, object] | None,
    failure: Mapping[str, object] | None,
) -> str:
    """One draft, validated by the reader OPEN and JOIN use (`parse_router_draft`)."""
    document: dict[str, object] = {
        "schema": DRAFT_SCHEMA,
        "router": router,
        "revision": None if admitted is None else admitted.revision,
        "revision_scheme": None if admitted is None else REVISION_SCHEME,
        "policy": None if admitted is None else admitted.definition_json["policy"],
        "evidence": None if evidence is None else dict(evidence),
        **decision,
    }
    if failure is not None:
        document["failure"] = dict(failure)
    text = compact_json(document)
    parse_router_draft(text)
    return text


__all__ = ["candidate_slot", "decide", "open_branch"]
