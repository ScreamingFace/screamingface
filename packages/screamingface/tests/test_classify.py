"""Classify one text with a configured classifier through the Engine's `/classify` (OME-1796).

FEATURE (OME-1796, hosted BYOM Unit 3): `Client.classify` and `sf.classify` send a classifier
model ID and a text to the Engine's one `/classify` endpoint and return the classifier's labels
and scores, in its order. The Engine asks the Gateway, which calls the classifier with the
caller's own Connection.
STORY: as a researcher with my own text classifier connected, I call
`sf.classify("byom_<id>/classifier_v1", text)` and get its labels and scores back, or a plain
reason why not, without ever paying twice for one call.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from url4.wire.subrequest import decode_subrequest

import screamingface as sf
from screamingface._access.auth import _CloudflareAccessAuth
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine.classification import classify_path
from screamingface.classification import Classification, LabelScore
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    PlanningError,
)

_MODEL = "byom_" + "0" * 32 + "/classifier_v1"
_RESULT = {
    "object": "classification",
    "model": _MODEL,
    "contract": "classification-scores-v1",
    "scores": [
        {"label": "LABEL_0", "score": 0.4},
        {"label": "LABEL_1", "score": 0.4},
        {"label": "LABEL_2", "score": 0.2},
    ],
}
_Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: _Handler, requests: list[httpx.Request]) -> sf.Client:
    """A Client whose engine is ``handler``; every request it receives lands in ``requests``."""

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return sf.Client(
        engine_url="http://engine.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(respond),
        save_results=False,
    )


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_RESULT)


def _url4_error(status: int, code: str, message: str = "refused") -> _Handler:
    return lambda _request: httpx.Response(
        status, json={"error": {"code": code, "message": message}}
    )


def _sent_context(request: httpx.Request) -> tuple[str, str]:
    """The ``(context, intent)`` the Engine decodes from the request, as its ingress does."""

    path, _, query = request.url.raw_path.decode("ascii").partition("?")
    assert path == "/classify"
    assert query.startswith("q=")
    return decode_subrequest(query.removeprefix("q="))


def _prefer_wait(prefer: str) -> float | None:
    """The ``wait=`` seconds of a ``Prefer`` header, read as the Engine's mount reads it."""

    wait: float | None = None
    for token in prefer.split(","):
        name, _, value = token.partition("=")
        if name.strip().lower() == "wait":
            wait = float(value.strip())
    return wait


# --- the request ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Great service",
        "1 + 1 = 2 & done",
        'She said "no" (twice), it\'s 100% #1',
        "line one\nline two\ttab",
        "caf\u00e9 \u0436\u0438\u0437\u043d\u044c \u4e2d\u6587 \U0001f600",
        "",
    ],
)
def test_the_text_reaches_the_engine_byte_for_byte(text: str) -> None:
    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client:
        client.classify(_MODEL, text)

    (request,) = requests
    context, intent = _sent_context(request)
    assert intent == "classify"
    # INVARIANT: the context is exactly the two fields; the Engine refuses anything else.
    assert json.loads(context) == {"model": _MODEL, "input": text}
    assert request.method == "GET"


def test_the_call_is_never_marked_safe_to_replay() -> None:
    """WHY: the auth layer re-sends a replay-safe request after an Access re-login, and a
    classification is a paid call that must not run twice."""

    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client:
        client.classify(_MODEL, "text")

    (request,) = requests
    assert request.extensions.get(_REPLAY_SAFE, False) is False


def test_the_call_states_its_wait_and_allows_a_longer_read() -> None:
    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client:
        client.classify(_MODEL, "text")

    (request,) = requests
    assert request.headers["Prefer"] == "wait=30"
    assert request.extensions["timeout"]["read"] == 45.0


@pytest.mark.parametrize("limit_s", [10.0, 30.0, 60.0])
def test_the_engine_answers_before_the_client_gives_up_whatever_its_limit(limit_s: float) -> None:
    """INVARIANT (spec 4.3): the Engine bounds a direct call by min(the request's wait, its own
    configurable limit), so its own `504 timeout` arrives before the client's read timeout."""

    bounds: list[tuple[float, float]] = []

    def engine(request: httpx.Request) -> httpx.Response:
        wait = _prefer_wait(request.headers.get("Prefer", ""))
        bound = limit_s if wait is None else min(wait, limit_s)
        bounds.append((bound, request.extensions["timeout"]["read"]))
        return _url4_error(504, "timeout", "the call did not finish in time; it was stopped")(
            request
        )

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    ((bound, read_timeout),) = bounds
    assert bound < read_timeout
    # WHY not retryable: the Engine stopped a run that may already have called the classifier.
    assert (caught.value.code, caught.value.status, caught.value.retryable) == (
        "timeout",
        504,
        False,
    )


