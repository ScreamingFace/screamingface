from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import MODEL as _MODEL
from _model_parameter_fixtures import SUMMARY as _SUMMARY

import screamingface as sf
from screamingface import _default_client


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
    )


def _engine(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"object": "list", "data": [_SUMMARY]})
    if request.url.path == "/v1/model-parameters":
        return httpx.Response(200, json=_DETAILS)
    return httpx.Response(404)


def test_model_list_keeps_the_lightweight_capability_summary() -> None:
    with _client(_engine) as client:
        model = client.models.list()[0]

    assert model == sf.ModelInfo(
        id=_MODEL,
        provider="openrouter",
        supported_parameters=("max_tokens", "temperature"),
        supported_tools=("function",),
    )


def test_models_get_returns_profile_specific_details_from_the_canonical_route() -> None:
    seen: list[httpx.Request] = []

    def engine(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _engine(request)

    with _client(engine) as client:
        details = client.models.get(_MODEL)

    assert isinstance(details, sf.ModelDetails)
    assert details.id == _MODEL
    assert details.provider == "openrouter"
    assert details.upstream_id == "openai/gpt-5.5"
    assert details.contract_id == "pc_fixture"
    assert details.scope == "account_connection"
    assert details.auth_mode == "api_key"
    assert details.context_revision == "ctx_fixture"
    assert details.source_revision == "openrouter-models-v1"
    assert details.observed_at == datetime(2026, 8, 5, 10, tzinfo=UTC)
    assert details.expires_at == datetime(2026, 8, 5, 10, 5, tzinfo=UTC)
    assert details.stale is False
    assert details.degraded is False

    assert len(seen) == 1
    assert seen[0].url.path == "/v1/model-parameters"
    assert dict(seen[0].url.params) == {"model": _MODEL}


def test_models_get_decodes_parameters_tools_and_transport() -> None:
    with _client(_engine) as client:
        details = client.models.get(_MODEL)

    temperature = details.parameters["temperature"]
    assert isinstance(temperature, sf.ModelParameter)
    assert temperature.enabled is True
    assert temperature.request_path == "temperature"
    assert temperature.schema is not None
    assert temperature.schema.type == "number"
    assert temperature.schema.minimum == 0
    assert temperature.schema.maximum == 2
    assert temperature.provider_support == "supported"
    assert temperature.gateway_projection == "direct"
    assert temperature.applicable_auth_modes == ("api_key",)

    reasoning = details.parameters["reasoning_effort"]
    assert reasoning.enabled is False
    assert reasoning.schema is not None
    assert reasoning.schema.enum == ("low", "medium", "high")
    assert reasoning.gateway_reason == "not available under this auth mode"

    assert details.tools["function"].gateway_status == "enabled"
    assert details.transport["stream"].reason == "streaming is disabled"


@pytest.mark.parametrize("degraded", [False, True])
def test_models_get_accepts_static_and_degraded_null_freshness(degraded: bool) -> None:
    import copy

    body = copy.deepcopy(_DETAILS)
    body["freshness"] = {
        "observed_at": None,
        "expires_at": None,
        "stale": False,
        "degraded": degraded,
    }
    client = _client(lambda request: httpx.Response(200, json=body))

    with client:
        details = client.models.get(_MODEL)

    assert details.observed_at is None
    assert details.expires_at is None
    assert details.degraded is degraded


def test_parameter_schema_validates_every_published_constraint() -> None:
    schema = sf.ModelParameterSchema(
        type="string",
        enum=("alpha", "beta"),
        pattern="^[a-z]+$",
        max_length=5,
    )

    schema.validate("alpha")
    with pytest.raises(ValueError, match="at most 5"):
        schema.validate("alphabet")
    with pytest.raises(ValueError, match="required pattern"):
        schema.validate("ALPHA")
    with pytest.raises(ValueError, match="one of"):
        schema.validate("gamma")

    numbers = sf.ModelParameterSchema(type="number", minimum=0, maximum=2)
    with pytest.raises(ValueError, match="finite"):
        numbers.validate(float("nan"))
    with pytest.raises(ValueError, match=">= 0"):
        numbers.validate(-1)
    with pytest.raises(ValueError, match="expected number"):
        numbers.validate(True)

    array = sf.ModelParameterSchema(type="array", items="number")
    array.validate([1, 2.5])
    with pytest.raises(ValueError, match="array items must be number"):
        array.validate([1, "two"])
    with pytest.raises(ValueError, match="array items must be finite"):
        array.validate([float("inf")])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type": "mystery"}, "schema type is invalid"),
        ({"type": ("string", "string")}, "type contains duplicates"),
        ({"type": "number", "minimum": True}, "minimum must be finite"),
        ({"type": "number", "minimum": 2, "maximum": 1}, "minimum cannot exceed"),
        ({"type": "array", "items": "array"}, "items type is invalid"),
        ({"type": "number", "max_length": 4}, "constraints require a string"),
        ({"type": "string", "pattern": "[a-z]+"}, "pattern must be anchored"),
        ({"type": "string", "pattern": "^[ $"}, "pattern is invalid"),
        ({"type": "string", "pattern": 42}, "pattern must be a string"),
        ({"type": "string", "max_length": True}, "max_length must be positive"),
    ],
)
def test_parameter_schema_rejects_malformed_contracts(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        sf.ModelParameterSchema(**kwargs)


@pytest.mark.asyncio
async def test_async_models_get_returns_the_same_typed_details() -> None:
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
    ) as client:
        details = await client.models.get(_MODEL)

    assert details.id == _MODEL
    assert details.parameters["temperature"].enabled is True


