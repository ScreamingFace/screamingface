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
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    parse_candidate_input,
)
from screamingface_engine.request_scope import RequestScope, current_scope
from screamingface_engine.world.classification import (
    CLASSIFIER_NOT_FOUND,
    CLASSIFY_INTENT,
    MALFORMED_SOURCE,
    ClassificationEndpoint,
    _unique_pairs,
)
from screamingface_engine.world.connector import AigatewayConfig
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.fusion_context import fusion_picture_messages
from screamingface_engine.world.gateway_transport import _headers
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.routing_config import RoutingBranch, RoutingProfile

ROUTE_ANSWER_ROUTE = "/route-answer"
ROUTE_ANSWER_INTENT = "route-answer"
RESULT_CONTRACT = "routed-answer-v1"
CLASSIFIER_DETAILS_PATH = "/v1/classifiers/details"
MODEL_PARAMETERS_PATH = "/v1/model-parameters"

ROUTING_UNSUPPORTED = "routing_unsupported"
ROUTING_PROFILE_NOT_FOUND = "routing_profile_not_found"
ROUTING_CONNECTION_MISSING = "routing_connection_missing"
ROUTING_PREFLIGHT_UNAVAILABLE = "routing_preflight_unavailable"
ROUTING_PREFLIGHT_FAILED = "routing_preflight_failed"
ROUTING_PROFILE_MISMATCH = "routing_profile_mismatch"
ROUTING_INVALID_SCORES = "routing_invalid_scores"
ROUTING_AMBIGUOUS = "routing_ambiguous"

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

# WHY `auth_required` alone among 401s: it is the Gateway's answer for a visible target whose
# Connection must sign in again; any other 401 says the request itself was not accepted.
_REAUTH_CODE = "auth_required"

# (usable, fits) of a visible target whose Connection cannot run: its contract is unread, so it
# is not held against the profile.
_NOT_CONNECTED = (False, True)

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
        await _preflight(self._http_client, _headers(scope), profile)
        try:
            result = await self._classify(
                json.dumps({"model": profile.classifier, "input": text}), CLASSIFY_INTENT, {}
            )
        except RunnerRequestError as exc:
            if exc.code != CLASSIFIER_NOT_FOUND:
                raise
            # WHY one code: access can change after the preflight, and the caller must not learn
            # which target of the profile it lost.
            raise not_found() from None
        scores, choice = _select(profile, json.loads(result)["scores"])
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
    client: httpx.AsyncClient, headers: dict[str, str], profile: RoutingProfile
) -> None:
    """Read the classifier's details and each branch's parameters; no inference (step 4)."""
    details = await _read(client, headers, CLASSIFIER_DETAILS_PATH, profile.classifier)
    findings = [_NOT_CONNECTED if details is None else _classifier_findings(details, profile)]
    for branch in profile.branches:
        model = decode_route_id(branch.model)
        document = await _read(client, headers, MODEL_PARAMETERS_PATH, model)
        findings.append(
            _NOT_CONNECTED
            if document is None
            else _branch_findings(document, model, branch.max_tokens)
        )
    # INVARIANT: decided only now, once every target was visible, so a caller who cannot see one
    # target learns nothing about the others; a missing Connection is named first.
    if not all(usable for usable, _ in findings):
        raise _routing_error(
            "a model this routing profile uses has no usable Connection for the caller",
            ROUTING_CONNECTION_MISSING,
        )
    if not all(fits for _, fits in findings):
        raise _routing_error(
            "this routing profile does not fit the published contract of a model it uses; "
            "nothing was sent to a model",
            ROUTING_PROFILE_MISMATCH,
        )


def _classifier_findings(details: dict[str, Any], profile: RoutingProfile) -> tuple[bool, bool]:
    """(usable, fits) of the classifier's details document."""
    if details.get("id") != profile.classifier:
        raise _failed()
    access, contract = details.get("execution_access"), details.get("result_contract")
    if not (isinstance(access, str) and isinstance(contract, str)):
        raise _failed()
    return access == "configured", contract == profile.classifier_contract