def test_a_dollar_reference_in_the_text_stays_literal() -> None:
    """A direct call substitutes nothing: `$text` reaches the classifier as five characters."""

    text = "$text and $item and $1"
    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client:
        client.classify(_MODEL, text)

    (request,) = requests
    context, _ = _sent_context(request)
    assert json.loads(context)["input"] == text


# --- size ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("character", "largest"),
    [
        ("a", 8075),
        ("\u0436", 1345),
        ('"', 2018),
        ("\u4e2d", 897),
        ("\U0001f600", 672),
    ],
)
def test_the_largest_input_that_fits_is_sent_and_one_more_is_refused_first(
    character: str, largest: int
) -> None:
    """The spec 3.4 table: 8 KiB of encoded path and query, the JSON envelope included."""

    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client:
        client.classify(_MODEL, character * largest)
        assert len(requests[0].url.raw_path) <= 8192
        with pytest.raises(PlanningError) as caught:
            client.classify(_MODEL, character * (largest + 1))

    assert len(requests) == 1
    assert caught.value.code == "uri_too_long"
    assert caught.value.permanent is True
    assert character * largest not in caught.value.message


@pytest.mark.parametrize(("model", "text"), [(None, "text"), (_MODEL, None), (_MODEL, 3)])
def test_a_non_string_model_or_input_is_refused_before_any_request(model: Any, text: Any) -> None:
    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client, pytest.raises(TypeError):
        client.classify(model, text)
    assert requests == []


@pytest.mark.parametrize(
    ("model", "text", "field"),
    [
        (_MODEL, "secret a\ud800b", "input text"),
        (_MODEL, "secret \udfff", "input text"),
        (_MODEL[:-1] + "\udc00", "secret text", "model ID"),
    ],
)
def test_text_that_utf8_cannot_encode_is_refused_before_any_request(
    model: str, text: str, field: str
) -> None:
    """INVARIANT: a lone surrogate is the caller's malformed input, refused by the code the Engine
    answers for it, and the refusal never carries the text it refused."""

    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client, pytest.raises(PlanningError) as caught:
        client.classify(model, text)

    error = caught.value
    assert requests == []
    assert (error.code, error.permanent) == ("malformed_source", True)
    assert field in error.message
    rendered = " ".join([str(error), repr(error.args), error.message, str(error.details)])
    assert "secret" not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


# --- the result ----------------------------------------------------------------------------


