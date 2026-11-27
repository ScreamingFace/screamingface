"""Router ADMIT and the scoring CLASSIFY step (contracts C2, C4, C7, C8, C11; Unit 5.2).

FEATURE: Router Recipe extension. ADMIT validates the C2 envelope and runs the occurrence's
metadata preflight through the shared routing core (`routing_core.preflight`, the one the named
profiles use) for every model-bearing role: the scoring classifier's visibility, input capability
and limits, then the LLMClassifier Model, every candidate and the default, each by its canonical
route, Connection, whole parameter contract and an executable route in this world. Every step that
can reach a provider depends on ADMIT in the url4 graph, so a refusal runs nothing of the Router.

STORY: as a Router author, a definition my world cannot run fails at ADMIT with one bounded code,
before any classifier or Model is paid, and the record says so.

INVARIANT: failures travel as data until JOIN (C4). ADMIT returns a refusal document; CLASSIFY
returns the classifier's failure document. Only a malformed step context, a control-plane ending
and a run-file admission refusal raise.
WHY the profile's preflight codes: the refusals are the shared preflight's, and C11 adds no
Router code for them; a Case reads each undeclared Engine code as `upstream_error`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace

import httpx

from screamingface_engine.benchmarks.failure_classes import benchmark_contract_error
from screamingface_engine.operation_calls import (
    current_operation_calls,
    operation_call_identity,
    record_operation_call,
)
from screamingface_engine.operation_provenance import CallOutcome, ended, record_call_outcome
from screamingface_engine.request_scope import current_scope
from screamingface_engine.router_vocabulary import RouterPolicy, strict_json
from screamingface_engine.world.classifier_limits import ChoiceRequest, TextRequest, choice_input
from screamingface_engine.world.gateway_transport import _headers
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.router_evidence import bounded_code
from screamingface_engine.world.router_provenance import first_run, proven_admit, remember
from screamingface_engine.world.router_spec import (
    DEFINITION_INVALID,
    ROUTER_UNSUPPORTED,
    ChoiceScoring,
    Definition,
    DescribedCandidate,
    FixedScoring,
    LlmSelector,
    ModelRef,
    ModelSynthesizer,
    RouterSpec,
    RouterSpecError,
    parse_router_spec,
)
from screamingface_engine.world.router_steps import (
    NOT_RUN,
    ROUTER_CLASSIFY_ROUTE,
    Accepted,
    Carried,
    StepCall,
    accepted_document,
    failed_document,
    no_params,
    read_input,
    refused_document,
    step_binding,
)
from screamingface_engine.world.routing import (
    ROUTING_CONNECTION_MISSING,
    ROUTING_PREFLIGHT_FAILED,
    ROUTING_PREFLIGHT_UNAVAILABLE,
    ROUTING_PROFILE_MISMATCH,
    ROUTING_PROFILE_NOT_FOUND,
)
from screamingface_engine.world.routing_core import (
    ClassifierTarget,
    ModelTarget,
    PreflightRefusal,
    Refusal,
    preflight,
)

Classify = Callable[[str, str | Mapping[str, object], str], Awaitable[str]]
"""The classification port: (classifier ID, scalar or C7 choice input, binding) to its JSON."""

_PREFLIGHT_CODES: Mapping[Refusal, str] = {
    "not_found": ROUTING_PROFILE_NOT_FOUND,
    "connection_missing": ROUTING_CONNECTION_MISSING,
    "unavailable": ROUTING_PREFLIGHT_UNAVAILABLE,
    "failed": ROUTING_PREFLIGHT_FAILED,
    "mismatch": ROUTING_PROFILE_MISMATCH,
}


class ClassifyFailure(Exception):
    """The classification port refused or failed the call: its bounded code and permanence.

    The adapter raises it for every failure of the call itself; a control-plane ending is never
    one and propagates unchanged.
    """

    def __init__(self, code: str, *, permanent: bool) -> None:
        super().__init__(code)
        self.code = code
        self.permanent = permanent


@dataclass(frozen=True, slots=True)
class RouterPorts:
    """What the Router's I/O steps reach: the world's Gateway client, its routes, its classifier."""

    client: httpx.AsyncClient
    models: frozenset[str]
    """Every chat route this world executes, by canonical Gateway Model ID (`canonical_models`)."""
    classify: Classify


def canonical_models(routes: Iterable[str]) -> frozenset[str]:
    """The canonical Gateway Model IDs of a world's url4 chat routes (``"/" + route id``).

    INVARIANT (C2, C5; OME-873): a C2 ``Model.model`` is the canonical ID (``:``, never the
    route's ``~`` escape), so an occurrence is checked, read and recorded by that one form.
    """
    return frozenset(decode_route_id(route.removeprefix("/")) for route in routes)


class _Refused(Exception):
    def __init__(self, code: str, *, permanent: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.permanent = permanent


async def admit(ports: RouterPorts, call: StepCall, files: Callable[[], Awaitable[None]]) -> str:
    """ADMIT: the accepted document, an ADMIT refusal, or the input failure carried forward.

    ``files`` awaits this run's shared OME-1809 file admission (a no-op without files).

    Raises:
        ResolutionError: `benchmark_contract_error` for a malformed step, or the run-file
            admission's own refusal, unchanged (a run refusal publishes no record).
    """
    router = step_binding(call.params, "admit")
    # INVARIANT: one ADMIT per occurrence and scope, claimed before the first await so a
    # parallel duplicate reads nothing; every result it returns is the recorded one later steps
    # prove their context against.
    first_run("admit", router)
    question = read_input(call.context)
    if isinstance(question, Carried):
        # INVARIANT (C4): an input failure takes precedence and reads nothing.
        failed = failed_document(question.code, question.permanent)
        return remember("admit", router, failed, question)
    try:
        admitted = _admitted(call.intent, router)
        await _checked(ports, admitted, question)
    except _Refused as refusal:
        refused = refused_document(refusal.code, refusal.permanent)
        return remember("admit", router, refused, Carried("admit", refusal.code, refusal.permanent))
    # WHY after the preflight: the scoring CLASSIFY, the selector and every branch depend on this
    # document, so none reaches a provider before the run's files are admitted.
    await files()
    accepted = accepted_document(question, strict_json(call.intent))
    return remember("admit", router, accepted, Accepted(question, admitted))


def _admitted(intent: str, router: str) -> RouterSpec:
    """The validated envelope of this occurrence, or a refusal before any read."""
    if current_operation_calls() is None:
        # INVARIANT (C4): a Router never runs model I/O where its record would be lost.
        raise _Refused(ROUTER_UNSUPPORTED)
    try:
        admitted = parse_router_spec(intent)
    except RouterSpecError:
        raise _Refused(DEFINITION_INVALID) from None
    if admitted.router != router:
        raise _Refused(DEFINITION_INVALID)
    if not isinstance(admitted.definition.policy, RouterPolicy):
        raise _Refused(ROUTER_UNSUPPORTED)
    # WHY a subset is admitted (C4): its preflight and pure decision are 5.2's; only its
    # panel executes in Unit 6, so OPEN and JOIN refuse a selected subset (C4).
    return admitted


async def _checked(ports: RouterPorts, admitted: RouterSpec, question: str) -> None:
    definition = admitted.definition
    scope = current_scope()
    scoring = isinstance(definition.classifier, FixedScoring | ChoiceScoring)
    if scoring and (scope.capture or scope.replay_frozen_copy is not None):
        # WHY: storing and replaying a Router's classification is C9 (Unit 6); a classification
        # neither stored nor replayed would be a paid call outside the frozen copy.
        raise _Refused(ROUTER_UNSUPPORTED)
    models = _models(definition)
    if any(ref.model not in ports.models for ref in models):
        # INVARIANT: decided from the world's own routes, before any read; a route form
        # (``~``) is no canonical ID and is refused like an unknown Model.
        raise _Refused(ROUTING_PROFILE_NOT_FOUND)
    targets = [ModelTarget(ref.model, params=tuple(sorted(ref.params.items()))) for ref in models]
    try:
        await preflight(ports.client, _headers(scope), _classifier(definition, question), targets)
    except PreflightRefusal as refusal:
        raise _Refused(_PREFLIGHT_CODES[refusal.kind], permanent=refusal.permanent) from None


def _models(definition: Definition) -> list[ModelRef]:
    """Every Model the occurrence can call, in role order: selector, candidates, default and
    a Model synthesizer (C4: every model-bearing role is preflighted)."""
    selector, synthesizer = definition.classifier, definition.synthesizer
    models = [selector.model] if isinstance(selector, LlmSelector) else []
    models.extend(candidate.model for candidate in definition.candidates)
    if definition.default is not None:
        models.append(definition.default)
    if isinstance(synthesizer, ModelSynthesizer):
        models.append(synthesizer.model)
    return models


def _classifier(definition: Definition, question: str) -> ClassifierTarget | None:
    classifier = definition.classifier
    if isinstance(classifier, FixedScoring):
        request = TextRequest(labels=definition.labels, text=question)
        return ClassifierTarget(classifier.model, classifier.contract, text=request)
    if isinstance(classifier, ChoiceScoring):
        choice = _choice(definition, classifier, question)
        return ClassifierTarget(classifier.model, classifier.contract, choice=choice)
    return None


def _choice(definition: Definition, classifier: ChoiceScoring, question: str) -> ChoiceRequest:
    # INVARIANT (C2): every candidate of a choice classifier carries its description.
    return ChoiceRequest(
        labels=definition.labels,
        descriptions=tuple(
            candidate.description
            for candidate in definition.candidates
            if isinstance(candidate, DescribedCandidate)
        ),
        instructions=classifier.instructions,
        text=question,
    )


async def classify(ports: RouterPorts, call: StepCall) -> str:
    """The scoring CLASSIFY: the classification JSON, its failure, or ``NOT_RUN``.

    INVARIANT (C8): one port call with the admitted question, recorded as the occurrence's
    classify operation (binding ``router_N``); its attempt fact is the port's.
    INVARIANT: a failed classification is that operation too, with unknown accounting,
    so the budget fold counts it unpriced and JOIN can prove the failure DECIDE read.
    """
    no_params(call, "classify")
    # INVARIANT: only the recorded ADMIT result of its router reaches the port.
    admission = proven_admit(call.context, "classify")
    if isinstance(admission, Carried):
        return NOT_RUN
    definition, router = admission.admitted.definition, admission.admitted.router
    # INVARIANT: one classification per occurrence, claimed before the port is reached, so a
    # replayed or parallel CLASSIFY of one ADMIT result pays for nothing.
    first_run("classify", router)
    classifier = definition.classifier
    if isinstance(classifier, FixedScoring):
        value: str | Mapping[str, object] = admission.question
    elif isinstance(classifier, ChoiceScoring):
        value = choice_input(_choice(definition, classifier, admission.question))
    else:
        raise benchmark_contract_error("router classify reads a scoring classifier")
    with operation_call_identity(ROUTER_CLASSIFY_ROUTE, {"binding": router}):
        result = await _classified(ports, classifier.model, value, router)
        record_operation_call(result, None)
    return result


async def _classified(
    ports: RouterPorts, model: str, value: str | Mapping[str, object], router: str
) -> str:
    """The port's classification, or its failure document, recorded as the call's outcome (C8)."""
    try:
        result = await ports.classify(model, value, router)
    except ClassifyFailure as failure:
        # INVARIANT (C11): a Router code never comes from a classifier.
        code = bounded_code(failure.code)
        result = failed_document(code, failure.permanent)
        outcome = CallOutcome(router, ROUTER_CLASSIFY_ROUTE, "failed", result, code)
        record_call_outcome(replace(outcome, permanent=failure.permanent))
        return result
    except (Exception, asyncio.CancelledError) as ending:
        # WHY: a control-plane ending propagates unchanged; its outcome says how it ended.
        record_call_outcome(ended(router, ROUTER_CLASSIFY_ROUTE, ending))
        raise
    record_call_outcome(CallOutcome(router, ROUTER_CLASSIFY_ROUTE, "answered", result))
    return result


__all__ = ["Classify", "ClassifyFailure", "RouterPorts", "admit", "canonical_models", "classify"]
