"""The `/route-answer` world endpoint: classify, select one branch, answer (OME-1822).

FEATURE: BYOM routing pilot (spec 3.2 to 3.5). A caller names a routing profile of the declared
world and sends one question. One direct run reads the published metadata of the profile's
classifier and branches, classifies the question once through Unit 3's `ClassificationEndpoint`,
takes the unique highest label (`unique-argmax-v1`) and asks that label's chat route once, with
the unchanged question.

WHY no url4 import: `tests/unit/test_url4_executor.py` pins which modules may import the url4
engine. The handler raises `RunnerRequestError` with a stable code, and the branch call arrives
as a callable from `world.factory`, already on that list, which also turns the error into url4's
`ResolutionError`, as for `/classify`.

INVARIANT: nothing reaches a branch unless every target was visible and connected, the scores
name exactly the profile's labels and one label holds the highest score. No other branch is ever
tried and no step is retried here.

INVARIANT: no refusal names a model ID, an origin or a path. Unknown and ungranted profiles
answer one message.

FEATURE: Router Recipe extension, Unit 5.2 (contracts C2, C4, C6). This is the named-profile
adapter over the shared routing core: the metadata preflight is `routing_core.preflight`, the
selection is the pure C6 `unique-argmax-v1` policy, and a dynamic-choice profile sends the C7
choice input with its options in branch order. The wire, codes and messages stay this module's.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NoReturn

import httpx

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    parse_candidate_input,
)
from screamingface_engine.request_scope import RequestScope, current_scope
from screamingface_engine.world.attempt_facts import direct_attempts, direct_role
from screamingface_engine.world.classification import (
    CLASSIFIER_NOT_FOUND,
    MALFORMED_SOURCE,
    ClassificationEndpoint,
    _unique_pairs,
)
from screamingface_engine.world.classifier_limits import ChoiceRequest, choice_input
from screamingface_engine.world.connector import AigatewayConfig
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.fusion_context import fusion_picture_messages
from screamingface_engine.world.gateway_transport import _headers
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.routing_config import RoutingBranch, RoutingProfile
from screamingface_engine.world.routing_core import (
    ClassifierTarget,
    ModelTarget,
    PreflightRefusal,
    preflight,
)
from screamingface_engine.world.routing_policy import (
    ROUTING_AMBIGUOUS,
    ROUTING_INVALID_SCORES,
    PolicyRule,
    ScoringEvidence,
    decide,
)

ROUTE_ANSWER_ROUTE = "/route-answer"
ROUTE_ANSWER_INTENT = "route-answer"
RESULT_CONTRACT = "routed-answer-v1"

ROUTING_UNSUPPORTED = "routing_unsupported"
ROUTING_PROFILE_NOT_FOUND = "routing_profile_not_found"
ROUTING_CONNECTION_MISSING = "routing_connection_missing"
ROUTING_PREFLIGHT_UNAVAILABLE = "routing_preflight_unavailable"
ROUTING_PREFLIGHT_FAILED = "routing_preflight_failed"
ROUTING_PROFILE_MISMATCH = "routing_profile_mismatch"

ROUTING_STATUS: dict[str, int] = {
    ROUTING_UNSUPPORTED: 400,
    ROUTING_PROFILE_NOT_FOUND: 404,
    ROUTING_CONNECTION_MISSING: 409,
    # WHY listed although `502` is the default for a permanent Engine code: the transient
    # preflight code would otherwise take url4's transient default, not the spec's status.
    ROUTING_PREFLIGHT_UNAVAILABLE: 502,
    ROUTING_PREFLIGHT_FAILED: 502,
    ROUTING_PROFILE_MISMATCH: 502,
    ROUTING_INVALID_SCORES: 502,
    ROUTING_AMBIGUOUS: 422,
}
"""The mount status of every routing code (spec 3.5)."""

ROUTED_MALFORMED_MESSAGE = (
    'a routed answer takes q=({"profile": <string>, "input": <non-empty text>})!route-answer '
    "and no parameters; the input is a plain prompt, not a message envelope"
)
_NOT_FOUND_MESSAGE = "no routing profile with this ID is available to the caller"
_UNIQUE_ARGMAX = PolicyRule(kind="unique-argmax-v1")

# The profile's message for each policy refusal (spec 3.5), unchanged by the shared policy.
_POLICY_MESSAGES = {
    ROUTING_INVALID_SCORES: "the classifier's labels are not the labels this routing profile binds",
    ROUTING_AMBIGUOUS: "more than one label holds the highest score, so no branch was asked",
}

Branch = Callable[[RoutingBranch, str], Awaitable[str]]
"""Ask one branch's chat route the question; supplied by `world.factory`."""


