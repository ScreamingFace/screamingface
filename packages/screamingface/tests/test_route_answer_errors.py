"""Every `/route-answer` answer other than a result, as `Client.route_answer` raises it (OME-1823).

FEATURE (BYOM routing pilot, spec 3.6): each row of the SDK error table, and the artifact path a
large result takes.

INVARIANT: one call, never re-sent. Only a connect-phase failure, an ingress `429` and
`routing_preflight_unavailable` are retryable; nothing ran before any of them. Every other error
after sending says that asking again may run and bill the classifier, and the selected model,
again, except a refused preflight, before which no model ran.
"""

from __future__ import annotations

import httpx
import pytest
from _route_answer_fixtures import (
    PROFILE,
    RERUN_HINT,
    SIGNED,
    Handler,
    answering,
    envelope,
    route,
    route_error,
    routed_result,
)

import screamingface as sf
from screamingface._access.auth import _CloudflareAccessAuth
from screamingface._core.wire import _REPLAY_SAFE
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    PlanningError,
)
from screamingface.routing import RoutedAnswer

# --- the error table (spec 3.6) ---------------------------------------------------------------


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_an_engine_that_cannot_be_reached_is_unavailable_and_retryable(
    failure: type[httpx.TransportError],
) -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        raise failure("unreachable", request=request)

    error = route_error(engine)

    assert isinstance(error, EngineUnavailableError)
    assert error.retryable is True


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError, httpx.WriteError]
)
def test_a_failure_after_sending_leaves_the_outcome_unknown(
    failure: type[httpx.TransportError],
) -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        raise failure("lost", request=request)

    error = route_error(engine)

    assert isinstance(error, ExecutionError)
    assert (error.code, error.retryable, error.hint) == (
        "routed_answer_outcome_unknown",
        False,
        RERUN_HINT,
    )


def test_an_engine_without_the_route_raises_the_capability_error() -> None:
    error = route_error(lambda _request: httpx.Response(404, text="Not Found"))

    assert isinstance(error, EngineCapabilityError)
    assert (error.status, error.retryable) == (404, False)
    assert error.details == {"path": "/route-answer"}


@pytest.mark.parametrize("status", [401, 403])
def test_an_unauthenticated_call_raises_the_authentication_error(status: int) -> None:
    error = route_error(answering(status, envelope("identity_access_denied")))

    assert isinstance(error, AuthenticationError)
    assert (error.code, error.status, error.retryable) == ("identity_access_denied", status, False)


def test_an_unavailable_preflight_is_retryable_because_nothing_ran() -> None:
    error = route_error(answering(502, envelope("routing_preflight_unavailable")))

    assert isinstance(error, ExecutionError)
    assert (error.code, error.status, error.retryable) == (
        "routing_preflight_unavailable",
        502,
        True,
    )


@pytest.mark.parametrize("code", ["routing_preflight_failed", "routing_profile_mismatch"])
def test_a_refused_preflight_is_permanent_and_says_nothing_ran(code: str) -> None:
    error = route_error(answering(502, envelope(code)))

    assert isinstance(error, ExecutionError)
    assert (error.code, error.retryable, error.hint) == (code, False, None)
    assert "before any model ran" in error.message


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "malformed_source"),
        (400, "routing_unsupported"),
        (404, "routing_profile_not_found"),
        (409, "routing_connection_missing"),
        (414, "uri_too_long"),
    ],
)
def test_an_engine_refusal_keeps_its_code(status: int, code: str) -> None:
    error = route_error(answering(status, envelope(code, "no routing profile with this ID")))

    assert isinstance(error, PlanningError)
    assert (error.code, error.status, error.retryable) == (code, status, False)
    assert "no routing profile with this ID" in error.message


def test_an_unknown_profile_warns_that_the_classifier_may_have_run() -> None:
    """Spec 6.1 C10: the one 404 also answers access lost after the classifier ran and billed.

    INVARIANT: the 404 stays the same for an unknown and an ungranted profile, so the SDK cannot
    tell which; the rerun and billing hint goes on every one, and it is safe when nothing ran.
    """
    answer = answering(404, envelope("routing_profile_not_found", "no routing profile"))

    error = route_error(answer)

    assert isinstance(error, PlanningError)
    assert (error.code, error.status, error.retryable, error.hint) == (
        "routing_profile_not_found",
        404,
        False,
        RERUN_HINT,
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "malformed_source"), (409, "routing_connection_missing"), (414, "uri_too_long")],
)
def test_a_refusal_before_any_model_carries_no_rerun_hint(status: int, code: str) -> None:
    error = route_error(answering(status, envelope(code, "refused")))

    assert error.hint != RERUN_HINT


@pytest.mark.parametrize(
    "answer",
    [answering(429, envelope("rate_limited")), answering(429, None, **{"Retry-After": "3"})],
    ids=["envelope", "plain"],
)
def test_an_ingress_rate_limit_is_retryable(answer: Handler) -> None:
    error = route_error(answer)

    assert isinstance(error, ExecutionError)
    assert (error.status, error.retryable) == (429, True)


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "1"}], ids=["bare", "retry-after"])
def test_a_503_is_not_retryable_even_with_retry_after(headers: dict[str, str]) -> None:
    """WHY: a queue-publish `503` may follow a run stored behind a lost acknowledgement, and
    asking again could bill two models twice."""

    error = route_error(answering(503, envelope("server_busy"), **headers))

    assert isinstance(error, ExecutionError)
    assert (error.code, error.retryable, error.hint) == ("server_busy", False, RERUN_HINT)


