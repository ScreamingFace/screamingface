"""MI-40 and MI-41: the one-line change from the OpenAI SDK (overview §5.6, D18 to D22; C1.7).

FEATURE: SDK model inference, unit U10. Team feedback of 2026-11-24: openai.OpenAI(...) becomes
screamingface.Client(...), and the code below that line keeps working as it is.
STORY: as a user of the OpenAI SDK, I change the line that makes my client, and my tool loop, my
sampling parameters and my stream loop run with no other change.
AIDEV-NOTE: program() and aprogram() are the code of that user. Do not change them for one of
the two clients: the test is the comparison.
"""

from __future__ import annotations

import inspect
import json
import sys
import warnings
from typing import Any

import httpx
import openai
import pytest
from _chat_engine import ENGINE_URL, ok, sent_body, sse
from _chat_frames import META, USAGE, engine_stream, info, wire

import screamingface as sf
from screamingface._inference.client_options import IGNORED_CLIENT_OPTIONS
from screamingface.warnings import IgnoredParameterWarning

KEY = "sk-test-do-not-send-1234567890"
MODEL = "openrouter/a"
BASE_URL = f"{ENGINE_URL}/v1"
FIRST, SECOND = "Paris", "Rome"


def _engine(requests: list[httpx.Request]) -> Any:
    """An Engine that answers the plain form (the OpenAI client) and the stream (each SF call)."""

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        text = FIRST if len(body["messages"]) == 1 else SECOND
        message: dict[str, Any] = {"role": "assistant", "content": text}
        if body.get("stream"):
            return sse(wire(engine_stream(message, "stop")))
        plain = {
            **META,
            "object": "chat.completion",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": dict(USAGE),
            "screamingface": info(),
        }
        return httpx.Response(200, json=plain)

    return respond


def _options(handler: Any = ok) -> dict[str, Any]:
    """The test wiring of a SF client: the mock Engine and no results on disk."""

    return {
        "scoreboard_url": "http://scoreboard.test",
        "http_transport": httpx.MockTransport(handler),
        "save_results": False,
    }


def program(client: Any) -> dict[str, Any]:
    """Two turns that keep the reply message in the conversation, and a stream loop.

    AIDEV-NOTE: the program has no tools. Tool calls are turned off for now (C1.8, D26); the
    test of that error is tests/test_model_inference_tools_off.py.
    """

    messages: list[Any] = [{"role": "user", "content": "What is the capital of France?"}]
    first = client.chat.completions.create(
        model=MODEL, messages=messages, temperature=0.2, max_tokens=64
    )
    messages.append(first.choices[0].message)
    messages.append({"role": "user", "content": "And of Italy?"})
    second = client.chat.completions.create(model=MODEL, messages=messages)
    stream = client.chat.completions.create(model=MODEL, messages=messages, stream=True)
    pieces = [chunk.choices[0].delta.content or "" for chunk in stream if chunk.choices]
    return _summary(first, second, pieces)


async def aprogram(client: Any) -> dict[str, Any]:
    """program() with the async client."""

    messages: list[Any] = [{"role": "user", "content": "What is the capital of France?"}]
    first = await client.chat.completions.create(
        model=MODEL, messages=messages, temperature=0.2, max_tokens=64
    )
    messages.append(first.choices[0].message)
    messages.append({"role": "user", "content": "And of Italy?"})
    second = await client.chat.completions.create(model=MODEL, messages=messages)
    stream = await client.chat.completions.create(model=MODEL, messages=messages, stream=True)
    pieces = [chunk.choices[0].delta.content or "" async for chunk in stream if chunk.choices]
    return _summary(first, second, pieces)


def _summary(first: Any, second: Any, pieces: list[str]) -> dict[str, Any]:
    message = first.choices[0].message
    usage = second.usage
    return {
        "finish": first.choices[0].finish_reason,
        "first": message.content,
        "tool_calls": message.tool_calls,
        "function_call": message.function_call,
        "answer": second.choices[0].message.content,
        "tokens": (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens),
        "token_details": usage.prompt_tokens_details,
        "logprobs": second.choices[0].logprobs,
        "fingerprint": second.system_fingerprint,
        "dumped": second.model_dump()["choices"][0]["message"]["content"],
        "json": json.loads(second.model_dump_json())["choices"][0]["finish_reason"],
        "stream": "".join(pieces),
    }


EXPECTED = {
    "finish": "stop",
    "first": FIRST,
    "tool_calls": None,
    "function_call": None,
    "answer": SECOND,
    "tokens": (3, 2, 5),
    "token_details": None,
    "logprobs": None,
    "fingerprint": None,
    "dumped": SECOND,
    "json": "stop",
    "stream": SECOND,
}


