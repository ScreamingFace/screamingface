"""RFC 9457 is this service's only error shape.

Every status a client can receive comes back as `application/problem+json`, so an SDK writes one
parser. The catalogue of constructors that produce them lands with the report route; this file
covers the plumbing underneath, which nothing later re-creates.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from report_intake.core.problem import (
    PROBLEM_MEDIA_TYPE,
    Problem,
    ProblemException,
    install_problem_handlers,
    problem_exception_handler,
)


def _app_that_raises(exc: Exception) -> TestClient:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app)


def test_a_problem_is_rendered_as_problem_json() -> None:
    client = _app_that_raises(
        ProblemException(413, "Payload Too Large", "report body is 91 kB; the limit is 64 kB")
    )

    response = client.get("/boom")

    assert response.status_code == 413
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "about:blank",
        "title": "Payload Too Large",
        "status": 413,
        "detail": "report body is 91 kB; the limit is 64 kB",
    }


def test_members_that_were_never_set_are_dropped_rather_than_sent_as_null() -> None:
    """RFC 9457 members are optional, and a client checking `"detail" in body` must not have to
    also check for null."""
    client = _app_that_raises(ProblemException(429, "Too Many Requests"))

    body = client.get("/boom").json()

    assert body == {"type": "about:blank", "title": "Too Many Requests", "status": 429}


def test_headers_travel_with_the_problem() -> None:
    """`429` is unusable without `Retry-After`; the carrier has to exist before the catalogue
    needs it."""
    client = _app_that_raises(
        ProblemException(429, "Too Many Requests", headers={"Retry-After": "30"})
    )

    assert client.get("/boom").headers["Retry-After"] == "30"


@pytest.mark.asyncio
async def test_an_exception_that_is_not_a_problem_is_re_raised_untouched() -> None:
    """The handler is registered for one exception type, but FastAPI hands it an `Exception`.
    Swallowing anything else would turn a genuine bug into a plausible-looking error body.
    """
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    other = RuntimeError("not a problem")

    with pytest.raises(RuntimeError, match="not a problem"):
        await problem_exception_handler(request, other)


def test_a_problem_defaults_to_the_blank_type() -> None:
    """`about:blank` says "the status code is the whole story" — the right default until this
    service publishes problem-type URIs of its own."""
    assert Problem(title="Service Unavailable", status=503).type == "about:blank"