def test_lazy_models_get_delegates_to_the_default_client(monkeypatch: Any) -> None:
    expected = object()

    class Models:
        def get(self, model_id: str) -> object:
            assert model_id == _MODEL
            return expected

    class FakeClient:
        models = Models()

    monkeypatch.setattr(_default_client, "_client", FakeClient())
    try:
        assert sf.models.get(_MODEL) is expected
    finally:
        monkeypatch.setattr(_default_client, "_client", None)


@pytest.mark.parametrize(
    ("model_id", "error", "message"),
    [
        (None, TypeError, "model_id must be a string"),
        ("/", ValueError, "model_id must be a non-empty string"),
    ],
)
def test_models_get_rejects_invalid_model_ids(
    model_id: Any,
    error: type[Exception],
    message: str,
) -> None:
    with _client(_engine) as client, pytest.raises(error, match=message):
        client.models.get(model_id)


def test_models_get_preserves_authentication_failures() -> None:
    client = _client(lambda request: httpx.Response(401))

    with client, pytest.raises(sf.AuthenticationError) as caught:
        client.models.get(_MODEL)

    assert caught.value.code == "authentication_required"
    assert caught.value.status == 401


def test_models_get_explains_a_missing_provider_profile() -> None:
    body = {
        "detail": {
            "code": "profile_not_found",
            "provider": "codex",
            "name": "default",
        }
    }
    client = _client(lambda request: httpx.Response(404, json=body))

    with client, pytest.raises(sf.ProviderConnectionError) as caught:
        client.models.get("codex/gpt-5.4")

    assert caught.value.message == "Codex profile 'default' is not connected"
    assert caught.value.code == "profile_not_found"
    assert caught.value.provider == "codex"
    assert caught.value.status == 404
    assert caught.value.details == body["detail"]
    assert caught.value.hint == "Open `sf.connect()` and connect Codex, then retry."


def test_models_get_preserves_engine_unavailability() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = _client(unavailable)
    with client, pytest.raises(sf.EngineUnavailableError) as caught:
        client.models.get(_MODEL)

    assert caught.value.engine_url == "https://engine.example"