class RoutedAnswerEndpoint:
    """One handler for every profile: the profile ID travels in the request, not in the route.

    Built once per world on the world's own Gateway client, so every read and call of a run
    carries the same identity and trace as the chat calls.
    """

    __slots__ = ("_branch", "_classify", "_http_client", "_profiles")

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        cfg: AigatewayConfig,
        profiles: Mapping[str, RoutingProfile],
        branch: Branch,
    ) -> None:
        self._http_client = http_client
        self._classify = ClassificationEndpoint(http_client, cfg)
        self._profiles = profiles
        self._branch = branch

    async def __call__(self, context: str, intent: str, params: Mapping[str, str]) -> str:
        """Run spec 3.3 steps 1 to 9 and return the `routed-answer-v1` document.

        Raises:
            RunnerRequestError: a routing code of spec 3.5 or `malformed_source`.
            ResolutionError: a classifier or branch failure, as raised; the mount's relay
                (`gateway_endpoints._relayed`) applies spec 3.5 and 6.1 C9 to it.
        """
        scope = current_scope()
        # INVARIANT: the mode refusal comes first, so a seeded, capture or replay run never
        # reaches the Gateway, whatever its envelope holds.
        _refuse_mode(scope)
        profile_id, text = _envelope(context, intent, params)
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise not_found()
        # FEATURE (C8): this invocation's private attempt scope, closed however it ends.
        with direct_attempts():
            return await self._route(profile, text, scope)

    async def _route(self, profile: RoutingProfile, text: str, scope: RequestScope) -> str:
        await _preflight(self._http_client, _headers(scope), profile, text)
        try:
            with direct_role("classifier"):
                result = await self._classify.classify(profile.classifier, _input(profile, text))
        except RunnerRequestError as exc:
            if exc.code != CLASSIFIER_NOT_FOUND:
                raise
            # WHY one code: access can change after the preflight, and the caller must not learn
            # which target of the profile it lost.
            raise not_found() from None
        scores, choice = _select(profile, json.loads(result)["scores"])
        with direct_role("branch"):
            answer = await self._branch(choice, text)
        return json.dumps(
            {
                "object": "routed_answer",
                "contract": RESULT_CONTRACT,
                "profile": profile.id,
                "revision": profile.revision,
                "policy": profile.policy,
                "classification": {
                    "model": profile.classifier,
                    "contract": profile.classifier_contract,
                    "scores": scores,
                },
                "selected": {"label": choice.label, "model": decode_route_id(choice.model)},
                "answer": answer,
            },
            ensure_ascii=False,
            allow_nan=False,
        )


def _refuse_mode(scope: RequestScope) -> None:
    # WHY `is not None`: a seed of 0 is a seed.
    if scope.answer_seed is not None:
        raise _unsupported("a routed answer takes no answer seed; send it without X-Answer-Seed")
    if scope.capture:
        raise _unsupported("a routed answer cannot run in a capture run; it stores no answer")
    if scope.replay_frozen_copy is not None:
        raise _unsupported("a routed answer cannot run in a replay run; no copy holds one")


def _envelope(context: str, intent: str, params: Mapping[str, str]) -> tuple[str, str]:
    """The profile ID and the input, from the exact two-field context (spec 3.2)."""
    if intent != ROUTE_ANSWER_INTENT or params:
        raise _malformed()
    try:
        document = json.loads(context, object_pairs_hook=_unique_pairs)
    except (ValueError, RecursionError):
        raise _malformed() from None
    if not isinstance(document, dict) or set(document) != {"profile", "input"}:
        raise _malformed()
    profile_id, text = document["profile"], document["input"]
    if not (isinstance(profile_id, str) and isinstance(text, str) and text):
        raise _malformed()
    try:
        profile_id.encode("utf-8")
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise _malformed() from None
    if not _plain_prompt(text):
        raise _malformed()
    return profile_id, text


def _plain_prompt(text: str) -> bool:
    """Whether the chat route sends ``text`` as written, as the one user message.

    WHY both readers: they are the two the chat route applies (`connector._native_messages`). An
    input either opens into other messages would ask the branch something other than the
    caller's text, after the classifier had read that text.
    """
    try:
        return parse_candidate_input(text) is None and fusion_picture_messages(text) is None
    except CandidateInputError:
        return False