def _same_wire(theirs: list[httpx.Request], ours: list[httpx.Request]) -> None:
    assert len(theirs) == len(ours) == 3
    for their, our in zip(theirs, ours, strict=True):
        assert our.url == their.url == f"{BASE_URL}/chat/completions"
        assert sent_body(our)["model"] == sent_body(their)["model"] == MODEL
        # INVARIANT (D23): the reply message that the program appended has the same wire form.
        assert sent_body(our)["messages"] == sent_body(their)["messages"]
        assert "tools" not in sent_body(our)
        assert KEY not in our.content.decode()
        assert all(KEY not in value for value in our.headers.values())


def test_one_program_runs_with_the_openai_client_and_with_sf_client() -> None:
    theirs: list[httpx.Request] = []
    ours: list[httpx.Request] = []
    plain = httpx.Client(transport=httpx.MockTransport(_engine(theirs)))
    with openai.OpenAI(api_key=KEY, base_url=BASE_URL, max_retries=0, http_client=plain) as client:
        expected = program(client)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", IgnoredParameterWarning)
        with sf.Client(
            api_key=KEY, base_url=BASE_URL, max_retries=0, **_options(_engine(ours))
        ) as client:
            result = program(client)

    assert expected == EXPECTED
    assert result == expected
    _same_wire(theirs, ours)


@pytest.mark.asyncio
async def test_one_program_runs_with_the_two_async_clients() -> None:
    theirs: list[httpx.Request] = []
    ours: list[httpx.Request] = []
    plain = httpx.AsyncClient(transport=httpx.MockTransport(_engine(theirs)))
    async with openai.AsyncOpenAI(
        api_key=KEY, base_url=BASE_URL, max_retries=0, http_client=plain
    ) as client:
        expected = await aprogram(client)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", IgnoredParameterWarning)
        async with sf.AsyncClient(
            api_key=KEY, base_url=BASE_URL, max_retries=0, **_options(_engine(ours))
        ) as client:
            result = await aprogram(client)

    assert expected == EXPECTED
    assert result == expected
    _same_wire(theirs, ours)


@pytest.mark.parametrize(
    "base_url",
    [
        ENGINE_URL,
        f"{ENGINE_URL}/",
        f"{ENGINE_URL}/v1",
        f"{ENGINE_URL}/v1/",
        f"  {ENGINE_URL}/v1  ",
        httpx.URL(f"{ENGINE_URL}/v1"),
        f"{ENGINE_URL}/v1//",
    ],
    ids=["origin", "origin-slash", "v1", "v1-slash", "white-space", "httpx-url", "v1-slashes"],
)
def test_base_url_is_the_engine_url_in_the_openai_form(base_url: Any) -> None:
    requests: list[httpx.Request] = []
    with sf.Client(base_url=base_url, **_options(_engine(requests))) as client:
        assert client.engine_url == ENGINE_URL
        # INVARIANT (D20): base_url is the value that endpoint() gives for another client.
        assert client.chat.endpoint(MODEL).base_url == BASE_URL
        client.chat.completions.create("Hello", model=MODEL)

    assert requests[0].url == f"{ENGINE_URL}/v1/chat/completions"


@pytest.mark.parametrize(
    ("base_url", "error"),
    [
        ("https://openrouter.ai/api/v1", ValueError),
        ("http://engine.test//v1", ValueError),
        ("http://engine.test/V1", ValueError),
        ("http://engine.test/v1/v1", ValueError),
        ("http://engine.test/v1/chat/completions", ValueError),
        ("ftp://engine.test/v1", ValueError),
        ("http://user:pass@engine.test/v1", ValueError),
        ("http://engine.test/v1?key=1", ValueError),
        ("", ValueError),
        (5, TypeError),
        (b"http://engine.test/v1", TypeError),
    ],
)
@pytest.mark.parametrize("make", [sf.Client, sf.AsyncClient])
def test_a_base_url_that_is_not_an_engine_url_is_refused(
    make: Any, base_url: Any, error: type[Exception]
) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(error, match="base_url"):
            make(base_url=base_url, api_key=KEY, **_options())
    # C1.7: an error comes before each warning.
    assert caught == []


def test_a_host_with_the_name_v1_is_a_valid_engine_host() -> None:
    with sf.Client(base_url="http://v1", **_options()) as client:
        assert client.engine_url == "http://v1"
    with sf.Client(base_url="http://v1:9108/v1", **_options()) as client:
        assert client.engine_url == "http://v1:9108"


@pytest.mark.parametrize(
    "bad", [{"engine_url": "ftp://engine.test"}, {"scoreboard_url": "ftp://scoreboard.test"}]
)
@pytest.mark.parametrize("make", [sf.Client, sf.AsyncClient])
def test_each_url_error_comes_before_each_warning(make: Any, bad: dict[str, str]) -> None:
    options = {**_options(), **bad}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match=next(iter(bad))):
            make(api_key=KEY, organization="o", **options)
    assert caught == []


