"""Discovery advertises a colon-bearing model under its `~`-encoded, url4-addressable id.

FEATURE: OME-873 — `GET /v1/models` / `GET /v1/model-parameters` show exactly what a caller
should type into a url4 expression, never aigateway's raw (colon-bearing) id verbatim.
"""

from __future__ import annotations

import pytest

from screamingface_engine.catalog.executable import (
    ExecutableCatalog,
    ExecutableModelParameterSource,
)
from screamingface_engine.catalog.port import (
    Credential,
    ModelCatalog,
    ModelNotInstalled,
    ModelParameterResponse,
)

pytestmark = pytest.mark.asyncio

_ROUTABLE = "openrouter/openai/gpt-5.5"
_REAL_ID = "huggingface/openai/gpt-oss-120b:cerebras"
_ROUTE_ID = "huggingface/openai/gpt-oss-120b~cerebras"


class _GatewayCatalog:
    counters = None
    entry_count = 0
    model_parameter_source = None

    async def fetch(self, credential: Credential) -> ModelCatalog:
        body = {
            "object": "list",
            "data": [
                {"id": _ROUTABLE, "object": "model"},
                {"id": _REAL_ID, "object": "model"},
            ],
        }
        return ModelCatalog(body=body, etag="irrelevant")

    def max_age_s(self, credential: Credential) -> int:
        return 60

    async def aclose(self) -> None:
        pass


async def test_a_retained_colon_bearing_item_is_rewritten_to_its_encoded_id() -> None:
    catalog = ExecutableCatalog(_GatewayCatalog(), frozenset({_ROUTABLE, _REAL_ID}))

    result = await catalog.fetch(Credential.derive())

    assert result.body["data"] == [
        {"id": _ROUTABLE, "object": "model"},
        {"id": _ROUTE_ID, "object": "model"},
    ]  # the real (colon-bearing) id never reaches the caller


async def test_encoding_is_a_no_op_for_an_id_with_no_colon() -> None:
    catalog = ExecutableCatalog(_GatewayCatalog(), frozenset({_ROUTABLE}))

    result = await catalog.fetch(Credential.derive())

    assert result.body["data"] == [{"id": _ROUTABLE, "object": "model"}]


class _GatewayDetails:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.seen.append(model)
        return ModelParameterResponse(status=200, content=b'{"model":{}}')

    async def aclose(self) -> None:
        pass


async def test_model_parameters_accepts_the_encoded_id_and_forwards_the_real_one() -> None:
    details = _GatewayDetails()
    source = ExecutableModelParameterSource(details, frozenset({_REAL_ID}))

    result = await source.fetch_model_parameters(Credential.derive(), _ROUTE_ID)

    assert result.status == 200
    assert details.seen == [_REAL_ID]


async def test_model_parameters_still_rejects_an_id_outside_the_declared_world() -> None:
    details = _GatewayDetails()
    source = ExecutableModelParameterSource(details, frozenset({_REAL_ID}))

    with pytest.raises(ModelNotInstalled):
        await source.fetch_model_parameters(Credential.derive(), "openrouter/not-declared")

    assert details.seen == []