async def _preflight(
    client: httpx.AsyncClient, headers: dict[str, str], profile: RoutingProfile, text: str
) -> None:
    """Read the classifier's details and each branch's parameters; no inference (step 4)."""
    choice = _choice(profile, text) if profile.dynamic else None
    try:
        await preflight(
            client,
            headers,
            ClassifierTarget(profile.classifier, profile.classifier_contract, choice),
            [ModelTarget(decode_route_id(b.model), b.max_tokens) for b in profile.branches],
        )
    except PreflightRefusal as refusal:
        _refuse(refusal)


def _refuse(refusal: PreflightRefusal) -> NoReturn:
    """The profile's presentation of a shared preflight refusal (spec 3.5)."""
    if refusal.kind == "not_found":
        raise not_found() from None
    if refusal.kind == "unavailable":
        raise _unavailable() from None
    errors = {
        "connection_missing": (
            "a model this routing profile uses has no usable Connection for the caller",
            ROUTING_CONNECTION_MISSING,
        ),
        "mismatch": (
            "this routing profile does not fit the published contract of a model it uses; "
            "nothing was sent to a model",
            ROUTING_PROFILE_MISMATCH,
        ),
    }
    if refusal.kind in errors:
        raise _routing_error(*errors[refusal.kind]) from None
    raise _failed() from None


def _choice(profile: RoutingProfile, text: str) -> ChoiceRequest:
    """The counts and lengths of the dynamic profile's C7 choice input, in branch order."""
    return ChoiceRequest(
        labels=tuple(branch.label for branch in profile.branches),
        descriptions=tuple(branch.description or "" for branch in profile.branches),
        instructions=profile.instructions or "",
        text=text,
    )


def _input(profile: RoutingProfile, text: str) -> str | dict[str, object]:
    """What the classifier reads: the text for a fixed profile, the C7 choice input otherwise.

    INVARIANT (C2): the options follow branch (table) order, the order the revision hashed.
    """
    if not profile.dynamic:
        return text
    return choice_input(_choice(profile, text))


def _select(
    profile: RoutingProfile, scores: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], RoutingBranch]:
    """The scores as decoded and the branch the shared C6 `unique-argmax-v1` policy selects.

    WHY the policy still sees Unit 3's checked scores: Unit 3 refused a result for another
    model or contract, duplicate labels, booleans and scores outside `[0, 1]`; the policy adds
    the label-set and tie rules (steps 6 and 7) and never reorders.
    """
    evidence = ScoringEvidence(
        model=profile.classifier,
        contract=profile.classifier_contract,
        scores=[(item["label"], item["score"]) for item in scores],
    )
    labels = [branch.label for branch in profile.branches]
    result = decide(_UNIQUE_ARGMAX, evidence, labels=labels, has_default=False)
    if result.failure is not None:
        raise _routing_error(_POLICY_MESSAGES[result.failure.code], result.failure.code)
    return scores, profile.branches[result.selected[0]]


def not_found() -> RunnerRequestError:
    """The one answer for an unknown profile and for a target the caller may not use."""
    return _routing_error(_NOT_FOUND_MESSAGE, ROUTING_PROFILE_NOT_FOUND)


def _routing_error(message: str, code: str, *, permanent: bool = True) -> RunnerRequestError:
    return RunnerRequestError(message, code=code, permanent=permanent)


def _unsupported(message: str) -> RunnerRequestError:
    return _routing_error(message, ROUTING_UNSUPPORTED)


def _unavailable() -> RunnerRequestError:
    return _routing_error(
        "the Gateway could not be read before routing; nothing was sent to a model",
        ROUTING_PREFLIGHT_UNAVAILABLE,
        permanent=False,
    )


def _failed() -> RunnerRequestError:
    return _routing_error(
        "the Gateway refused or garbled a metadata read before routing; nothing was sent to a "
        "model",
        ROUTING_PREFLIGHT_FAILED,
    )


def _malformed() -> RunnerRequestError:
    return RunnerRequestError(ROUTED_MALFORMED_MESSAGE, code=MALFORMED_SOURCE, permanent=True)


__all__ = [
    "ROUTED_MALFORMED_MESSAGE",
    "ROUTE_ANSWER_INTENT",
    "ROUTE_ANSWER_ROUTE",
    "ROUTING_STATUS",
    "Branch",
    "RoutedAnswerEndpoint",
    "not_found",
]
