"""Key readiness by task: a classifier validation target is probed with one classification.

# FEATURE: hosted BYOM Unit 3 — when `validation_target` names a classifier, attaching a key sends
# one classification of a fixed synthetic text to that target's own origin and path.
# INVARIANT: only an answer that passes the classification contract is VALID; every status maps
# exactly as the chat probe maps it, so a classifier-only endpoint is connected like any other.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aigateway.core.api_key_validation import ApiKeyValidationStage, ApiKeyValidationState
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .classifier_upstream import (
    SCORES,
    classifier_id,
    classifier_only_document,
    mixed_document,
    started,
)
from .conftest import MALFORMED, REJECTED, Harness, put_key, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    CLASSIFIER_ALIAS,
    CLASSIFIER_PATH,
    ENDPOINT_A,
    FINISHED_COMPLETION,
    ORIGIN_A,
)

KEY = "sk-byom-classifier-readiness-0001"


def _plugin(respond: Any, sent: list[httpx.Request], doc: dict[str, Any]) -> RemoteEndpointPlugin:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return respond(request)

    definition = parse_remote_endpoint_config(doc).endpoints[0]
    return RemoteEndpointPlugin(definition, transport=httpx.MockTransport(handler))


def _classifier_probed(respond: Any, sent: list[httpx.Request]) -> RemoteEndpointPlugin:
    return _plugin(respond, sent, mixed_document(validation_target=CLASSIFIER_ALIAS))


async def _validate(plugin: RemoteEndpointPlugin) -> Any:
    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)
    assert result is not None
    return result


@pytest.mark.asyncio
async def test_a_valid_classification_is_valid_at_readiness() -> None:
    sent: list[httpx.Request] = []

    result = await _validate(
        _classifier_probed(lambda _r: httpx.Response(200, json=[SCORES]), sent)
    )

    assert (result.state, result.stage) == (
        ApiKeyValidationState.VALID,
        ApiKeyValidationStage.READINESS,
    )
    assert result.probe_model == classifier_id(ENDPOINT_A)
    (request,) = sent
    assert (request.method, str(request.url)) == ("POST", ORIGIN_A + CLASSIFIER_PATH)
    assert request.headers["authorization"] == f"Bearer {KEY}"
    probe = json.loads(request.content)
    assert set(probe) == {"inputs"}
    assert isinstance(probe["inputs"], str) and probe["inputs"]


@pytest.mark.asyncio
async def test_the_probe_text_is_fixed() -> None:
    sent: list[httpx.Request] = []
    plugin = _classifier_probed(lambda _r: httpx.Response(200, json=[SCORES]), sent)

    await _validate(plugin)
    await _validate(plugin)

    assert sent[0].content == sent[1].content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [[], [[]], SCORES, [SCORES, SCORES], [[{"label": "a", "score": 2}]], FINISHED_COMPLETION],
    ids=["empty", "empty-batch", "flat", "two-item-batch", "out-of-range", "chat-completion"],
)
async def test_a_malformed_classification_is_unavailable_not_valid(body: Any) -> None:
    # INVARIANT: VALID publishes the key, so it needs a real classification, not merely a 200.
    sent: list[httpx.Request] = []

    result = await _validate(_classifier_probed(lambda _r: httpx.Response(200, json=body), sent))

    assert (result.state, result.stage) == (
        ApiKeyValidationState.UNAVAILABLE,
        ApiKeyValidationStage.READINESS,
    )
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403, 429, 500, 503, 302])
async def test_a_status_maps_as_the_chat_probe_maps_it(status: int) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"retry-after": "9", "location": ORIGIN_A + "/x"})

    classified = await _validate(_classifier_probed(respond, []))
    chatted = await _validate(_plugin(respond, [], mixed_document()))

    assert (classified.state, classified.stage, classified.retry_after_seconds) == (
        chatted.state,
        chatted.stage,
        chatted.retry_after_seconds,
    )
    expected = {
        401: ApiKeyValidationState.INVALID,
        402: ApiKeyValidationState.NO_QUOTA,
        403: ApiKeyValidationState.PERMISSION_DENIED,
        429: ApiKeyValidationState.RATE_LIMITED,
    }
    assert classified.state is expected.get(status, ApiKeyValidationState.UNAVAILABLE)


@pytest.mark.asyncio
async def test_a_transport_failure_is_unavailable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = await _validate(_classifier_probed(fail, []))

    assert result.state is ApiKeyValidationState.UNAVAILABLE


# --- through the admin API, on an endpoint that declares only a classifier ----------------------


def _status(client: Any, account: str) -> str:
    response = client.get("/v1/provider-access", headers=tenant_headers(account))
    assert response.status_code == 200, response.text
    return {row["provider"]: row["status"] for row in response.json()["providers"]}[ENDPOINT_A]


def test_a_classifier_only_endpoint_is_connected_by_a_classification_probe(byom: Harness) -> None:
    with started(byom, classifier_only_document()) as (client, upstream):
        before = _status(client, ACCOUNT_A)
        attached = put_key(client, ACCOUNT_A, ENDPOINT_A, KEY)
        after = _status(client, ACCOUNT_A)

    assert attached.status_code == 200, attached.text
    assert (before, after) == ("not_connected", "connected")
    (probe,) = upstream.calls
    assert (probe.url, probe.bearer, probe.probe) == (
        ORIGIN_A + CLASSIFIER_PATH,
        f"Bearer {KEY}",
        True,
    )
    assert byom.upstream.calls == []
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY


@pytest.mark.parametrize("marker, refused", [(MALFORMED, 503), (REJECTED, 422)])
def test_a_failed_replacement_keeps_the_previous_key(
    byom: Harness, marker: str, refused: int
) -> None:
    with started(byom, classifier_only_document()) as (client, upstream):
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        replaced = put_key(client, ACCOUNT_A, ENDPOINT_A, f"sk-{marker}-0002")
        status = _status(client, ACCOUNT_A)

    assert replaced.status_code == refused, replaced.text
    assert status == "connected"
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY
    assert [call.probe for call in upstream.calls] == [True, True]
