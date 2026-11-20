"""OME-881: the per-model details probe decides OpenRouter availability.

FEATURE: run any OpenRouter model (OME-878). The Engine's `/v1/models` listing
used to be the SDK's whole availability authority, refusing a missing model
before the per-model `GET /v1/model-parameters` call — the exact call that now
triggers dynamic admission on the Engine (OME-880). EVERY listing-missing id now
probes that endpoint instead (review F10: the SDK keeps no admissibility grammar
of its own — the Engine and Gateway are the only authorities): an admitting
Engine lets the run proceed; a refusing one answers with the gateway's
diagnostic code, decoded into a clear `PlanningError`; a non-admitting one
answers a plain 404 that reads as today's refusal — all pre-spend, all $0.

INVARIANT: a model the Engine does not serve still refuses BEFORE execution —
the probe moved the refusal's source, never its timing.
"""

from __future__ import annotations

from typing import NoReturn

import httpx
import pytest
from _model_parameter_fixtures import details as _model_details
from _run_transport import AsyncScriptedRun, ScriptedRun
from url4 import RelExpr, expr, render, src, text

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate

_TARGET = "openrouter/qwen/qwen2.5-7b-instruct"
_JUDGE = "provider/judge"

_BENCHMARK_URL4 = render(
    expr(
        src(
            RelExpr(path="/candidate", context="question", intent=text("$candidate")),
            name="answer",
            weight=0.0,
        ),
        src(
            RelExpr(path=f"/{_JUDGE}", context="$answer", intent=text("Grade.")),
            name="grade",
            weight=0.0,
        ),
        intent=text("$grade"),
    )
)

_BENCHMARK = {
    "schema": "screamingface.benchmark.v1",
    "id": "draco",
    "title": "DRACO",
    "description": "Fixture DRACO Benchmark.",
    "revision": "fixture-revision",
    "case_count": 1,
    "url4": _BENCHMARK_URL4,
}


def _model_row(model: str) -> dict[str, object]:
    return {
        "id": model,
        "object": "model",
        "owned_by": model.split("/", 1)[0],
        "supported_parameters": [],
        "supported_tools": [],
        "unsupported_parameter_behavior": "reject",
        "parameter_contract_url": f"/v1/model-parameters?model={model}",
    }


def _admission_refusal(model: str, code: str, message: str) -> httpx.Response:
    # The exact 404 body OME-880's engine relays for a gateway refusal.
    return httpx.Response(
        404,
        json={
            "detail": {
                "code": code,
                "message": message,
                "provider": "openrouter",
                "model": model,
            }
        },
    )


_NOT_INSTALLED = httpx.Response(
    404,
    json={
        "type": "about:blank",
        "title": "Not Found",
        "detail": "the model is not installed on this Engine",
        "status": 404,
    },
)


def _engine(details_responses: dict[str, httpx.Response], probed: list[str]):
    """A fake Engine listing only the judge; per-model details answer from the table."""

    def _details(request: httpx.Request) -> httpx.Response:
        model = request.url.params["model"]
        probed.append(model)
        canned = details_responses.get(model)
        return canned if canned is not None else httpx.Response(200, json=_model_details(model))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/model-parameters":
            return _details(request)
        canned = {
            "/v1/models": {"object": "list", "data": [_model_row(_JUDGE)]},
            "/v1/benchmarks/draco": _BENCHMARK,
        }.get(request.url.path)
        return httpx.Response(404) if canned is None else httpx.Response(200, json=canned)

    return handler


class _ReachedExecution(Exception):
    """Raised by the transports below: preflight passed and execution began."""


class _Transport(ScriptedRun):
    called = False

    def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        self.called = True
        raise _ReachedExecution(candidate.url4)


class _AsyncTransport(AsyncScriptedRun):
    called = False

    async def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        self.called = True
        raise _ReachedExecution(candidate.url4)


def _client(handler, transport) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
        run_transport=transport,
    )


def test_a_missing_openrouter_model_defers_to_the_probe_and_proceeds() -> None:
    probed: list[str] = []
    transport = _Transport()
    client = _client(_engine({}, probed), transport)

    with client, pytest.raises(_ReachedExecution):
        client.evaluate(sf.Model(_TARGET), benchmark="draco")

    # WHY the probe matters: it is the request that makes the Engine ask the
    # gateway to admit the model — without it nothing ever triggers admission.
    assert _TARGET in probed
    assert transport.called is True


@pytest.mark.asyncio
async def test_the_async_path_defers_the_same_way() -> None:
    probed: list[str] = []
    transport = _AsyncTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine({}, probed)),
        run_transport=transport,
    )

    with pytest.raises(_ReachedExecution):
        await client.evaluate(sf.Model(_TARGET), benchmark="draco")
    await client.aclose()

    assert _TARGET in probed
    assert transport.called is True


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("model_not_on_openrouter", "'qwen/qwen2.5-7b-instruct' is not in OpenRouter's catalog"),
        ("provider_not_credentialed", "connect an OpenRouter API key first"),
        ("provider_disabled", "the OpenRouter provider is disabled on this gateway"),
    ],
)
def test_an_engine_refusal_code_reaches_the_user_pre_spend(code: str, message: str) -> None:
    probed: list[str] = []
    transport = _Transport()
    handler = _engine({_TARGET: _admission_refusal(_TARGET, code, message)}, probed)
    client = _client(handler, transport)

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_TARGET), benchmark="draco")

    assert caught.value.code == code
    assert message in str(caught.value)
    assert transport.called is False


def test_an_engine_without_admission_still_refuses_cleanly() -> None:
    # An Engine predating OME-880 (or with the gateway's flag off end-to-end)
    # answers the probe with its plain RFC 9457 404 — the SDK keeps today's
    # wording rather than surfacing a generic contract error.
    probed: list[str] = []
    transport = _Transport()
    client = _client(_engine({_TARGET: _NOT_INSTALLED}, probed), transport)

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_TARGET), benchmark="draco")

    assert caught.value.code == "model_unavailable"
    assert f"Model {_TARGET!r} is not available on this Engine" in str(caught.value)
    assert transport.called is False


@pytest.mark.parametrize(
    "model_id",
    [
        "missing/model",  # not OpenRouter's namespace
        "openrouter/x-ai/grok-4~fast",  # '~' colon escape — the ENGINE refuses it locally
    ],
)
def test_non_admissible_ids_probe_once_and_keep_todays_refusal(model_id: str) -> None:
    # Review F10: the SDK holds no admissibility grammar — even a hopeless id
    # defers to the free probe, and the Engine's local refusal (a plain 404, no
    # gateway dial) decodes into byte-identical wording. One request, $0.
    probed: list[str] = []
    transport = _Transport()
    client = _client(_engine({model_id: _NOT_INSTALLED}, probed), transport)

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(model_id), benchmark="draco")

    assert caught.value.code == "model_unavailable"
    assert f"Model {model_id!r} is not available on this Engine" in str(caught.value)
    assert probed == [model_id]
    assert transport.called is False


def test_a_bare_404_outside_the_probe_stays_a_deployment_diagnosis() -> None:
    # Review F8: only the probe may read a string-detail 404 as "model not
    # available" — on an ordinary details call (a LISTED model, e.g. behind a
    # reverse proxy missing the route) it stays a contract error pointing at the
    # deployment, never at the model id.
    probed: list[str] = []
    handler = _engine({_JUDGE: httpx.Response(404, json={"detail": "Not Found"})}, probed)
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
        run_transport=_Transport(),
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.models.get(_JUDGE)

    assert caught.value.code == "engine_contract_error"
