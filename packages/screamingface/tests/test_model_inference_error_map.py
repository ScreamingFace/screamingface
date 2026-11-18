"""MI-11, MI-12 and MI-31 (sync part) at the level of the error map (contracts C2.4).

No transport: refusal_error gets an httpx.Response that holds its body; the other functions get
their values as they are.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from screamingface._inference.error_map import (
    client_timeout,
    engine_unavailable,
    invalid_response,
    outcome_unknown,
    refusal_error,
    stream_error,
)
from screamingface._inference.frames import StreamError
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    PlanningError,
    ScreamingFaceError,
)

TRACE = "0af7651916cd43dd8448eb211c80319c"
ROUTE = "POST /v1/chat/completions"
RETRY = {"x-should-retry": "true"}


def env(code: str, *, param: str | None = None, message: str = "refused") -> bytes:
    return json.dumps(
        {
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "code": code,
                "param": param,
            }
        }
    ).encode()


@pytest.mark.parametrize(
    ("status", "headers", "body", "cls", "code", "permanent", "details"),
    [
        pytest.param(
            404,
            {},
            b"Not Found",
            EngineCapabilityError,
            "engine_capability_missing",
            True,
            {"route": ROUTE},
            id="404-no-envelope",
        ),
        pytest.param(
            405,
            {},
            b"",
            EngineCapabilityError,
            "engine_capability_missing",
            True,
            {"route": ROUTE},
            id="405-no-envelope",
        ),
        pytest.param(
            401,
            {},
            env("invalid_api_key"),
            AuthenticationError,
            "invalid_api_key",
            True,
            None,
            id="401",
        ),
        pytest.param(
            403, {}, env("forbidden"), AuthenticationError, "forbidden", True, None, id="403"
        ),
        pytest.param(
            401,
            {},
            b"",
            AuthenticationError,
            "authentication_failed",
            True,
            None,
            id="401-no-envelope",
        ),
        pytest.param(
            400,
            {},
            env("recipe_invalid", param="model"),
            PlanningError,
            "recipe_invalid",
            True,
            {"param": "model"},
            id="400",
        ),
        pytest.param(
            404,
            {},
            env("model_not_found", param="model"),
            PlanningError,
            "model_not_found",
            True,
            {"param": "model"},
            id="404-envelope",
        ),
        pytest.param(
            413,
            {},
            env("request_too_large"),
            PlanningError,
            "request_too_large",
            True,
            None,
            id="413",
        ),
        pytest.param(
            415,
            {},
            env("unsupported_media_type"),
            PlanningError,
            "unsupported_media_type",
            True,
            None,
            id="415",
        ),
        pytest.param(
            408,
            {"x-should-retry": "false"},
            env("timeout"),
            ExecutionError,
            "timeout",
            True,
            None,
            id="408",
        ),
        pytest.param(
            422, {}, env("recipe_failed"), ExecutionError, "recipe_failed", True, None, id="422"
        ),
        pytest.param(
            429,
            {**RETRY, "Retry-After": "7"},
            env("overloaded"),
            ExecutionError,
            "overloaded",
            False,
            {"retry_after": 7},
            id="429-retry",
        ),
        pytest.param(
            500,
            {"x-should-retry": "false"},
            env("server_error"),
            ExecutionError,
            "server_error",
            True,
            None,
            id="500",
        ),
        pytest.param(
            503,
            {"x-should-retry": " TRUE "},
            env("server_restarting"),
            ExecutionError,
            "server_restarting",
            False,
            None,
            id="503-retry",
        ),
        pytest.param(
            502,
            {},
            env("upstream_error"),
            ExecutionError,
            "upstream_error",
            True,
            None,
            id="502-no-header",
        ),
        pytest.param(
            409, {}, env("conflict"), ExecutionError, "conflict", True, None, id="409-other"
        ),
        pytest.param(
            302, {}, b"", ExecutionError, "engine_contract_error", True, None, id="302-other"
        ),
        pytest.param(
            429,
            {**RETRY, "Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
            env("overloaded"),
            ExecutionError,
            "overloaded",
            False,
            {"retry_after": 0.0},
            id="retry-after-date",
        ),
        pytest.param(
            429,
            {**RETRY, "Retry-After": "soon"},
            env("overloaded"),
            ExecutionError,
            "overloaded",
            False,
            None,
            id="retry-after-text",
        ),
    ],
)
def test_error_map_before_the_stream(
    status: int,
    headers: dict[str, str],
    body: bytes,
    cls: type[ScreamingFaceError],
    code: str,
    permanent: bool,
    details: dict[str, object] | None,
) -> None:
    err = refusal_error(httpx.Response(status, headers=headers, content=body), TRACE)

    assert type(err) is cls
    assert err.code == code
    assert err.status == status
    assert err.permanent is permanent
    assert err.details == details
    assert err.trace_id == TRACE


def test_error_message_names_the_status_and_the_engine_message() -> None:
    err = refusal_error(httpx.Response(429, content=env("overloaded", message="busy")), TRACE)

    assert "429" in err.message
    assert "busy" in err.message


def test_a_future_http_date_retry_after_is_in_details() -> None:
    when = datetime.now(UTC) + timedelta(seconds=120)
    headers = {**RETRY, "Retry-After": format_datetime(when, usegmt=True)}
    err = refusal_error(httpx.Response(429, headers=headers, content=env("overloaded")), TRACE)

    assert isinstance(err.details, dict)
    assert 100.0 <= err.details["retry_after"] <= 120.0


def test_error_event_maps_should_retry_and_retry_after() -> None:
    retry = StreamError(
        message="restart",
        type="server_error",
        code="server_restarting",
        should_retry=True,
        retry_after=5,
    )
    err = stream_error(retry, TRACE)

    assert isinstance(err, ExecutionError)
    assert err.code == "server_restarting"
    assert err.permanent is False
    assert err.details == {"retry_after": 5}
    assert err.trace_id == TRACE

    final = StreamError(
        message="stopped",
        type="server_error",
        code="timeout",
        should_retry=False,
        retry_after=None,
    )
    err = stream_error(final, TRACE)

    assert err.code == "timeout"
    assert err.permanent is True
    assert err.details is None


def test_error_event_with_no_flag_is_permanent() -> None:
    event = StreamError(
        message="stopped",
        type="server_error",
        code="timeout",
        should_retry=None,
        retry_after=None,
    )
    err = stream_error(event, TRACE)

    assert err.permanent is True


def test_transport_failures() -> None:
    outcome = outcome_unknown(TRACE)
    assert outcome.code == "inference_outcome_unknown"
    assert outcome.permanent is True

    timeout = client_timeout(TRACE)
    assert timeout.code == "client_timeout"
    assert timeout.permanent is True

    wrong = invalid_response("not_json", TRACE)
    assert wrong.code == "invalid_response"
    assert wrong.details == {"reason": "not_json"}
    assert wrong.permanent is True

    for err in (outcome, timeout, wrong):
        assert err.trace_id == TRACE
        assert err.hint is not None

    unavailable = engine_unavailable("http://engine.test", TRACE)
    assert isinstance(unavailable, EngineUnavailableError)
    assert unavailable.permanent is False
    assert unavailable.engine_url == "http://engine.test"
    assert unavailable.code == "engine_unreachable"
    assert unavailable.trace_id == TRACE