@pytest.mark.parametrize("make", [sf.Client, sf.AsyncClient])
def test_base_url_with_engine_url_is_a_type_error(make: Any) -> None:
    with pytest.raises(TypeError, match="engine_url"):
        make(base_url=BASE_URL, engine_url="http://other.test", **_options())


def test_api_key_gives_one_warning_that_does_not_show_it() -> None:
    options = _options()
    with pytest.warns(IgnoredParameterWarning) as record:
        expected_line = sys._getframe().f_lineno + 1
        client = sf.Client(api_key=KEY, base_url=BASE_URL, **options)
    client.close()

    assert len(record) == 1
    text = str(record[0].message)
    assert "'api_key'" in text
    assert "sf.connect(" in text
    assert KEY not in text
    assert record[0].filename == __file__
    assert record[0].lineno == expected_line


def test_api_key_is_in_no_request_no_attribute_and_no_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT (D19): the SDK does not read the OpenAI environment either.
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://other.test/v1")
    requests: list[httpx.Request] = []
    called: list[int] = []

    def provider() -> str:
        called.append(1)
        return KEY

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", IgnoredParameterWarning)
        with (
            sf.Client(api_key=KEY, engine_url=ENGINE_URL, **_options(_engine(requests))) as client,
            sf.Client(api_key=provider, base_url=BASE_URL, **_options(_engine(requests))) as other,
        ):
            client.chat.completions.create("Hello", model=MODEL)
            other.chat.completions.create("Hello", model=MODEL)
            endpoint = client.chat.endpoint(MODEL)
            shown = repr(client) + repr(vars(client)) + repr(endpoint) + repr(client.chat)

    assert len(requests) == 2
    for request in requests:
        assert request.url.host == "engine.test"
        assert KEY not in str(request.url)
        assert KEY not in request.content.decode()
        assert all(KEY not in value for value in request.headers.values())
    assert KEY not in shown
    assert not hasattr(client, "api_key")
    assert all(KEY not in value for value in endpoint.headers.values())
    assert called == []


@pytest.mark.parametrize("name", sorted(IGNORED_CLIENT_OPTIONS))
def test_each_other_openai_option_is_accepted_and_not_used(name: str) -> None:
    requests: list[httpx.Request] = []
    value: Any = {"X-Secret-Option": "s3cret-option"} if "default" in name else "s3cret-option"
    with pytest.warns(IgnoredParameterWarning) as record:
        client = sf.Client(engine_url=ENGINE_URL, **{name: value}, **_options(_engine(requests)))
    with client:
        client.chat.completions.create("Hello", model=MODEL)

    assert len(record) == 1
    assert repr(name) in str(record[0].message)
    assert "s3cret-option" not in str(record[0].message)
    assert record[0].filename == __file__
    assert requests[0].url == f"{ENGINE_URL}/v1/chat/completions"
    assert "x-secret-option" not in requests[0].headers
    assert all("s3cret-option" not in value for value in requests[0].headers.values())


def test_an_option_with_the_value_none_gives_no_warning() -> None:
    none = dict.fromkeys(IGNORED_CLIENT_OPTIONS)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sf.Client(api_key=None, base_url=None, timeout=None, **none, **_options()).close()
    assert [item for item in caught if item.category is IgnoredParameterWarning] == []


@pytest.mark.parametrize(("make", "name"), [(sf.Client, "Client"), (sf.AsyncClient, "AsyncClient")])
def test_an_unknown_client_option_is_a_type_error(make: Any, name: str) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(TypeError) as error:
            make(api_kee=KEY, organization="o", **_options())
    assert str(error.value) == f"{name}.__init__() got an unexpected keyword argument 'api_kee'"
    assert caught == []


@pytest.mark.parametrize(
    ("ours", "theirs"), [(sf.Client, openai.OpenAI), (sf.AsyncClient, openai.AsyncOpenAI)]
)
def test_each_public_option_of_the_openai_client_is_accepted(ours: Any, theirs: Any) -> None:
    """A tripwire: a later openai version that adds an option makes this test fail."""

    named = set(inspect.signature(ours.__init__).parameters)
    public = [
        name
        for name in inspect.signature(theirs.__init__).parameters
        if name != "self" and not name.startswith("_")
    ]
    assert {"api_key", "base_url", "timeout", "max_retries"} <= named
    # D22: the list of the spec, written out, so a name that leaves the code is seen.
    assert IGNORED_CLIENT_OPTIONS == {
        "organization",
        "project",
        "webhook_secret",
        "websocket_base_url",
        "default_headers",
        "default_query",
        "http_client",
        "admin_api_key",
        "workload_identity",
        "provider",
    }
    assert [name for name in public if name not in named | IGNORED_CLIENT_OPTIONS] == []
    assert named.isdisjoint(IGNORED_CLIENT_OPTIONS)
