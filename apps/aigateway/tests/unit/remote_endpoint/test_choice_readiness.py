"""Key readiness of a choice classifier: one synthetic choice within the target's limits (C7).

# FEATURE: Router Recipe extension Unit 5.1 — when `validation_target` names a
# `systemone-choice-v1` target, attaching a key sends one fixed SystemOne choice that fits the
# target's limits, and only an answer `decode_choice` accepts publishes the key.
# INVARIANT: readiness holds the endpoint to the same decoder dispatch uses, so a key never
# becomes VALID on an answer a later classification would refuse.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aigateway.core.api_key_validation import ApiKeyValidationStage, ApiKeyValidationState
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.plugins.remote_endpoint.completion import strict_json
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .choice_upstream import CHOICE_ALIAS, LIMITS, choice_target, native_answer
from .classifier_upstream import SCORES
from .fixtures import (
    CLASSIFIER_PATH,
    ENDPOINT_A,
    FINISHED_COMPLETION,
    JSON_TYPE,
    ORIGIN_A,
    classifier_target,
    document,
    endpoint,
)

KEY = "sk-byom-choice-readiness-0001"
GOOD = native_answer({"ping": 1.0})


def _plugin(
    target: dict[str, Any], respond: Any, sent: list[httpx.Request]
) -> RemoteEndpointPlugin:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return respond(request)

    doc = document(endpoint(targets=[target], validation_target=target["alias"]))
    definition = parse_remote_endpoint_config(doc).endpoints[0]
    return RemoteEndpointPlugin(definition, transport=httpx.MockTransport(handler))


async def _validate(plugin: RemoteEndpointPlugin) -> Any:
    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)
    assert result is not None
    return result


def _answering(body: Any):
    return lambda _request: httpx.Response(200, json=body)


@pytest.mark.asyncio
async def test_a_well_formed_choice_answer_is_valid_and_the_probe_is_one_fixed_question() -> None:
    sent: list[httpx.Request] = []
    plugin = _plugin(choice_target(), _answering(GOOD), sent)

    first = await _validate(plugin)
    await _validate(plugin)

    assert (first.state, first.stage) == (
        ApiKeyValidationState.VALID,
        ApiKeyValidationStage.READINESS,
    )
    assert first.probe_model == f"{ENDPOINT_A}/{CHOICE_ALIAS}"
    request = sent[0]
    assert (request.method, str(request.url)) == ("POST", ORIGIN_A + CLASSIFIER_PATH)
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {
        "state": {"body": "ping"},
        "questions": {
            "choice": {"type": "choice", "instructions": "ping", "criteria": {"ping": "ping"}}
        },
    }
    assert sent[0].content == sent[1].content


@pytest.mark.asyncio
async def test_the_probe_is_clipped_to_the_smallest_limits_and_names_the_upstream_model() -> None:
    tiny = dict.fromkeys(LIMITS, 1)
    sent: list[httpx.Request] = []
    target = choice_target(limits=tiny, upstream_model="jev/router-2026-10")

    result = await _validate(_plugin(target, _answering(native_answer({"p": 1.0})), sent))

    assert result.state is ApiKeyValidationState.VALID
    probe = json.loads(sent[0].content)
    assert list(probe) == ["model", "state", "questions"]
    assert probe["model"] == "jev/router-2026-10"
    assert probe["state"] == {"body": "p"}
    assert probe["questions"]["choice"]["instructions"] == "p"
    assert probe["questions"]["choice"]["criteria"] == {"p": "p"}


MALFORMED: dict[str, Any] = {
    "hf-scores": [SCORES],
    "chat-completion": FINISHED_COMPLETION,
    "empty-probabilities": native_answer({}),
    "too-many-labels": native_answer(dict.fromkeys("abcdefghi", 0.1)),
    "truncated-input": native_answer({"ping": 1.0}, usage={"truncated": True}),
    "other-question": {"answers": {"other": GOOD["answers"]["choice"]}},
    "error-beside-the-answers": native_answer({"ping": 1.0}, error={"message": "failed"}),
    "error-on-the-answer": {
        "answers": {"choice": {**GOOD["answers"]["choice"], "error": {"message": "failed"}}}
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", MALFORMED.values(), ids=MALFORMED.keys())
async def test_an_answer_dispatch_would_refuse_is_unavailable_not_valid(body: Any) -> None:
    sent: list[httpx.Request] = []

    result = await _validate(_plugin(choice_target(), _answering(body), sent))

    assert (result.state, result.stage) == (
        ApiKeyValidationState.UNAVAILABLE,
        ApiKeyValidationStage.READINESS,
    )
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403, 429, 500])
async def test_a_status_maps_as_the_hf_probe_maps_it(status: int) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"retry-after": "9"})

    chosen = await _validate(_plugin(choice_target(), respond, []))
    scored = await _validate(_plugin(classifier_target(), respond, []))

    assert (chosen.state, chosen.stage, chosen.retry_after_seconds) == (
        scored.state,
        scored.stage,
        scored.retry_after_seconds,
    )


@pytest.mark.asyncio
async def test_an_hf_probe_is_clipped_to_its_declared_text_limit() -> None:
    sent: list[httpx.Request] = []
    # WHY 3 and 8: SCORES holds three labels, the longest eight bytes.
    limits = {"max_labels": 3, "max_label_bytes": 8, "max_text_chars": 2}

    result = await _validate(_plugin(classifier_target(limits=limits), _answering([SCORES]), sent))

    assert result.state is ApiKeyValidationState.VALID
    assert json.loads(sent[0].content) == {"inputs": "pi"}


@pytest.mark.asyncio
async def test_an_hf_probe_answer_outside_its_limits_is_unavailable() -> None:
    limits = {"max_labels": 1, "max_label_bytes": 64, "max_text_chars": 10}
    two_labels = [[{"label": "a", "score": 0.5}, {"label": "b", "score": 0.5}]]

    result = await _validate(_plugin(classifier_target(limits=limits), _answering(two_labels), []))

    assert result.state is ApiKeyValidationState.UNAVAILABLE


def test_strict_json_refuses_a_repeated_key_only_when_asked() -> None:
    body = b'{"a": 1, "nested": {"b": 1, "b": 2}}'

    assert strict_json(JSON_TYPE, body) == {"a": 1, "nested": {"b": 2}}
    with pytest.raises(ValueError, match="repeated JSON object key"):
        strict_json(JSON_TYPE, body, unique_keys=True)
    assert strict_json(JSON_TYPE, b'{"a": {"b": 1}, "b": 2}', unique_keys=True) == {
        "a": {"b": 1},
        "b": 2,
    }
