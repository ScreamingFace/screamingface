"""EB-1 to EB-4 and EB-6: InferenceClient.endpoint() with a sync Client (contracts C1.5, C5)."""

from __future__ import annotations

import logging
from types import MappingProxyType

import httpx
import pytest
from _chat_engine import (
    CAND,
    CATALOG,
    CHAT_PATH,
    ENGINE_URL,
    EVAL,
    catalogue_engine,
    fusion,
    model,
    ok,
    recording_client,
    sent_body,
    vote,
)
from _endpoint_access import (
    HOSTED_URL,
    TOKEN_HEADER,
    fake_access,
    hosted_client,
    no_access,
    signed_in,
)

import screamingface as sf
from screamingface import _default_client
from screamingface._evaluation.candidate import compile_candidate
from screamingface.errors import AuthenticationError, EngineCapabilityError
from screamingface.inference import InferenceClient, InferenceEndpoint


def _no_login(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("login on a local Engine")


def test_endpoint_text_form_hides_header_values() -> None:
    secret = "secret-token-value"
    e = InferenceEndpoint(
        base_url="https://engine.test/v1", model="openrouter/a", headers={TOKEN_HEADER: secret}
    )
    expected = (
        "InferenceEndpoint(base_url='https://engine.test/v1', model='openrouter/a', "
        "headers={'Cf-Access-Token': '***'})"
    )
    assert repr(e) == expected
    assert str(e) == expected
    assert f"{e}" == expected
    assert secret not in repr(e) + str(e)


def test_endpoint_text_form_with_no_headers() -> None:
    e = InferenceEndpoint(base_url="http://engine.test/v1", model="m", headers={})
    assert repr(e) == "InferenceEndpoint(base_url='http://engine.test/v1', model='m', headers={})"


def test_hosted_endpoint_shows_no_token_in_text_or_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    token, browser = signed_in(monkeypatch)
    requests: list[httpx.Request] = []
    with hosted_client(ok, requests) as client:
        with caplog.at_level(logging.DEBUG):
            e = InferenceClient("openrouter/a", client=client).endpoint()

    assert TOKEN_HEADER in repr(e)
    assert token not in repr(e)
    assert token not in str(e)
    assert token not in caplog.text
    assert browser == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("openrouter/a", "openrouter/a", id="model-id"),
        pytest.param(sf.Url4(EVAL), CAND, id="evaluation-url4"),
        pytest.param(model(), CAND, id="recipe"),
    ],
)
def test_endpoint_values_for_a_local_client(
    monkeypatch: pytest.MonkeyPatch, source: sf.Recipe | sf.Url4 | str, expected: str
) -> None:
    monkeypatch.setattr(sf.Client, "login", _no_login)
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        e = InferenceClient(source, client=client).endpoint()

    assert e.base_url == f"{ENGINE_URL}/v1"
    assert e.model == expected
    assert dict(e.headers) == {}
    assert isinstance(e.headers, MappingProxyType)
    assert requests == []


def test_endpoint_values_for_a_hosted_client(monkeypatch: pytest.MonkeyPatch) -> None:
    token, browser = signed_in(monkeypatch)
    requests: list[httpx.Request] = []
    with hosted_client(ok, requests) as client:
        e = InferenceClient("openrouter/a", client=client).endpoint()

    assert e.base_url == f"{HOSTED_URL}/v1"
    assert e.model == "openrouter/a"
    # WHY one header only: the other headers of the client (User-Agent, traceparent) are not
    # part of the bridge.
    assert dict(e.headers) == {TOKEN_HEADER: token}
    assert browser == []
    assert requests == []