def _branch_findings(document: dict[str, Any], model: str, max_tokens: int) -> tuple[bool, bool]:
    """(usable, fits) of one branch's parameter document."""
    identity, context, parameters = (
        document.get("model"),
        document.get("context"),
        document.get("parameters"),
    )
    if not (
        isinstance(identity, dict)
        and identity.get("id") == model
        and isinstance(context, dict)
        and isinstance(context.get("execution_access"), str)
        and isinstance(parameters, dict)
    ):
        raise _failed()
    usable = context["execution_access"] == "configured"
    return usable, _admits(parameters.get("max_tokens"), max_tokens)


async def _read(
    client: httpx.AsyncClient, headers: dict[str, str], path: str, model: str
) -> dict[str, Any] | None:
    """One metadata document, or ``None`` for a visible target whose Connection cannot run."""
    try:
        response = await client.get(path, params={"model": model}, headers=headers)
    except httpx.TransportError:
        raise _unavailable() from None
    except httpx.HTTPError:
        raise _failed() from None
    return _document(response)


def _document(response: httpx.Response) -> dict[str, Any] | None:
    status = response.status_code
    if status == 429 or 500 <= status < 600:
        raise _unavailable()
    if status in (400, 404):
        # WHY one code: the Gateway answers both for a target the caller may not see.
        raise not_found()
    if status == 409 or (status == 401 and _detail_code(response) == _REAUTH_CODE):
        return None
    if status != 200:
        raise _failed()
    try:
        document = response.json()
    except (ValueError, RecursionError):
        # WHY `RecursionError`: a body nested past the reader's depth limit is unreadable too,
        # and it is not a `ValueError`; uncaught, it ends the run as the Engine's own fault.
        raise _failed() from None
    if not isinstance(document, dict):
        raise _failed()
    return document


def _detail_code(response: httpx.Response) -> object:
    try:
        payload = response.json()
    except (ValueError, RecursionError):
        return None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return detail.get("code") if isinstance(detail, dict) else None


def _admits(rule: object, value: int) -> bool:
    """Whether a published `max_tokens` rule accepts ``value``: enabled, integer, in bounds."""
    if not isinstance(rule, dict):
        return False
    gateway, schema = rule.get("gateway"), rule.get("schema")
    return (
        isinstance(gateway, dict)
        and gateway.get("status") == "enabled"
        and isinstance(schema, dict)
        and _schema_admits(schema, value)
    )


def _schema_admits(schema: dict[str, Any], value: int) -> bool:
    kinds = schema.get("type")
    if not (kinds == "integer" or (isinstance(kinds, list) and "integer" in kinds)):
        return False
    low, high = schema.get("minimum"), schema.get("maximum")
    return (low is None or (_number(low) and low <= value)) and (
        high is None or (_number(high) and value <= high)
    )


def _number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float)


def _select(
    profile: RoutingProfile, scores: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], RoutingBranch]:
    """The scores as decoded and the branch of the unique highest label (steps 6 and 7).

    WHY only the label set here: Unit 3 already refused a result for another model or contract,
    duplicate labels, booleans and scores outside `[0, 1]`.
    """
    labels = sorted(item["label"] for item in scores)
    if labels != sorted(branch.label for branch in profile.branches):
        raise _routing_error(
            "the classifier's labels are not the labels this routing profile binds",
            ROUTING_INVALID_SCORES,
        )
    top = max(item["score"] for item in scores)
    leaders = [item["label"] for item in scores if item["score"] == top]
    if len(leaders) != 1:
        raise _routing_error(
            "more than one label holds the highest score, so no branch was asked",
            ROUTING_AMBIGUOUS,
        )
    choice = next(branch for branch in profile.branches if branch.label == leaders[0])
    return scores, choice


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
