"""E4b part 3 (LC-E5, C4b, LC#20): the OpenRouter parameter refusal has its own code.

FEATURE: E4b signal sources v1 — logprob capture. The engine asks for ``logprobs`` and must
tell "this model cannot give logprobs" apart from every other upstream failure, so that the
member fails with ``logprobs_unsupported`` and not with a generic provider error.

WHY: unit 1 recorded the live answer (2026-10-15). An OpenRouter model with no endpoint that
supports ``logprobs`` under the gateway's forced ``require_parameters`` is refused with a
transport 404, which the route mapped to ``provider_error`` — the same status and code as a
``max_price`` or a data-policy refusal, an unknown upstream model, or any other upstream 404.
The refusal was NOT distinct, so the plugin gives it ``unsupported_parameters``.

INVARIANT: the answer carries gateway-authored text only. The provider text and any named
internal endpoint stay out of the response, as on every other dispatch error.
INVARIANT: only the transport shape of the PARAMETER refusal changes. Other 404 refusals and
the embedded HTTP-200 shape keep their mapping (pinned in ``test_openrouter_no_eligible_endpoint``
and ``test_openrouter_routing_policy_routes``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from litellm.exceptions import NotFoundError

from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-parameter-refusal"
_MODEL = "openrouter/anthropic/claude-fable-5"
_MESSAGES: list[Any] = [{"role": "user", "content": "hi"}]
_WIRE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1")

_EXPECTED_DETAIL = {
    "code": "unsupported_parameters",
    "provider": "openrouter",
    "message": "No upstream endpoint for this model supports every requested parameter.",
}


@pytest.fixture(autouse=True)
def _api_key_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicit test double (per tests/unit/conftest.py AIDEV-NOTE): key readiness
    # is not what this file exercises.
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self, _plugin, _provider, _api_key) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _create_connection(client) -> None:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text


def _transport_404(message: str) -> Exception:
    # Mirrors the provenance a real litellm OpenRouter transport failure carries
    # (chained httpx.HTTPStatusError + surfaced wire headers): the live refusal of
    # unit 1 took the transport path (attempt failure_code provider_status_error).
    exc = NotFoundError(
        message=message,
        llm_provider="openrouter",
        model=_MODEL,
        response=httpx.Response(404, request=_WIRE_REQUEST),
    )
    response = httpx.Response(404, request=_WIRE_REQUEST)
    exc.__cause__ = httpx.HTTPStatusError("404", request=_WIRE_REQUEST, response=response)
    exc.litellm_response_headers = dict(response.headers)  # type: ignore[attr-defined]
    return exc


def _counting_raiser(exc: Exception, calls: list[dict[str, Any]]):
    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        raise exc

    return fake_acompletion


def _post_chat(client, body: dict[str, Any] | None = None):
    payload = {"model": _MODEL, "messages": list(_MESSAGES), **(body or {})}
    return client.post("/v1/chat/completions", json=payload)


# The two phrasings OpenRouter uses for "no endpoint supports every supplied parameter".
# The live refusal is wrapped by litellm in "OpenrouterException - {json}", so both appear
# here inside such a wrapper, with a named internal endpoint that must never leak.
_PARAMETER_REFUSALS = [
    pytest.param(
        'litellm.NotFoundError: OpenrouterException - {"error":{"message":"No endpoints found '
        "that can handle the requested parameters. To learn more about provider routing, "
        'visit: https://openrouter.ai/docs/provider-routing","code":404}} '
        "Tried provider secret-internal-router.",
        id="can-handle-the-requested-parameters",
    ),
    pytest.param(
        "No endpoints found that support all parameters: logprobs, top_logprobs. "
        "Tried provider secret-internal-router.",
        id="support-all-parameters",
    ),
]


@pytest.mark.parametrize("provider_message", _PARAMETER_REFUSALS)
def test_openrouter_parameter_refusal_has_its_own_code(
    enabled_openrouter, credential_blobs, authenticated_client, provider_message: str
) -> None:
    # STORY: as the engine, I ask a model for logprobs and it has no endpoint that can
    # give them; I get a code that says so, and not the code of any other upstream 404.
    _create_connection(authenticated_client)
    calls: list[dict[str, Any]] = []
    with patch("litellm.acompletion", _counting_raiser(_transport_404(provider_message), calls)):
        resp = _post_chat(authenticated_client, {"logprobs": True, "top_logprobs": 5})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == _EXPECTED_DETAIL
    # INVARIANT: gateway-authored text only.
    assert "No endpoints found" not in resp.text
    assert "secret-internal-router" not in resp.text
    assert "OpenrouterException" not in resp.text
    # INVARIANT: a refusal is deterministic, so it is never retried.
    assert len(calls) == 1


@pytest.mark.parametrize(
    "provider_message",
    [
        pytest.param(
            "No endpoints found that satisfy max_price. Tried provider secret-internal-router.",
            id="max-price",
        ),
        pytest.param("No endpoints found that support zero data retention", id="zdr"),
        pytest.param(
            "No endpoints found matching your data policy (Free model publication).",
            id="data-policy",
        ),
        pytest.param("No endpoints found for anthropic/claude-fable-5.", id="unknown-model"),
        pytest.param("Not Found", id="plain-404"),
    ],
)
def test_other_openrouter_404_refusals_keep_provider_error(
    enabled_openrouter, credential_blobs, authenticated_client, provider_message: str
) -> None:
    # WHY: only the PARAMETER refusal earns the new code. A routing-control refusal or a
    # missing model is a different failure, and naming it "unsupported_parameters" would
    # make the engine call it a logprobs refusal.
    _create_connection(authenticated_client)
    calls: list[dict[str, Any]] = []
    with patch("litellm.acompletion", _counting_raiser(_transport_404(provider_message), calls)):
        resp = _post_chat(authenticated_client, {"logprobs": True})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "provider_error"
    assert "No endpoints found" not in resp.text
    assert "secret-internal-router" not in resp.text


def test_the_parameter_refusal_text_on_a_non_404_status_keeps_its_mapping(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # INVARIANT: the detector needs BOTH the 404 status and the parameter-refusal text. A
    # 400 carrying the same words stays the route's `bad_request`.
    from litellm.exceptions import BadRequestError

    _create_connection(authenticated_client)
    exc = BadRequestError(
        message="No endpoints found that support all parameters: logprobs",
        llm_provider="openrouter",
        model=_MODEL,
        response=httpx.Response(400, request=_WIRE_REQUEST),
    )
    response = httpx.Response(400, request=_WIRE_REQUEST)
    exc.__cause__ = httpx.HTTPStatusError("400", request=_WIRE_REQUEST, response=response)
    exc.litellm_response_headers = dict(response.headers)  # type: ignore[attr-defined]
    calls: list[dict[str, Any]] = []
    with patch("litellm.acompletion", _counting_raiser(exc, calls)):
        resp = _post_chat(authenticated_client, {"logprobs": True})

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "bad_request"
    assert "No endpoints found" not in resp.text


def test_the_embedded_http_200_parameter_refusal_keeps_its_mapping(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # AIDEV-NOTE: the embedded HTTP-200 shape is out of scope for LC-E5 — the live refusal
    # is a transport 404, and `test_no_eligible_endpoint_embedded_in_a_200_body_surfaces_
    # sanitized` pins `provider_error` for this shape. The embedded scanner never reads
    # provider text, and this test keeps it that way.
    _create_connection(authenticated_client)
    payload = {
        "id": "gen-parameter-refusal",
        "choices": [],
        "error": {
            "code": 404,
            "message": "No endpoints found that support all parameters: logprobs",
            "metadata": {"provider_name": "secret-internal-router"},
        },
    }

    async def _return(**_kwargs):
        return SimpleNamespace(model_dump=lambda: payload)

    with patch("litellm.acompletion", _return):
        resp = _post_chat(authenticated_client, {"logprobs": True})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "provider_error"
    assert "No endpoints found" not in resp.text
    assert "secret-internal-router" not in resp.text
