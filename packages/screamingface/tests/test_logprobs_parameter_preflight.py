"""Refuse before spend when a Model's PROVIDER cannot accept a logprobs parameter (E4b part 3).

Pins LC#15 (CHAR): the existing preflight refuses `logprobs` and `top_logprobs` when the provider
catalog denies them, or does not list them, before any spend. Unit 4 adds the injected params and
their test (D-U3-6). Exemplar: `test_unsupported_provider_parameter_preflight.py`. A separate
module (append-only gate).
"""

from __future__ import annotations

import copy
from typing import Any, NoReturn

import httpx
import pytest
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import SUMMARY as _SUMMARY
from url4 import RelExpr, expr, render, src, text

import screamingface as sf

_BENCHMARK_URL4 = render(
    expr(
        src(
            RelExpr(path="/candidate", context="question", intent=text("$candidate")),
            name="answer",
            weight=0.0,
        ),
        intent=text("$answer"),
    )
)
_BENCHMARK = {
    "schema": "screamingface.benchmark.v1",
    "id": "fixture",
    "title": "Fixture",
    "description": "Fixture Benchmark.",
    "revision": "fixture-revision",
    "case_count": 1,
    "url4": _BENCHMARK_URL4,
}
_MEMBER = "openrouter/test/member"


def _row(name: str, support: str) -> dict[str, object]:
    """One contract row: gateway POLICY enabled, provider EVIDENCE `support`."""
    schema: dict[str, object] = {"type": "boolean"}
    if name != "logprobs":
        schema = {"type": "integer", "minimum": 0, "maximum": 20}
    return {
        "request_path": name,
        "schema": schema,
        "provider": {
            "support": support,
            "source": "openrouter:models",
            "stale": False,
            "deprecated": False,
        },
        "gateway": {
            "status": "enabled",
            "projection": "direct",
            "cache_behavior": "keyed",
            "applicable_auth_modes": ["api_key"],
        },
    }


def _details(rows: dict[str, str]) -> dict[str, object]:
    value: dict[str, Any] = copy.deepcopy(_DETAILS)
    provider, upstream = _MEMBER.split("/", 1)
    value["model"] = {"id": _MEMBER, "gateway_provider": provider, "upstream_id": upstream}
    for name, support in rows.items():
        value["parameters"][name] = _row(name, support)
    return value


def _engine(rows: dict[str, str]) -> httpx.MockTransport:
    # WHY one route table: PLR0911 (four returns in one handler). The answers are the spec's.
    summary = {
        **_SUMMARY,
        "id": _MEMBER,
        "owned_by": "openrouter",
        "parameter_contract_url": f"/v1/model-parameters?model={_MEMBER}",
    }
    routes: dict[str, Any] = {
        "/v1/benchmarks/fixture": _BENCHMARK,
        "/v1/models": {"object": "list", "data": [summary]},
        "/v1/model-parameters": _details(rows),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path not in routes:
            return httpx.Response(404)
        return httpx.Response(200, json=routes[request.url.path])

    return httpx.MockTransport(handler)


class _ForbiddenTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("the logprobs preflight must refuse before any spend")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


def _refusal(params: dict[str, bool | int], rows: dict[str, str]) -> sf.PlanningError:
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(rows),
        run_transport=transport,
    )
    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_MEMBER, params=params), benchmark="fixture")
    assert transport.called is False
    return caught.value


def test_preflight_refuses_a_model_the_catalog_marks_without_logprobs() -> None:
    error = _refusal({"logprobs": True}, {"logprobs": "unsupported"})
    assert error.code == "unsupported_model_parameter"
    assert error.permanent is True
    assert error.details == {
        "model": _MEMBER,
        "parameter": "logprobs",
        "provider_support": "unsupported",
        "provider_source": "openrouter:models",
    }


def test_preflight_refuses_top_logprobs_the_catalog_marks_unsupported() -> None:
    error = _refusal(
        {"logprobs": True, "top_logprobs": 5},
        {"logprobs": "supported", "top_logprobs": "unsupported"},
    )
    assert error.code == "unsupported_model_parameter"
    assert error.permanent is True
    assert error.details == {
        "model": _MEMBER,
        "parameter": "top_logprobs",
        "provider_support": "unsupported",
        "provider_source": "openrouter:models",
    }


def test_preflight_refuses_logprobs_the_contract_does_not_list() -> None:
    error = _refusal({"logprobs": True}, {})
    assert error.code == "unsupported_model_parameter"
    assert error.permanent is True
    assert error.details == {"model": _MEMBER, "parameter": "logprobs"}
