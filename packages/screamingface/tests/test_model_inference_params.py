"""MI-16, MI-17, MI-19 at the level of the request helpers (contracts C1.2, C2.1, P4)."""

from __future__ import annotations

import re
import warnings

import httpx
import pytest

from screamingface._inference.parameters import OPENAI_ONLY_PARAMETERS
from screamingface._inference.request import (
    INCLUDE_USAGE,
    KNOWN_PARAMETERS,
    chat_body,
    chat_headers,
    chat_messages,
    chat_tools,
    check_options,
    check_other,
)
from screamingface.errors import PlanningError
from screamingface.warnings import IgnoredParameterWarning

SAMPLE: dict[str, object] = {
    "temperature": 0.2,
    "max_tokens": 50,
    "max_completion_tokens": 50,
    "top_p": 0.9,
    "stop": ["x"],
    "seed": 1,
    "response_format": {"type": "json_object"},
    "tool_choice": "auto",
    "parallel_tool_calls": False,
    "presence_penalty": 0.1,
    "frequency_penalty": 0.1,
    "logit_bias": {"1": 1},
    "top_logprobs": 2,
    "reasoning_effort": "low",
    "user": "u",
    "metadata": {"k": "v"},
    "store": False,
    "service_tier": "auto",
    "n": 1,
    "logprobs": False,
    "audio": None,
    "modalities": ["text"],
    # U10 (D25): the other keywords of the OpenAI create.
    "extra_headers": {"x": "y"},
    "extra_query": {"a": "b"},
    "extra_body": {"k": 1},
    "prediction": {"type": "content", "content": "x"},
    "web_search_options": {},
    "prompt_cache_key": "k",
    "prompt_cache_options": {},
    "prompt_cache_retention": "24h",
    "safety_identifier": "u",
    "verbosity": "low",
    "moderation": {},
    "functions": None,
    "function_call": None,
}
TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}
M1 = {"role": "system", "content": "Be short."}
M2 = {"role": "user", "content": [{"type": "text", "text": "Hi"}]}
BASE_OPTIONS: dict[str, object] = {
    "stream": False,
    "stream_options": None,
    "use_cache": True,
    "max_retries": 0,
    "timeout": None,
}


def test_sample_covers_each_known_parameter() -> None:
    assert set(SAMPLE) == KNOWN_PARAMETERS


@pytest.mark.parametrize("name", list(SAMPLE))
def test_known_parameter_warns_and_is_not_sent(name: str) -> None:
    with pytest.warns(IgnoredParameterWarning) as record:
        check_other({name: SAMPLE[name]})
    assert len(record) == 1
    message = str(record[0].message)
    assert name in message
    # D25: the advice applies to a model parameter, not to a keyword that only OpenAI has.
    assert ("sf.Model(" in message) == (name not in OPENAI_ONLY_PARAMETERS)


def test_each_parameter_gives_one_warning() -> None:
    with pytest.warns(IgnoredParameterWarning) as record:
        check_other({"temperature": 0.2, "max_tokens": 50})
    messages = [str(item.message) for item in record]
    assert len(messages) == 2
    assert "'temperature'" in messages[0]
    assert "'max_tokens'" in messages[1]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("n", 2),
        ("logprobs", True),
        ("audio", {"voice": "alloy", "format": "wav"}),
        ("modalities", ["text", "audio"]),
    ],
)
def test_refused_parameters_raise(name: str, value: object) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(PlanningError) as error:
            check_other({name: value})
    assert error.value.code == "unsupported_parameter"
    assert error.value.details == {"param": name}
    assert caught == []


@pytest.mark.parametrize("name", ["tool", "message", "temprature", "stream_option"])
def test_unknown_keyword_is_a_type_error(name: str) -> None:
    with pytest.raises(TypeError, match=name):
        check_other({name: []})


def test_unknown_keyword_comes_before_a_refused_one() -> None:
    with pytest.raises(TypeError):
        check_other({"n": 2, "tool": []})


def test_prompt_is_one_user_message() -> None:
    assert chat_messages("Hello", None) == [{"role": "user", "content": "Hello"}]
    assert chat_messages(None, (M1, M2)) == [M1, M2]


def test_empty_tools_are_not_sent() -> None:
    assert chat_tools(None) is None
    assert chat_tools([]) is None
    assert chat_tools([TOOL]) == [TOOL]


