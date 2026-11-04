"""The `/classify` handler: what reaches the Gateway, and what comes back (OME-1795).

FEATURE: hosted BYOM, Unit 3. The worker sends only the classifier model ID and the caller's text
to the Gateway's `POST /v1/classifications`, under the trusted request scope, and returns the
Gateway's labels and scores once they pass the result contract (spec section 3.2).

STORY: as a granted caller I classify a text with my own classifier, and the Engine neither adds
nor drops anything on the way.

INVARIANT: every refusal here (a malformed request, a seed, a capture or replay run, a model ID
that cannot exist) happens before any Gateway request, so it costs nothing upstream.

WHY the handler is called directly: these checks are about the handler alone. The capture
boundary through the real executor, the url4 registration and the App mount have their own
modules (`test_classification_frozen_copy.py`, `test_classification_world.py`,
`test_classification_hosted.py`).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from frozen_copy_support import capture_scope, replay_scope

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import connector
from screamingface_engine.world.classification import (
    CLASSIFICATION_UNSUPPORTED,
    CLASSIFICATIONS_PATH,
    CLASSIFIER_NOT_FOUND,
    ClassificationEndpoint,
)
from screamingface_engine.world.connector import AigatewayConfig
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.serving import mount_http_status
from url4.core.errors import ResolutionError

pytestmark = pytest.mark.asyncio

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_MODEL = f"{_ENDPOINT}/classifier_v1"
_CALLER = {"X-User-Email": "caller@x.test"}
_MARKER = "synthetic-marker-7f3a"
_TEXT = f"a 'b' \"c\" (d) & e + f\n!g ü {_MARKER} 😀"
_SCORES = [{"label": "LABEL_0", "score": 0.8}, {"label": "LABEL_1", "score": 0.2}]

Step = httpx.Response | BaseException


class _Gateway:
    """Answers each request with the next scripted step (the last repeats) and records it."""

    def __init__(self, *steps: Step) -> None:
        self._steps = list(steps) or [_ok()]
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        step = self._steps[min(len(self.requests), len(self._steps) - 1)]
        self.requests.append(request)
        if isinstance(step, BaseException):
            raise step
        return step

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), base_url="http://aigateway.test"
        )


def _result(**fields: Any) -> dict[str, Any]:
    return {
        "object": "classification",
        "model": _MODEL,
        "contract": "classification-scores-v1",
        "scores": _SCORES,
        **fields,
    }


def _ok(**fields: Any) -> httpx.Response:
    return httpx.Response(200, json=_result(**fields))


def _context(**fields: Any) -> str:
    return json.dumps({"model": _MODEL, "input": _TEXT, **fields})


async def _classify(
    gateway: _Gateway,
    context: str | None = None,
    *,
    intent: str = "classify",
    params: dict[str, str] | None = None,
    scope: RequestScope | None = None,
    cfg: AigatewayConfig | None = None,
) -> str:
    bound = scope if scope is not None else RequestScope(origin="sync", identity_headers=_CALLER)
    async with gateway.client() as client:
        endpoint = ClassificationEndpoint(client, cfg or AigatewayConfig())
        with request_scope(bound):
            return await endpoint(_context() if context is None else context, intent, params or {})


async def _refusal(gateway: _Gateway, context: str | None = None, **kwargs: Any) -> Exception:
    with pytest.raises((RunnerRequestError, ResolutionError)) as caught:
        await _classify(gateway, context, **kwargs)
    return caught.value


# --- what reaches the Gateway -------------------------------------------------------------------


async def test_the_gateway_receives_only_the_model_and_the_exact_input() -> None:
    gateway = _Gateway()

    await _classify(gateway)

    (request,) = gateway.requests
    assert (request.method, request.url.path) == ("POST", CLASSIFICATIONS_PATH)
    assert json.loads(request.content) == {"model": _MODEL, "input": _TEXT}


async def test_the_request_carries_the_callers_identity_and_both_budgets_and_no_key() -> None:
    gateway = _Gateway()
    scope = RequestScope(origin="sync", identity_headers={**_CALLER, "X-Other": "dropped"})

    await _classify(gateway, scope=scope, cfg=AigatewayConfig(timeout_s=12.0, queue_timeout_s=3.0))

    (request,) = gateway.requests
    assert request.headers["X-User-Email"] == _CALLER["X-User-Email"]
    assert request.headers["x-aigw-execution-timeout-s"] == "12.0"
    assert request.headers["x-aigw-queue-timeout-s"] == "3.0"
    assert "Authorization" not in request.headers
    assert "X-Other" not in request.headers


async def test_the_queue_budget_defaults_to_the_execution_budget() -> None:
    gateway = _Gateway()

    await _classify(gateway, cfg=AigatewayConfig(timeout_s=20.0))

    assert gateway.requests[0].headers["x-aigw-queue-timeout-s"] == "20.0"


async def test_a_run_without_an_identity_sends_none() -> None:
    gateway = _Gateway()

    await _classify(gateway, scope=RequestScope(origin="run"))

    assert "X-User-Email" not in gateway.requests[0].headers


# --- what comes back ------------------------------------------------------------------------------


async def test_a_valid_result_comes_back_as_the_contract_in_upstream_order() -> None:
    """Ties stay in upstream order, an integer score stays an integer, and a field outside the
    contract is not passed on."""
    scores = [
        {"label": "B", "score": 0.5},
        {"label": "A", "score": 0.5},
        {"label": "Ünïcode", "score": 0},
        {"label": "D", "score": 1},
    ]
    gateway = _Gateway(_ok(scores=scores, _aigw={"cost_usd": 0.1}))

    body = await _classify(gateway)

    assert json.loads(body) == _result(scores=scores)
    assert "Ünïcode" in body
    assert "_aigw" not in body


_BAD_RESULTS: dict[str, Any] = {
    "not-an-object": [_result()],
    "another-object": _result(object="chat.completion"),
    "another-model": _result(model=f"{_ENDPOINT}/classifier_v2"),
    "another-contract": _result(contract="classification-scores-v2"),
    "no-scores": {k: v for k, v in _result().items() if k != "scores"},
    "scores-not-a-list": _result(scores={"label": "A", "score": 0.5}),
    "empty-scores": _result(scores=[]),
    "two-item-batch": _result(scores=[_SCORES, _SCORES]),
    "item-not-an-object": _result(scores=["A"]),
    "missing-label": _result(scores=[{"score": 0.5}]),
    "empty-label": _result(scores=[{"label": "", "score": 0.5}]),
    "label-not-a-string": _result(scores=[{"label": 3, "score": 0.5}]),
    "duplicate-label": _result(scores=[{"label": "A", "score": 0.5}, {"label": "A", "score": 0.4}]),
    "missing-score": _result(scores=[{"label": "A"}]),
    "boolean-score": _result(scores=[{"label": "A", "score": True}]),
    "string-score": _result(scores=[{"label": "A", "score": "0.5"}]),
    "below-zero": _result(scores=[{"label": "A", "score": -0.1}]),
    "above-one": _result(scores=[{"label": "A", "score": 1.5}]),
}


@pytest.mark.parametrize("document", list(_BAD_RESULTS.values()), ids=list(_BAD_RESULTS))
async def test_a_result_outside_the_contract_is_a_bad_response(document: Any) -> None:
    """INVARIANT (E7): a Gateway fault never reaches the caller as a success."""
    refused = await _refusal(_Gateway(httpx.Response(200, json=document)))

    assert isinstance(refused, RunnerRequestError)
    assert (refused.code, refused.permanent) == ("aigateway_bad_response", True)
    assert _MARKER not in str(refused) and _MODEL not in str(refused)


@pytest.mark.parametrize(
    "score", ["NaN", "Infinity", "-Infinity", "1" + "0" * 400], ids=["nan", "inf", "-inf", "huge"]
)
async def test_a_non_finite_or_huge_score_is_a_bad_response(score: str) -> None:
    # WHY raw text: `json.dumps` refuses to write these, and a Gateway fault is not so polite.
    raw = json.dumps(_result(scores=[{"label": "A", "score": 0.5}])).replace("0.5", score)
    response = httpx.Response(
        200, content=raw.encode(), headers={"content-type": "application/json"}
    )

    refused = await _refusal(_Gateway(response))

    assert isinstance(refused, RunnerRequestError)
    assert refused.code == "aigateway_bad_response"


@pytest.mark.parametrize(
    ("body", "code", "permanent"),
    [
        (b"", "aigateway_empty_response", False),
        (b"<html>login</html>", "aigateway_bad_response", True),
    ],
    ids=["empty", "not-json"],
)
async def test_a_success_body_that_is_not_json_keeps_the_connector_codes(
    body: bytes, code: str, permanent: bool
) -> None:
    refused = await _refusal(_Gateway(httpx.Response(200, content=body)))

    assert (getattr(refused, "code", None), getattr(refused, "permanent", None)) == (
        code,
        permanent,
    )


# --- refusals before any Gateway request ----------------------------------------------------------


_MALFORMED_CONTEXTS = {
    "empty": "",
    "not-json": "ctx",
    "array": json.dumps([_MODEL, _TEXT]),
    "string": json.dumps(_TEXT),
    "missing-input": json.dumps({"model": _MODEL}),
    "missing-model": json.dumps({"input": _TEXT}),
    "extra-field": _context(seed=1),
    "model-not-a-string": json.dumps({"model": 1, "input": _TEXT}),
    "input-not-a-string": json.dumps({"model": _MODEL, "input": None}),
    "duplicate-key": _context()[:-1] + ', "input": "again"}',
    "deeply-nested": "[" * 5000,
    # WHY these two: JSON can spell a lone surrogate, which no UTF-8 request body can carry.
    "lone-surrogate-input": json.dumps({"model": _MODEL, "input": f"{_MARKER} \ud800"}),
    "lone-surrogate-model": json.dumps({"model": f"{_MODEL}\udfff", "input": _TEXT}),
}


@pytest.mark.parametrize(
    "context", list(_MALFORMED_CONTEXTS.values()), ids=list(_MALFORMED_CONTEXTS)
)
async def test_a_malformed_context_is_refused_before_any_gateway_call(context: str) -> None:
    gateway = _Gateway()

    refused = await _refusal(gateway, context)

    assert isinstance(refused, RunnerRequestError)
    assert (refused.code, refused.permanent) == ("malformed_source", True)
    assert mount_http_status(refused.code, permanent=refused.permanent) == 400
    assert _MARKER not in str(refused)
    assert gateway.requests == []


async def test_a_lone_surrogate_is_refused_unchanged_and_unquoted() -> None:
    """The text is neither repaired nor echoed: no replacement character reaches the Gateway,
    and the refusal carries no encoding error that would quote it."""
    gateway = _Gateway()

    refused = await _refusal(gateway, json.dumps({"model": _MODEL, "input": f"a\ud800{_MARKER}"}))

    assert getattr(refused, "code", None) == "malformed_source"
    assert refused.__cause__ is None
    assert refused.__context__ is None or refused.__suppress_context__
    assert _MARKER not in str(refused)
    assert gateway.requests == []


@pytest.mark.parametrize(
    ("intent", "params"),
    [("go", {}), ("", {}), ("classify", {"seed": "5"}), ("classify", {"top_k": "2"})],
    ids=["other-intent", "no-intent", "seed-param", "other-param"],
)
async def test_another_intent_or_any_parameter_is_refused_before_any_gateway_call(
    intent: str, params: dict[str, str]
) -> None:
    """WHY a parameter is refused and not ignored: a dropped `seed` would run a seeded call
    unseeded and still answer as if it had applied."""
    gateway = _Gateway()

    refused = await _refusal(gateway, intent=intent, params=params)

    assert isinstance(refused, RunnerRequestError)
    assert refused.code == "malformed_source"
    assert gateway.requests == []


@pytest.mark.parametrize(
    "scope",
    [
        RequestScope(origin="sync", answer_seed=7),
        RequestScope(origin="sync", answer_seed=0),
        RequestScope(origin="run", answer_seed=7),
        capture_scope(),
        replay_scope(),
    ],
    ids=["seed", "zero-seed", "run-seed", "capture", "replay"],
)
async def test_a_seed_capture_or_replay_scope_is_refused_before_any_gateway_call(
    scope: RequestScope,
) -> None:
    """E4: one Engine code, answered `400` by a mount. Without its status entry a permanent
    Engine code would answer `502`, an upstream failure."""
    gateway = _Gateway()

    refused = await _refusal(gateway, scope=scope)

    assert isinstance(refused, RunnerRequestError)
    assert (refused.code, refused.permanent) == (CLASSIFICATION_UNSUPPORTED, True)
    assert mount_http_status(refused.code, permanent=True) == 400
    assert gateway.requests == []


async def test_the_mode_refusal_comes_before_the_envelope_check() -> None:
    gateway = _Gateway()

    refused = await _refusal(gateway, "ctx", scope=capture_scope())

    assert getattr(refused, "code", None) == CLASSIFICATION_UNSUPPORTED


# --- not found is one answer ----------------------------------------------------------------------


async def _not_found(gateway: _Gateway, model: str = _MODEL) -> RunnerRequestError:
    refused = await _refusal(gateway, json.dumps({"model": model, "input": _TEXT}))
    assert isinstance(refused, RunnerRequestError)
    return refused


async def test_unknown_provider_and_invalid_model_are_one_not_found_answer() -> None:
    """E6: a caller cannot tell an unknown, an ungranted and a chat model ID apart."""
    unknown = await _not_found(
        _Gateway(httpx.Response(400, json={"detail": f"unknown provider: {_ENDPOINT}"}))
    )
    invalid = await _not_found(
        _Gateway(
            httpx.Response(
                400,
                json={
                    "detail": {
                        "code": "invalid_model",
                        "message": "model is not a configured target of this provider",
                    }
                },
            )
        )
    )

    assert (unknown.code, unknown.permanent) == (CLASSIFIER_NOT_FOUND, True)
    assert (invalid.code, invalid.permanent, str(invalid)) == (unknown.code, True, str(unknown))
    assert mount_http_status(unknown.code, permanent=True) == 404
    assert "unknown provider" not in str(unknown) and _ENDPOINT not in str(unknown)
    assert unknown.__cause__ is None and unknown.__suppress_context__


@pytest.mark.parametrize("model", ["classifier_v1", f"{_ENDPOINT}/", "/classifier_v1", ""], ids=str)
async def test_a_model_id_without_a_provider_or_alias_is_not_found_without_a_call(
    model: str,
) -> None:
    gateway = _Gateway()

    refused = await _not_found(gateway, model)

    assert refused.code == CLASSIFIER_NOT_FOUND
    assert gateway.requests == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"detail": "unknown provider: byom_" + "f" * 32}),
        httpx.Response(400, json={"detail": {"code": "unsupported_parameters", "message": "m"}}),
        httpx.Response(404, json={"detail": {"code": "invalid_model", "message": "m"}}),
        httpx.Response(403, json={"detail": f"unknown provider: {_ENDPOINT}"}),
    ],
    ids=["another-provider", "another-code", "another-status", "forbidden"],
)
async def test_any_other_gateway_refusal_is_kept(response: httpx.Response) -> None:
    refused = await _refusal(_Gateway(response))

    assert getattr(refused, "code", None) != CLASSIFIER_NOT_FOUND


# --- retries follow the existing connector rules --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "permanent"), [(429, False), (503, False), (500, False), (401, True)]
)
async def test_429_and_5xx_stay_retryable_and_other_refusals_permanent(
    status: int, permanent: bool
) -> None:
    gateway = _Gateway(httpx.Response(status, json={"detail": {"code": "x", "message": "m"}}))

    refused = await _refusal(gateway)

    assert getattr(refused, "permanent", None) is permanent
    assert len(gateway.requests) == 1


async def test_a_transport_failure_is_retried_once_then_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_BASE_S", 0.0)
    recovered = _Gateway(httpx.ConnectError("refused"), _ok())
    failing = _Gateway(httpx.ConnectError("refused"))

    body = await _classify(recovered)
    refused = await _refusal(failing)

    assert json.loads(body) == _result()
    assert len(recovered.requests) == 2
    assert (getattr(refused, "code", None), getattr(refused, "permanent", None)) == (
        "aigateway_transport_error",
        False,
    )
    assert len(failing.requests) == 2


# --- the run total stays honest (E8) --------------------------------------------------------------


@pytest.fixture
def usage(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every usage record the handler reports, as the keyword arguments it passed."""
    records: list[dict[str, Any]] = []

    def sink(**fields: Any) -> None:
        records.append(fields)

    monkeypatch.setattr(connector, "current_usage_sink", lambda: sink)
    return records