def test_model_list_rejects_duplicate_canonical_ids() -> None:
    body = {"object": "list", "data": [_SUMMARY, _SUMMARY]}
    client = _client(lambda request: httpx.Response(200, json=body))

    with client, pytest.raises(sf.PlanningError, match="duplicate id") as caught:
        client.models.list()

    assert caught.value.code == "invalid_catalogue"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda body: body.update(schema_version=2), "schema_version"),
        (lambda body: body["model"].update(id="openrouter/other"), "wrong Model id"),
        (lambda body: body["parameters"].update(temperature=[]), "temperature"),
        (
            lambda body: body["parameters"]["temperature"]["schema"].update(type="mystery"),
            "schema type",
        ),
        (
            lambda body: body["parameters"]["temperature"].update(request_path="top_p"),
            "mismatched request_path",
        ),
        (
            lambda body: body["parameters"]["temperature"]["provider"].update(stale="no"),
            "provider stale must be a boolean",
        ),
        (
            lambda body: body["parameters"]["temperature"]["schema"].update(minimum=True),
            "schema minimum must be a number",
        ),
        (
            lambda body: body["parameters"]["temperature"]["schema"].update(maxLength=0),
            "schema maxLength must be a positive integer",
        ),
        (
            lambda body: body["tools"].update({" ": {}}),
            "Model tools name must be a non-empty string",
        ),
        (
            lambda body: body["tools"]["function"].update(provider_support="invented"),
            "provider_support is invalid",
        ),
        (
            lambda body: body["context"].update(auth_mode="password"),
            "auth_mode is invalid",
        ),
        (
            lambda body: body["parameters"]["temperature"].update(schema=None),
            "enabled Model parameter must publish a schema",
        ),
        (
            lambda body: body["freshness"].update(observed_at="not-a-time"),
            "observed_at must be an ISO 8601 timestamp",
        ),
        (
            lambda body: body["freshness"].update(expires_at=None),
            "timestamps must both be present or both be null",
        ),
        (
            lambda body: body["freshness"].update(degraded=True),
            "degraded Model freshness cannot be stale or carry timestamps",
        ),
        (
            lambda body: body["freshness"].update(expires_at=body["freshness"]["observed_at"]),
            "expires_at must follow observed_at",
        ),
        (
            lambda body: body["freshness"].update(
                observed_at=None,
                expires_at=None,
                stale=True,
            ),
            "stale Model freshness must carry an observation window",
        ),
    ],
)
def test_models_get_rejects_malformed_v1_documents(
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    import copy

    body = copy.deepcopy(_DETAILS)
    mutate(body)
    client = _client(lambda request: httpx.Response(200, json=body))

    with client, pytest.raises(sf.PlanningError, match=message) as caught:
        client.models.get(_MODEL)

    assert caught.value.code == "invalid_catalogue"
    assert caught.value.permanent is True


def test_model_info_repr_is_a_compact_capability_summary() -> None:
    with _client(_engine) as client:
        info = client.models.list()[0]

    assert repr(info) == (
        "ModelInfo('openrouter/openai/gpt-5.5', provider='openrouter', parameters=2, tools=1)"
    )


def test_model_details_repr_summarises_identity_and_contract_sizes() -> None:
    with _client(_engine) as client:
        details = client.models.get(_MODEL)

    # WHY: the dataclass default repr dumps all 15 fields incl. the full nested parameter
    # mappings; the summary identifies the profile and reports contract sizes as counts.
    assert repr(details) == (
        "ModelDetails('openrouter/openai/gpt-5.5', provider='openrouter', "
        "scope='account_connection', parameters=3, tools=1, transport=1)"
    )


@pytest.mark.parametrize(
    ("freshness", "flag"),
    [
        (
            {
                "observed_at": "2026-08-05T10:00:00Z",
                "expires_at": "2026-08-05T10:05:00Z",
                "stale": True,
                "degraded": False,
            },
            "stale=True",
        ),
        (
            {"observed_at": None, "expires_at": None, "stale": False, "degraded": True},
            "degraded=True",
        ),
    ],
)
def test_model_details_repr_surfaces_a_set_freshness_flag(
    freshness: dict[str, Any],
    flag: str,
) -> None:
    import copy

    body = copy.deepcopy(_DETAILS)
    body["freshness"] = freshness
    client = _client(lambda request: httpx.Response(200, json=body))

    with client:
        details = client.models.get(_MODEL)

    # INVARIANT: stale/degraded are mutually exclusive, so at most one flag ever appears.
    assert repr(details) == (
        "ModelDetails('openrouter/openai/gpt-5.5', provider='openrouter', "
        f"scope='account_connection', parameters=3, tools=1, transport=1, {flag})"
    )