ARGUMENT_ERRORS: list[tuple[str, object, type[Exception]]] = [
    ("messages-both-none", lambda: chat_messages(None, None), TypeError),
    ("messages-both-given", lambda: chat_messages("hi", [M1]), TypeError),
    ("prompt-not-str", lambda: chat_messages(5, None), TypeError),
    ("messages-empty", lambda: chat_messages(None, []), ValueError),
    ("messages-str", lambda: chat_messages(None, "hi"), TypeError),
    ("messages-str-item", lambda: chat_messages(None, ["hi"]), TypeError),
    ("tools-str", lambda: chat_tools("x"), TypeError),
    ("tools-int-item", lambda: chat_tools([1]), TypeError),
    ("stream-not-bool", lambda: check_options(**{**BASE_OPTIONS, "stream": "yes"}), TypeError),
    ("use-cache-not-bool", lambda: check_options(**{**BASE_OPTIONS, "use_cache": 1}), TypeError),
    (
        "stream-options-list",
        lambda: check_options(**{**BASE_OPTIONS, "stream_options": ["x"]}),
        TypeError,
    ),
    ("retries-negative", lambda: check_options(**{**BASE_OPTIONS, "max_retries": -1}), ValueError),
    ("retries-bool", lambda: check_options(**{**BASE_OPTIONS, "max_retries": True}), TypeError),
    ("retries-float", lambda: check_options(**{**BASE_OPTIONS, "max_retries": 1.5}), TypeError),
    ("timeout-zero", lambda: check_options(**{**BASE_OPTIONS, "timeout": 0}), ValueError),
    ("timeout-negative", lambda: check_options(**{**BASE_OPTIONS, "timeout": -1}), ValueError),
    (
        "timeout-inf",
        lambda: check_options(**{**BASE_OPTIONS, "timeout": float("inf")}),
        ValueError,
    ),
    (
        "timeout-nan",
        lambda: check_options(**{**BASE_OPTIONS, "timeout": float("nan")}),
        ValueError,
    ),
    ("timeout-str", lambda: check_options(**{**BASE_OPTIONS, "timeout": "5"}), TypeError),
    ("timeout-bool", lambda: check_options(**{**BASE_OPTIONS, "timeout": True}), TypeError),
]


@pytest.mark.parametrize(
    ("build", "error"),
    [(item[1], item[2]) for item in ARGUMENT_ERRORS],
    ids=[item[0] for item in ARGUMENT_ERRORS],
)
def test_argument_errors(build: object, error: type[Exception]) -> None:
    assert callable(build)
    with pytest.raises(error):
        build()


def test_valid_options_give_no_error() -> None:
    check_options(**BASE_OPTIONS)
    check_options(**{**BASE_OPTIONS, "timeout": 5, "max_retries": 2})
    # U10 (D21): None means the default of the client; an httpx.Timeout is a valid timeout.
    check_options(**{**BASE_OPTIONS, "max_retries": None})
    check_options(**{**BASE_OPTIONS, "timeout": httpx.Timeout(30.0)})


def test_body_has_the_c2_1_shape() -> None:
    m = {"role": "user", "content": "Hello"}
    assert chat_body("openrouter/a", [m], None, stream_options=INCLUDE_USAGE) == {
        "model": "openrouter/a",
        "messages": [m],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    with_tools = chat_body("openrouter/a", [m], [TOOL], stream_options=INCLUDE_USAGE)
    assert list(with_tools) == ["model", "messages", "tools", "stream", "stream_options"]
    without_options = chat_body("openrouter/a", [m], None, stream_options=None)
    assert "stream_options" not in without_options


def test_headers_have_accept_trace_and_cache_rule() -> None:
    headers, trace_id = chat_headers(use_cache=True)
    assert headers["Accept"] == "text/event-stream"
    match = re.fullmatch(r"00-([0-9a-f]{32})-[0-9a-f]{16}-01", headers["traceparent"])
    assert match is not None
    assert match.group(1) == trace_id
    assert "Cache-Control" not in headers
    assert chat_headers(use_cache=False)[0]["Cache-Control"] == "no-store"
    assert chat_headers(use_cache=True)[0]["traceparent"] != headers["traceparent"]


def test_use_cache_has_the_message_of_sf_evaluate() -> None:
    with pytest.raises(TypeError, match=r"^use_cache must be True or False$"):
        check_options(**{**BASE_OPTIONS, "use_cache": "yes"})
