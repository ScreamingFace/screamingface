"""OME-1381 — the published OpenAPI contract documents the `X-Profile` refusal where it applies.

# FEATURE: selector-less provider access — design `component/provider-access` v6, "Stage D
# target", rollout step 2 (Engine producer-off). Refusing the header is a breaking change to the
# public REST contract, so the contract itself has to say so.
# INVARIANT: every REST operation that refuses a nonblank `X-Profile` declares the header as
# deprecated, and declares its 400 as an RFC 9457 problem whose schema carries the refusal `code`.
# A client generated from the document therefore learns both that the header is retired and
# what the refusal looks like.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_rest_connections import FakeConnections
from test_rest_connections import _app as _connections_app

_PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}

_REFUSING_OPERATIONS = [
    pytest.param("/", "get", id="execution"),
    pytest.param("/v1/models", "get", id="model-listing"),
    pytest.param("/v1/model-parameters", "get", id="model-parameters"),
    pytest.param("/v1/connections", "get", id="list-connections"),
    pytest.param("/v1/connections/{provider}", "put", id="connect"),
    pytest.param("/v1/connections/{provider}/oauth", "post", id="start-oauth"),
    pytest.param("/v1/connections/{provider}", "delete", id="disconnect"),
]


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return _connections_app(FakeConnections()).openapi()


def _operation(schema: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    return schema["paths"][path][method]


@pytest.mark.parametrize(("path", "method"), _REFUSING_OPERATIONS)
def test_every_refusing_operation_declares_the_header_deprecated(
    schema: dict[str, Any], path: str, method: str
) -> None:
    parameters = _operation(schema, path, method).get("parameters", [])

    (header,) = [p for p in parameters if p["name"] == "X-Profile"]
    assert header["in"] == "header"
    assert header["deprecated"] is True
    assert header.get("required", False) is False
    assert "refused with 400" in header["description"]


@pytest.mark.parametrize(("path", "method"), _REFUSING_OPERATIONS)
def test_every_refusing_operation_declares_its_400_as_a_problem(
    schema: dict[str, Any], path: str, method: str
) -> None:
    refusal = _operation(schema, path, method)["responses"]["400"]

    assert refusal["content"]["application/problem+json"]["schema"] == _PROBLEM_REF
    assert "x_profile_unsupported" in refusal["description"]


def test_the_problem_schema_carries_the_refusal_code(schema: dict[str, Any]) -> None:
    problem = schema["components"]["schemas"]["Problem"]

    assert "code" in problem["properties"]
    assert "code" not in problem.get("required", [])


def test_model_parameters_keep_declaring_the_gateway_verbatim_400(
    schema: dict[str, Any],
) -> None:
    """A 400 on this route is either the Engine's problem or AI Gateway's verbatim JSON (an
    invalid canonical model id); declaring only the first would misstate the second."""
    refusal = _operation(schema, "/v1/model-parameters", "get")["responses"]["400"]

    assert set(refusal["content"]) == {"application/problem+json", "application/json"}


def test_routes_that_never_read_the_header_do_not_declare_it(schema: dict[str, Any]) -> None:
    """The header is documented where it is refused and nowhere else (D12 scope)."""
    for path in ("/token", "/healthz"):
        for operation in schema["paths"].get(path, {}).values():
            names = {p["name"] for p in operation.get("parameters", [])}
            assert "X-Profile" not in names, path