def test_the_result_keeps_the_classifiers_order_and_ties() -> None:
    with _client(_ok, []) as client:
        result = client.classify(_MODEL, "text")

    assert result == Classification(
        model=_MODEL,
        contract="classification-scores-v1",
        scores=(
            LabelScore(label="LABEL_0", score=0.4),
            LabelScore(label="LABEL_1", score=0.4),
            LabelScore(label="LABEL_2", score=0.2),
        ),
    )


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        json.dumps({**_RESULT, "object": "chat.completion"}).encode(),
        json.dumps({**_RESULT, "model": 1}).encode(),
        json.dumps({**_RESULT, "contract": None}).encode(),
        json.dumps({**_RESULT, "scores": []}).encode(),
        json.dumps({**_RESULT, "scores": {"label": "a", "score": 1}}).encode(),
        json.dumps({**_RESULT, "scores": [["a", 1]]}).encode(),
        json.dumps({**_RESULT, "scores": [{"label": "", "score": 0.5}]}).encode(),
        json.dumps({**_RESULT, "scores": [{"label": 1, "score": 0.5}]}).encode(),
        json.dumps({**_RESULT, "scores": [{"label": "a", "score": True}]}).encode(),
        json.dumps({**_RESULT, "scores": [{"label": "a", "score": "0.5"}]}).encode(),
        b'{"object":"classification","model":"m","contract":"c",'
        b'"scores":[{"label":"a","score":NaN}]}',
        b'{"object":"classification","model":"m","contract":"c",'
        b'"scores":[{"label":"a","score":Infinity}]}',
    ],
)
def test_a_malformed_success_body_is_never_returned(body: bytes) -> None:
    def engine(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    assert caught.value.code == "engine_contract_error"
    assert caught.value.permanent is True


def test_a_score_past_the_float_range_is_a_contract_error() -> None:
    """An integer too large for a float fails as a malformed answer, not as a raw OverflowError."""

    body = (
        b'{"object":"classification","model":"m","contract":"c",'
        b'"scores":[{"label":"a","score":1' + b"0" * 400 + b"}]}"
    )

    def engine(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    assert (caught.value.code, caught.value.permanent) == ("engine_contract_error", True)


def test_an_integer_score_is_a_number() -> None:
    result_body = {**_RESULT, "scores": [{"label": "a", "score": 1}]}
    with _client(lambda _r: httpx.Response(200, json=result_body), []) as client:
        result = client.classify(_MODEL, "text")
    assert result.scores == (LabelScore(label="a", score=1.0),)


def test_a_large_result_is_fetched_from_its_artifact() -> None:
    """The Engine spills a result over its inline limit and answers `303` to a signed path."""

    location = "/artifacts/0123abcd?exp=1767225600&sig=c2lnbmF0dXJl"

    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/classify":
            return httpx.Response(303, headers={"Location": location})
        return httpx.Response(200, json=_RESULT)

    requests: list[httpx.Request] = []
    with _client(engine, requests) as client:
        result = client.classify(_MODEL, "text")

    assert [request.url.raw_path.decode() for request in requests][1] == location
    assert result.scores[0] == LabelScore(label="LABEL_0", score=0.4)
    assert all(request.extensions.get(_REPLAY_SAFE, False) is False for request in requests)


@pytest.mark.parametrize(
    "location",
    ["https://elsewhere.test/artifacts/0123", "//elsewhere.test/artifacts/0123", "/v1/x", ""],
)
def test_a_redirect_off_the_artifact_path_is_never_followed(location: str) -> None:
    requests: list[httpx.Request] = []
    with (
        _client(lambda _r: httpx.Response(303, headers={"Location": location}), requests) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert len(requests) == 1
    assert caught.value.code == "engine_contract_error"


# Each would reach a path other than one artifact once httpx removes its dot segments, a server
# decodes it, or a client resolves it against an origin; the first one names `/classify` itself.
_OFF_ROUTE_LOCATIONS: dict[str, str] = {
    "dot-segment-to-classify": "/artifacts/.." + classify_path(_MODEL, "text"),
    "nested-dot-segments": "/artifacts/0123/../../classify?q=x",
    "single-dot-segment": "/artifacts/./0123?exp=1&sig=x",
    "encoded-dot-segment": "/artifacts/%2e%2e/classify?q=x",
    "mixed-case-encoded-dot": "/artifacts/.%2E/classify?q=x",
    "encoded-slash": "/artifacts/0123%2F..%2Fclassify?exp=1&sig=x",
    "backslash": "/artifacts\\..\\classify?q=x",
    "same-origin-absolute": "http://engine.test/artifacts/0123?exp=1&sig=x",
    "network-path": "//engine.test/artifacts/0123?exp=1&sig=x",
    "extra-segment": "/artifacts/0123/x?exp=1&sig=x",
    "unsigned": "/artifacts/0123",
    "fragment": "/artifacts/0123?exp=1&sig=x#/../classify",
}


@pytest.mark.parametrize("location", _OFF_ROUTE_LOCATIONS.values(), ids=_OFF_ROUTE_LOCATIONS.keys())
def test_a_redirect_is_followed_only_to_one_signed_artifact(location: str) -> None:
    """INVARIANT: one call is never sent twice. httpx resolves `/artifacts/../classify` to
    `/classify`, so the `Location` is checked as it arrived, before any URL handling."""

    requests: list[httpx.Request] = []

    def engine(request: httpx.Request) -> httpx.Response:
        # WHY a second `/classify` succeeds: a classifier run again answers as it did before.
        if request.url.path == "/classify" and len(requests) == 1:
            return httpx.Response(303, headers={"Location": location})
        return httpx.Response(200, json=_RESULT)

    with _client(engine, requests) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    assert [request.url.path for request in requests] == ["/classify"]
    error = caught.value
    assert (error.code, error.status, error.retryable) == ("engine_contract_error", 303, False)


def test_the_engine_s_own_signed_location_is_followed() -> None:
    """The exact form the Engine's `signed_artifact_path` writes: a sha256 id, `exp` and `sig`."""

    location = f"/artifacts/{'ab' * 32}?exp=1767225600&sig={'0f' * 32}"

    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/classify":
            return httpx.Response(303, headers={"Location": location})
        return httpx.Response(200, json=_RESULT)

    requests: list[httpx.Request] = []
    with _client(engine, requests) as client:
        result = client.classify(_MODEL, "text")

    assert [request.url.path for request in requests] == ["/classify", f"/artifacts/{'ab' * 32}"]
    assert requests[1].url.raw_path.decode() == location
    assert result.scores == tuple(LabelScore(**item) for item in _RESULT["scores"])


def test_a_negative_score_past_the_float_range_is_a_contract_error() -> None:
    body = (
        b'{"object":"classification","model":"m","contract":"c",'
        b'"scores":[{"label":"a","score":-1' + b"0" * 400 + b"}]}"
    )

    def engine(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    assert (caught.value.code, caught.value.retryable) == ("engine_contract_error", False)


def test_the_integer_scores_zero_and_one_are_numbers() -> None:
    result_body = {**_RESULT, "scores": [{"label": "a", "score": 0}, {"label": "b", "score": 1}]}
    with _client(lambda _r: httpx.Response(200, json=result_body), []) as client:
        result = client.classify(_MODEL, "text")

    assert result.scores == (LabelScore(label="a", score=0.0), LabelScore(label="b", score=1.0))
    assert [type(item.score) for item in result.scores] == [float, float]


def test_an_artifact_the_engine_no_longer_holds_fails_by_name() -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/classify":
            return httpx.Response(303, headers={"Location": "/artifacts/0123?exp=1&sig=x"})
        return httpx.Response(404, json={"title": "Result artifact unavailable"})

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    assert (caught.value.code, caught.value.status, caught.value.permanent) == (
        "result_unavailable",
        404,
        True,
    )


@pytest.mark.parametrize(
    "artifact",
    [
        pytest.param(lambda _r: httpx.Response(500, text="boom"), id="500"),
        pytest.param(_url4_error(502, "artifact_spill_failed"), id="502"),
        pytest.param(
            lambda _r: httpx.Response(503, text="busy", headers={"Retry-After": "1"}), id="503"
        ),
        pytest.param(_url4_error(429, "rate_limited"), id="429"),
    ],
)
def test_a_failed_artifact_fetch_after_a_run_is_not_retryable(artifact: _Handler) -> None:
    """INVARIANT: after a `303` the classification has run. Fetching its result again and
    classifying again are different acts, and only the second one bills."""

    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/classify":
            return httpx.Response(303, headers={"Location": "/artifacts/0123?exp=1&sig=x"})
        return artifact(request)

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    error = caught.value
    assert (error.code, error.retryable) == ("result_unavailable", False)
    assert "ran" in error.message
    assert error.hint is not None and "again" in error.hint


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_an_artifact_fetch_that_cannot_connect_is_still_not_retryable(
    failure: type[httpx.TransportError],
) -> None:
    """Even a connect-phase failure: the classification itself already ran."""

    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/classify":
            return httpx.Response(303, headers={"Location": "/artifacts/0123?exp=1&sig=x"})
        raise failure("lost", request=request)

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    error = caught.value
    assert not isinstance(error, EngineUnavailableError)
    assert (error.code, error.retryable) == ("result_unavailable", False)
    assert isinstance(error.__cause__, failure)


_SIGNED = "/artifacts/" + "ab" * 32 + "?exp=1&sig=" + "0f" * 32


def _behind_access(
    monkeypatch: pytest.MonkeyPatch, artifact_answers: list[httpx.Response]
) -> tuple[sf.Client, list[httpx.Request]]:
    """An https Client whose `/classify` answers `303`; Access logs in without a browser."""

    monkeypatch.setattr(
        _CloudflareAccessAuth, "_authenticate_after_redirect", lambda *_args, **_kwargs: None
    )
    answers = iter(artifact_answers)
    requests: list[httpx.Request] = []

    def engine(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/classify":
            return httpx.Response(303, headers={"Location": _SIGNED})
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


def test_an_access_login_during_the_artifact_fetch_still_returns_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: Access stops a challenged request at the edge, so the fetch never reached the Engine.
    After the login the result is fetched once more; the classification is never sent again."""

    client, requests = _behind_access(
        monkeypatch, [_challenge(), httpx.Response(200, json=_RESULT)]
    )
    with client:
        result = client.classify(_MODEL, "text")

    artifact = _SIGNED.split("?")[0]
    assert [request.url.path for request in requests] == ["/classify", artifact, artifact]
    assert result.scores[0] == LabelScore(label="LABEL_0", score=0.4)
    assert all(request.extensions.get(_REPLAY_SAFE, False) is False for request in requests)


def test_a_second_access_challenge_on_the_artifact_is_not_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: once the `303` arrived, no failure to read the result may advise a retry."""

    client, requests = _behind_access(monkeypatch, [_challenge(), _challenge()])
    with client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    error = caught.value
    assert [request.url.path for request in requests].count("/classify") == 1
    assert (error.code, error.retryable) == ("result_unavailable", False)
    assert error.hint is not None and "again" in error.hint


def test_an_artifact_past_the_read_limit_is_a_result_that_ran() -> None:
    def engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/classify":
            return httpx.Response(303, headers={"Location": _SIGNED})
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))

    with _client(engine, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    assert (caught.value.code, caught.value.retryable) == ("result_unavailable", False)


@pytest.mark.parametrize("status", [404, 502])
def test_a_run_whose_result_is_gone_is_a_result_that_ran(status: int) -> None:
    """The Engine answers `result_unavailable` for a run that finished but whose result it cannot
    serve; the classifier ran, so this is not a refusal of the request."""

    with (
        _client(_url4_error(status, "result_unavailable"), []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    error = caught.value
    assert not isinstance(error, PlanningError)
    assert (error.code, error.status, error.retryable) == ("result_unavailable", status, False)
    assert "ran" in error.message
    assert error.hint is not None and "again" in error.hint


@pytest.mark.parametrize("status", [200, 502])
def test_a_body_past_the_read_limit_is_refused(status: int) -> None:
    """A bounded read: the client never buffers an unbounded answer."""

    huge = b"x" * (2 * 1024 * 1024 + 1)
    with (
        _client(lambda _r: httpx.Response(status, content=huge), []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert caught.value.code == "result_too_large"


# --- errors --------------------------------------------------------------------------------


def test_an_engine_without_the_endpoint_raises_the_capability_error() -> None:
    """An older Engine answers FastAPI's plain `404` on `/classify`; no paid call was made."""

    requests: list[httpx.Request] = []
    with (
        _client(lambda _r: httpx.Response(404, json={"detail": "Not Found"}), requests) as client,
        pytest.raises(EngineCapabilityError) as caught,
    ):
        client.classify(_MODEL, "text")

    error = caught.value
    assert len(requests) == 1
    assert (error.code, error.status, error.permanent) == ("engine_capability_missing", 404, True)
    assert error.details == {"path": "/classify"}
    assert error.hint is not None and "/classify" in error.hint


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (404, "classifier_not_found"),
        (400, "malformed_source"),
        (400, "capture_unsupported"),
        (414, "uri_too_long"),
    ],
)
def test_an_engine_refusal_keeps_its_code(status: int, code: str) -> None:
    with (
        _client(_url4_error(status, code, "fixed engine text"), []) as client,
        pytest.raises(PlanningError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert not isinstance(caught.value, EngineCapabilityError)
    assert (caught.value.code, caught.value.status, caught.value.permanent) == (code, status, True)
    assert "fixed engine text" in caught.value.message


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (502, "aigateway_bad_response"),
        (502, "profile_not_found"),
        (502, "aigateway_transport_error"),
        (503, "overloaded"),
        (504, "timeout"),
        (500, "internal_error"),
    ],
)
def test_a_server_failure_after_the_call_may_have_run_is_not_retryable(
    status: int, code: str
) -> None:
    """INVARIANT: the Engine answers 502 for a permanent refusal and for a transient one alike,
    and a run it stopped may already have called the classifier. Classifying again is a new paid
    call, so the SDK never recommends it unless the Engine says nothing ran."""

    with (
        _client(_url4_error(status, code), []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    error = caught.value
    assert (error.code, error.status, error.retryable) == (code, status, False)
    assert "may have run" in error.message
    assert error.hint is not None and "again" in error.hint


def test_a_server_failure_without_an_envelope_is_not_retryable() -> None:
    with (
        _client(lambda _r: httpx.Response(500, text="Internal Server Error"), []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert (caught.value.status, caught.value.retryable) == (500, False)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_url4_error(429, "rate_limited"), id="429"),
        pytest.param(
            lambda _r: httpx.Response(
                503,
                json={"title": "Service Unavailable", "detail": "the runner is at capacity"},
                headers={"Retry-After": "7"},
            ),
            id="503-at-capacity",
        ),
    ],
)
def test_a_refusal_before_anything_ran_is_retryable(answer: _Handler) -> None:
    """A rate limit and a runner at capacity both refuse before any run."""

    with (
        _client(answer, []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert caught.value.retryable is True
    assert "may have run" not in caught.value.message


@pytest.mark.parametrize("code", ["x.admission_timeout", "admission_timeout"])
def test_an_admission_timeout_without_retry_after_may_have_run(code: str) -> None:
    """WHY: url4 raises it only in an expression's `;t=` guard, which `/classify` never runs, so
    on this call such a `503` is relayed from inside a run like any other."""

    with (
        _client(_url4_error(503, code), []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert caught.value.retryable is False
    assert "may have run" in caught.value.message


def test_a_result_too_large_for_the_engine_is_permanent() -> None:
    with (
        _client(_url4_error(413, "result_too_large"), []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert not isinstance(caught.value, PlanningError)
    assert (caught.value.code, caught.value.permanent) == ("result_too_large", True)


@pytest.mark.parametrize("status", [401, 403])
def test_an_unauthenticated_call_raises_the_authentication_error(status: int) -> None:
    with (
        _client(_url4_error(status, "identity_access_denied"), []) as client,
        pytest.raises(AuthenticationError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert (caught.value.code, caught.value.status) == ("identity_access_denied", status)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_an_unreachable_engine_raises_engine_unavailable(
    failure: type[httpx.TransportError],
) -> None:
    """A connect-phase failure never sent the request, so retrying it is safe."""

    def offline(request: httpx.Request) -> httpx.Response:
        raise failure("offline", request=request)

    with _client(offline, []) as client, pytest.raises(EngineUnavailableError) as caught:
        client.classify(_MODEL, "text")

    assert caught.value.engine_url == "http://engine.test"
    assert caught.value.retryable is True


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout,
        httpx.ReadError,
        httpx.WriteError,
        httpx.WriteTimeout,
        httpx.RemoteProtocolError,
    ],
)
def test_a_connection_lost_after_sending_leaves_the_outcome_unknown(
    failure: type[httpx.TransportError],
) -> None:
    """WHY not EngineUnavailableError: the request left the client, so the classification may
    have run and been billed; that error tells the caller a retry is safe."""

    def lost(request: httpx.Request) -> httpx.Response:
        raise failure("lost", request=request)

    with _client(lost, []) as client, pytest.raises(ExecutionError) as caught:
        client.classify(_MODEL, "text")

    error = caught.value
    assert not isinstance(error, EngineUnavailableError)
    assert (error.code, error.retryable) == ("classification_outcome_unknown", False)
    assert "may have run" in error.message
    assert isinstance(error.__cause__, failure)


class _BrokenStream(httpx.SyncByteStream):
    """A body that breaks after the status line arrived."""

    def __iter__(self) -> Iterator[bytes]:
        yield b'{"object":'
        raise httpx.ReadError("connection reset")


def test_a_body_that_breaks_after_the_status_leaves_the_outcome_unknown() -> None:
    with (
        _client(lambda _r: httpx.Response(200, stream=_BrokenStream()), []) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.classify(_MODEL, "text")

    assert (caught.value.code, caught.value.retryable) == ("classification_outcome_unknown", False)


def test_a_closed_client_refuses_to_classify() -> None:
    requests: list[httpx.Request] = []
    client = _client(_ok, requests)
    client.close()
    with pytest.raises(RuntimeError):
        client.classify(_MODEL, "text")
    assert requests == []


# --- the module-level call -----------------------------------------------------------------


def test_sf_classify_uses_the_process_wide_client(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    with _client(_ok, requests) as client:
        monkeypatch.setattr("screamingface._default_client.default_client", lambda: client)
        result = sf.classify(_MODEL, "text")

    assert len(requests) == 1
    assert isinstance(result, sf.Classification)
    assert result.scores[2] == sf.LabelScore(label="LABEL_2", score=0.2)