_UNPRICED_CALL = {
    "provider": _ENDPOINT,
    "model": _MODEL,
    "input_tokens": 0,
    "output_tokens": 0,
    "cost_usd": None,
    "image_and_file_tokens": None,
}


async def test_a_dispatched_classification_reports_one_unpriced_call(
    usage: list[dict[str, Any]],
) -> None:
    """E8 as amended (owner, 2026-10-30): a classification answer carries no price, and a call
    that reports nothing is absent from the run total, so it must say its cost is unknown.

    INVARIANT: exactly the unknown-cost signal. The two zero counts are the sink's required
    fields, not measurements; nothing else is stated."""
    await _classify(_Gateway())

    assert usage == [_UNPRICED_CALL]


_DISPATCH_FAILURES: dict[str, Step] = {
    "gateway-5xx": httpx.Response(503, json={"detail": {"code": "x", "message": "m"}}),
    "not-found": httpx.Response(400, json={"detail": {"code": "invalid_model", "message": "m"}}),
    "other-refusal": httpx.Response(401, json={"detail": {"code": "x", "message": "m"}}),
    "bad-result": _ok(scores=[]),
    "not-json": httpx.Response(200, content=b"<html>login</html>"),
}


@pytest.mark.parametrize("step", list(_DISPATCH_FAILURES.values()), ids=list(_DISPATCH_FAILURES))
async def test_a_dispatch_that_fails_still_reports_one_unpriced_call(
    step: Step, usage: list[dict[str, Any]]
) -> None:
    """Once the request is sent, the upstream may have run and billed, whatever came back."""
    await _refusal(_Gateway(step))

    assert usage == [_UNPRICED_CALL]