@pytest.mark.parametrize("status", [404, 502])
def test_a_run_whose_result_is_gone_is_a_result_that_ran(status: int) -> None:
    error = route_error(answering(status, envelope("result_unavailable")))

    assert isinstance(error, ExecutionError)
    assert (error.code, error.status, error.retryable, error.hint) == (
        "result_unavailable",
        status,
        False,
        RERUN_HINT,
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (422, "routing_ambiguous"),
        (502, "routing_invalid_scores"),
        (502, "aigateway_http_429"),
        (502, "aigateway_bad_response"),
        (502, "model_token_cap"),
        (504, "timeout"),
        (500, None),
    ],
)
def test_any_other_answer_may_have_run_and_is_not_retryable(status: int, code: str | None) -> None:
    body = None if code is None else envelope(code)

    error = route_error(answering(status, body))

    assert isinstance(error, ExecutionError)
    # WHY `execution_failed` without an envelope: there is no Engine code to keep, so the
    # error class's own default stands.
    expected = code or "execution_failed"
    assert (error.code, error.status, error.retryable, error.hint) == (
        expected,
        status,
        False,
        RERUN_HINT,
    )


@pytest.mark.parametrize("code", ["aigateway_http_400", "aigateway_http_404", "model_token_cap"])
def test_a_gateway_failure_after_a_model_ran_is_never_a_refusal(code: str) -> None:
    """Review P3: the Engine answers a Gateway failure relayed after the classifier call as `502`,
    so the caller is told the models may have run and billed, not that the request was refused."""

    error = route_error(answering(502, envelope(code, "after-send failure")))

    assert isinstance(error, ExecutionError)
    assert not isinstance(error, (PlanningError, AuthenticationError))
    assert (error.code, error.status, error.retryable, error.hint) == (code, 502, False, RERUN_HINT)
    assert "may have run" in error.message


@pytest.mark.parametrize("status", [200, 502])
def test_a_body_past_the_read_limit_is_refused(status: int) -> None:
    error = route_error(
        lambda _request: httpx.Response(status, content=b"x" * (2 * 1024 * 1024 + 1))
    )

    assert isinstance(error, ExecutionError)
    assert (error.code, error.retryable) == ("result_too_large", False)
    assert "routed answer" in error.message


# --- the artifact path ------------------------------------------------------------------------


def test_a_large_result_is_fetched_once_from_its_signed_artifact() -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/route-answer":
            return httpx.Response(303, headers={"Location": SIGNED})
        return httpx.Response(200, json=routed_result())

    result, requests = route(engine)

    assert isinstance(result, RoutedAnswer)
    assert [request.url.path for request in requests] == ["/route-answer", SIGNED.split("?")[0]]
    assert requests[1].url.raw_path.decode() == SIGNED


@pytest.mark.parametrize(
    "location",
    [
        "/artifacts/../route-answer?q=x",
        "https://elsewhere.test/artifacts/ab?exp=1&sig=s",
        "/route-answer?q=x",
        "/artifacts/ab",
        "",
    ],
    ids=["dot-segment", "other-origin", "the-route", "unsigned", "missing"],
)
def test_a_redirect_off_the_artifact_path_is_never_followed(location: str) -> None:
    error = route_error(answering(303, None, Location=location) if location else answering(303))

    assert isinstance(error, ExecutionError)
    assert (error.code, error.status, error.retryable) == ("engine_contract_error", 303, False)


def test_an_artifact_the_engine_no_longer_holds_is_a_result_that_ran() -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/route-answer":
            return httpx.Response(303, headers={"Location": SIGNED})
        return httpx.Response(404, json=envelope("result_unavailable"))

    outcome, requests = route(engine)

    assert isinstance(outcome, ExecutionError)
    assert [request.url.path for request in requests].count("/route-answer") == 1
    assert (outcome.code, outcome.retryable, outcome.hint) == (
        "result_unavailable",
        False,
        RERUN_HINT,
    )


def _behind_access(
    monkeypatch: pytest.MonkeyPatch, artifact_answers: list[httpx.Response]
) -> tuple[sf.Client, list[httpx.Request]]:
    """An https Client whose `/route-answer` answers `303`; Access logs in without a browser."""

    monkeypatch.setattr(
        _CloudflareAccessAuth, "_authenticate_after_redirect", lambda *_args, **_kwargs: None
    )
    answers = iter(artifact_answers)
    requests: list[httpx.Request] = []

    def engine(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/route-answer":
            return httpx.Response(303, headers={"Location": SIGNED})
        return next(answers)

    client = sf.Client(
        engine_url="https://engine.test",
        scoreboard_url="https://scoreboard.test",
        http_transport=httpx.MockTransport(engine),
        save_results=False,
    )
    return client, requests


def _challenge() -> httpx.Response:
    return httpx.Response(403, headers={"cf-access-aud": "a" * 64})


def test_an_access_login_during_the_artifact_fetch_refetches_it_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY once: Access stops a challenged request at its edge, so the fetch never reached the
    Engine; the routed answer itself is never sent again."""

    client, requests = _behind_access(
        monkeypatch, [_challenge(), httpx.Response(200, json=routed_result())]
    )
    with client:
        result = client.route_answer(PROFILE, "question")

    artifact = SIGNED.split("?")[0]
    assert [request.url.path for request in requests] == ["/route-answer", artifact, artifact]
    assert result.selected_label == "code"
    assert all(request.extensions.get(_REPLAY_SAFE, False) is False for request in requests)


def test_a_second_access_challenge_on_the_artifact_is_not_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, requests = _behind_access(monkeypatch, [_challenge(), _challenge()])
    with client, pytest.raises(ExecutionError) as caught:
        client.route_answer(PROFILE, "question")

    assert [request.url.path for request in requests].count("/route-answer") == 1
    assert (caught.value.code, caught.value.retryable) == ("result_unavailable", False)