@pytest.mark.parametrize("hosted", [False, True], ids=["local", "hosted"])
def test_endpoint_values_work_with_a_plain_http_post(
    monkeypatch: pytest.MonkeyPatch, hosted: bool
) -> None:
    token = signed_in(monkeypatch)[0] if hosted else None
    sink: list[httpx.Request] = []
    if hosted:
        client = hosted_client(ok, sink)
    else:
        client = recording_client(ok, sink)

    with client:
        e = InferenceClient("openrouter/a", client=client).endpoint()
        engine_requests: list[httpx.Request] = []

        def engine(request: httpx.Request) -> httpx.Response:
            engine_requests.append(request)
            return ok(request)

        with httpx.Client(transport=httpx.MockTransport(engine)) as plain:
            response = plain.post(
                f"{e.base_url}/chat/completions",
                headers=dict(e.headers),
                json={
                    "model": e.model,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

    assert response.status_code == 200
    (request,) = engine_requests
    assert str(request.url) == f"{HOSTED_URL if hosted else ENGINE_URL}{CHAT_PATH}"
    assert sent_body(request)["model"] == "openrouter/a"
    assert request.headers.get(TOKEN_HEADER) == token


def test_endpoint_loads_the_catalogue_for_a_reducer_recipe() -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        e = InferenceClient(vote(), client=client).endpoint()

    assert e.model == compile_candidate(vote(), operators=CATALOG).url4
    assert [r.url.path for r in requests] == ["/v1/operators"]


def test_endpoint_of_a_recipe_without_a_reducer_loads_no_catalogue() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        e = InferenceClient(fusion(), client=client).endpoint()

    assert e.model == compile_candidate(fusion()).url4
    assert requests == []


def test_endpoint_failure_gives_no_partial_value(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = fake_access(monkeypatch, no_access)
    requests: list[httpx.Request] = []
    with hosted_client(catalogue_engine, requests) as client:
        llm = InferenceClient(vote(), client=client)
        with pytest.raises(AuthenticationError) as raised:
            llm.endpoint()

    assert raised.value.code == "access_not_advertised"
    # WHY: the sign-in comes before the catalogue load, so no request reaches the Engine.
    assert requests == []
    assert browser == []


def test_endpoint_raises_the_catalogue_error() -> None:
    def not_found(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    requests: list[httpx.Request] = []
    with recording_client(not_found, requests) as client:
        with pytest.raises(EngineCapabilityError):
            InferenceClient(vote(), client=client).endpoint()

    assert [r.url.path for r in requests] == ["/v1/operators"]


def test_endpoint_raises_the_compiler_error() -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        llm = InferenceClient(
            sf.Fanout(["prov/a", "prov/b"]) >> sf.Vote(over="benchmark"), client=client
        )
        with pytest.raises(ValueError, match="over='benchmark' needs a benchmark"):
            llm.endpoint()

    assert [r.url.path for r in requests] == ["/v1/operators"]


def test_endpoint_of_a_closed_client_sends_no_request() -> None:
    requests: list[httpx.Request] = []
    client = recording_client(catalogue_engine, requests)
    client.close()
    with pytest.raises(RuntimeError, match="Client is closed"):
        InferenceClient(vote(), client=client).endpoint()

    assert requests == []


def test_endpoint_takes_the_default_client_at_each_call(monkeypatch: pytest.MonkeyPatch) -> None:
    first_requests: list[httpx.Request] = []
    second_requests: list[httpx.Request] = []
    first = recording_client(ok, first_requests)
    # WHY a second Engine URL: the test fails when endpoint() keeps the first client.
    second = sf.Client(
        engine_url="http://engine2.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(lambda r: (second_requests.append(r), ok(r))[1]),
        save_results=False,
    )
    monkeypatch.setattr(_default_client, "_client", first)
    llm = InferenceClient("openrouter/a")
    try:
        first_endpoint = llm.endpoint()
        # WHY sf.close(): it closes the first client and forgets it, as the next call needs.
        sf.close()
        monkeypatch.setattr(_default_client, "_client", second)
        second_endpoint = llm.endpoint()
    finally:
        second.close()

    assert first_endpoint.base_url == f"{ENGINE_URL}/v1"
    assert second_endpoint.base_url == "http://engine2.test/v1"
    assert first_requests == []
    assert second_requests == []


def test_endpoint_is_hashable() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = InferenceClient("openrouter/a", client=client)
        first = llm.endpoint()
        second = llm.endpoint()

    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1