async def test_a_transport_failure_after_dispatch_reports_one_unpriced_call(
    monkeypatch: pytest.MonkeyPatch, usage: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_BASE_S", 0.0)

    await _refusal(_Gateway(httpx.ReadError("lost")))

    assert usage == [_UNPRICED_CALL]


_BEFORE_DISPATCH: dict[str, dict[str, Any]] = {
    "malformed": {"context": "ctx"},
    "lone-surrogate": {"context": json.dumps({"model": _MODEL, "input": "\ud800"})},
    "other-intent": {"intent": "go"},
    "parameter": {"params": {"seed": "5"}},
    "seed": {"scope": RequestScope(origin="sync", answer_seed=7)},
    "capture": {"scope": capture_scope()},
    "replay": {"scope": replay_scope()},
    "no-alias": {"context": json.dumps({"model": "classifier_v1", "input": _TEXT})},
}


@pytest.mark.parametrize("kwargs", list(_BEFORE_DISPATCH.values()), ids=list(_BEFORE_DISPATCH))
async def test_a_refusal_before_dispatch_reports_no_usage(
    kwargs: dict[str, Any], usage: list[dict[str, Any]]
) -> None:
    gateway = _Gateway()

    await _refusal(gateway, **kwargs)

    assert gateway.requests == []
    assert usage == []
