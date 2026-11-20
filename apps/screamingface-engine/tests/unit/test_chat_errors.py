"""Tests for the OpenAI error envelope of POST /v1/chat/completions (prd/chat-completion.md §3.4).

Q2: the error type follows the status (429 rate_limit_error, other 4xx invalid_request_error,
5xx server_error). Q3: a capacity or queue problem from the scheduler is re-enveloped with its
retry rule, and any other problem keeps its status with the fixed internal_error message.
"""

import json

import pytest

from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.chat_errors import ChatError, error_type, from_problem
from screamingface_engine.rest.stopping import QUEUE_UNAVAILABLE_RETRY_AFTER_S
from screamingface_engine.runner_queue import RunQueueUnavailable
from url4.streaming.interfaces import JobRunnerAtCapacity


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, "rate_limit_error"),
        (400, "invalid_request_error"),
        (401, "invalid_request_error"),
        (404, "invalid_request_error"),
        (413, "invalid_request_error"),
        (415, "invalid_request_error"),
        (422, "invalid_request_error"),
        (500, "server_error"),
        (502, "server_error"),
        (503, "server_error"),
        (504, "server_error"),
    ],
)
def test_error_type_follows_the_openai_names(status: int, expected: str) -> None:
    assert error_type(status) == expected


def test_the_envelope_has_the_four_openai_keys_and_the_retry_header() -> None:
    response = ChatError(400, "invalid_request", param="messages").response()

    assert json.loads(bytes(response.body)) == {
        "error": {
            "message": "the request body is not valid",
            "type": "invalid_request_error",
            "param": "messages",
            "code": "invalid_request",
        }
    }
    assert response.headers["x-should-retry"] == "false"
    assert "retry-after" not in response.headers
    assert response.media_type == "application/json"


def test_retry_after_is_sent_only_when_given() -> None:
    response = ChatError(503, "queue_unavailable", retry_after=5, should_retry=True).response()

    assert response.headers["retry-after"] == "5"
    assert response.headers["x-should-retry"] == "true"


def test_capacity_problem_becomes_429_overloaded_with_the_runner_estimate() -> None:
    try:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="x",
            headers={"Retry-After": "42"},
        ) from JobRunnerAtCapacity(4, 4, retry_after_s=42)
    except ProblemException as exc:
        err = from_problem(exc)

    assert err.status == 429
    assert err.code == "overloaded"
    assert err.retry_after == 42
    assert err.should_retry is True


def test_capacity_problem_without_a_retry_after_header_waits_one_second() -> None:
    try:
        raise ProblemException(
            status=503, title="Service Unavailable", detail="x"
        ) from JobRunnerAtCapacity(4, 4)
    except ProblemException as exc:
        err = from_problem(exc)

    assert err.status == 429
    assert err.code == "overloaded"
    assert err.retry_after == 1


def test_queue_problem_becomes_503_queue_unavailable_with_its_retry_after() -> None:
    try:
        raise ProblemException(
            status=503, title="Service Unavailable", detail="x", headers={"Retry-After": "7"}
        ) from RunQueueUnavailable("down")
    except ProblemException as exc:
        err = from_problem(exc)

    assert err.status == 503
    assert err.code == "queue_unavailable"
    assert err.retry_after == 7
    assert err.should_retry is True


def test_queue_problem_without_a_retry_after_header_waits_the_queue_default() -> None:
    try:
        raise ProblemException(
            status=503, title="Service Unavailable", detail="x"
        ) from RunQueueUnavailable("down")
    except ProblemException as exc:
        err = from_problem(exc)

    assert err.code == "queue_unavailable"
    assert err.retry_after == QUEUE_UNAVAILABLE_RETRY_AFTER_S == 5


def test_other_problem_keeps_its_status_with_internal_error() -> None:
    exc = ProblemException(status=409, title="Conflict", detail="a run already exists")

    err = from_problem(exc)
    body = bytes(err.response().body).decode()

    assert err.status == 409
    assert err.code == "internal_error"
    assert err.message == "the request failed"
    assert err.should_retry is False
    assert err.retry_after is None
    assert "already exists" not in body
