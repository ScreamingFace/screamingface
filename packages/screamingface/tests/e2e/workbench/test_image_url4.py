"""The image input matrix's url4 path client (plan Task 3), against ``httpx.MockTransport``.

Review Focus 3 (a stale ``FIXTURE_REF`` or a 404 is a setup error naming the URL, before any
model call) and the Engine response mapping (200 / problem / 202) are pinned here without a
live target. The Engine shapes mirror ``screamingface_engine.rest.routes``: ``POST /token``
answers ``{"token": …}``; ``GET /?q=`` takes the token in ``URL4-Capability``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from url4 import Expression, RelExpr, Source, Text, Url, build

from workbench.image_url4 import (
    FixtureError,
    Url4Outcome,
    attachment_expression,
    fixture_url,
    run_attachment,
    verify_fixture,
)

ENGINE = "http://engine.test"
MODEL = "google/gemini-3-flash-preview"
PATH = "packages/screamingface/tests/e2e/workbench/fixtures/image_input/token.png"
REF = "0123456789abcdef0123456789abcdef01234567"
URL = fixture_url(REF, PATH)
PROMPT = "What 4-digit number is shown? Reply with the number only. Don't explain."
PNG = b"\x89PNG\r\n\x1a\n fixture bytes"
PROBLEM = "application/problem+json"

type Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _engine(run: Handler, sent: list[httpx.Request]) -> Handler:
    """A fake Engine: ``POST /token`` mints, ``GET /`` delegates to ``run``."""

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "POST" and request.url.path == "/token":
            return httpx.Response(200, json={"token": "cap.jwt.token"})
        assert request.method == "GET" and request.url.path == "/"
        return run(request)

    return handler


def _run(handler: Handler) -> tuple[Url4Outcome, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    with _client(_engine(handler, sent)) as client:
        outcome = run_attachment(client, ENGINE, MODEL, URL, "image/png", PROMPT)
    return outcome, sent


# --- fixture_url / verify_fixture ---------------------------------------------------------------


def test_fixture_url_is_commit_pinned_raw_github() -> None:
    assert URL == f"https://raw.githubusercontent.com/ScreamingFace/screamingface/{REF}/{PATH}"


@pytest.mark.parametrize(("ref", "path"), [("", PATH), (REF, ""), (REF, f"/{PATH}")])
def test_fixture_url_refuses_a_blank_ref_or_an_absolute_path(ref: str, path: str) -> None:
    with pytest.raises(ValueError):
        fixture_url(ref, path)


def test_verify_fixture_accepts_matching_bytes() -> None:
    with _client(lambda _: httpx.Response(200, content=PNG)) as client:
        verify_fixture(client, URL, hashlib.sha256(PNG).hexdigest())


def test_a_sha256_mismatch_is_a_fixture_error_naming_the_url() -> None:
    with _client(lambda _: httpx.Response(200, content=b"other bytes")) as client:
        with pytest.raises(FixtureError) as caught:
            verify_fixture(client, URL, hashlib.sha256(PNG).hexdigest())
    assert caught.value.url == URL
    assert URL in str(caught.value)
    assert "sha256" in caught.value.reason


def test_a_404_is_a_fixture_error_naming_the_url() -> None:
    with _client(lambda _: httpx.Response(404, text="404: Not Found")) as client:
        with pytest.raises(FixtureError) as caught:
            verify_fixture(client, URL, hashlib.sha256(PNG).hexdigest())
    assert caught.value.url == URL
    assert URL in str(caught.value)
    assert "404" in caught.value.reason


def test_an_unreachable_fixture_is_a_fixture_error_naming_the_url() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with _client(refuse) as client:
        with pytest.raises(FixtureError) as caught:
            verify_fixture(client, URL, hashlib.sha256(PNG).hexdigest())
    assert caught.value.url == URL


# --- attachment_expression ----------------------------------------------------------------------


def test_the_expression_round_trips_through_url4_build() -> None:
    expression = attachment_expression(MODEL, URL, "image/png", PROMPT)
    tree = build(expression)
    assert isinstance(tree, Expression)
    (call,) = tree.sources
    assert isinstance(call, RelExpr)
    assert call.path == f"/{MODEL}"
    assert call.intent == Text(PROMPT)
    assert call.context is not None
    # The context is the attachment: one source, the fixture URL, accepted as the media type.
    inner = build(f"({call.context})!'x'")
    assert isinstance(inner, Expression)
    assert inner.sources == (Source(value=Url(URL), annotations=(("accept", "image/png"),)),)


def test_the_expression_matches_the_engine_tested_shape() -> None:
    # `test_fair_share_fetch_bytes.py` runs `/{MODEL}(src=<url>;accept=image/png)!'…'`; the
    # prompt's apostrophe is escaped the way url4 Text requires.
    written = f"/{MODEL}(src={URL};accept=image/png)!'{PROMPT.replace("'", "\\'")}'"
    assert attachment_expression(MODEL, URL, "image/png", PROMPT) == written


def test_an_expression_that_does_not_round_trip_is_refused() -> None:
    # A comma in the URL would split the context into two sources.
    with pytest.raises(ValueError, match="round"):
        attachment_expression(MODEL, "https://raw.githubusercontent.com/a,b.png", "image/png", "p")


# --- run_attachment -----------------------------------------------------------------------------


def test_a_200_is_the_answer_and_the_run_carries_token_and_traceparent() -> None:
    outcome, sent = _run(lambda _: httpx.Response(200, text="The number is 7392."))
    mint, start = sent
    assert mint.method == "POST" and str(mint.url) == f"{ENGINE}/token"
    assert start.headers["URL4-Capability"] == "cap.jwt.token"
    (q,) = parse_qs(urlsplit(str(start.url)).query)["q"]
    assert q == attachment_expression(MODEL, URL, "image/png", PROMPT)
    assert outcome.answer == "The number is 7392."
    assert outcome.error_code is None
    assert outcome.spend_usd is None


def test_the_traceparent_sent_equals_the_returned_trace_id() -> None:
    outcome, sent = _run(lambda _: httpx.Response(200, text="7392"))
    version, trace_id, span_id, flags = sent[-1].headers["traceparent"].split("-")
    assert (version, flags) == ("00", "01")
    assert len(trace_id) == 32 and int(trace_id, 16) != 0
    assert len(span_id) == 16 and int(span_id, 16) != 0
    assert outcome.trace_id == trace_id


def test_each_call_mints_its_own_trace() -> None:
    first, _ = _run(lambda _: httpx.Response(200, text="7392"))
    second, _ = _run(lambda _: httpx.Response(200, text="7392"))
    assert first.trace_id != second.trace_id


def _problem(status: int, code: str | None) -> Handler:
    body = {"type": "about:blank", "title": "Bad", "status": status}
    if code is not None:
        body["code"] = code

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=json.dumps(body), headers={"content-type": PROBLEM})

    return handler


@pytest.mark.parametrize(
    ("status", "code"),
    [(422, "intent_error"), (502, "intent_error"), (502, "x.source_fetch_failed")],
)
def test_a_problem_is_its_code(status: int, code: str) -> None:
    outcome, _ = _run(_problem(status, code))
    assert outcome.answer is None
    assert outcome.error_code == code


def test_a_problem_without_a_code_is_named_by_its_status() -> None:
    outcome, _ = _run(_problem(502, None))
    assert outcome.answer is None
    assert outcome.error_code == "http_502"


def test_a_202_is_a_sync_timeout_never_a_pass() -> None:
    outcome, _ = _run(lambda _: httpx.Response(202, headers={"Location": "/?topic=t"}))
    assert outcome.answer is None
    assert outcome.error_code == "sync_timeout"


def test_an_empty_200_is_an_error_not_an_answer() -> None:
    outcome, _ = _run(lambda _: httpx.Response(200))
    assert outcome.answer is None
    assert outcome.error_code == "empty_result"


def test_a_failed_token_mint_is_an_error_and_starts_no_run() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503, content=b"down")

    with _client(handler) as client:
        outcome = run_attachment(client, ENGINE, MODEL, URL, "image/png", PROMPT)
    assert [r.url.path for r in sent] == ["/token"]
    assert outcome.answer is None
    assert outcome.error_code == "token_mint_failed"


def test_an_unreachable_engine_is_a_transport_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _client(refuse) as client:
        outcome = run_attachment(client, ENGINE, MODEL, URL, "image/png", PROMPT)
    assert outcome.answer is None
    assert outcome.error_code == "transport_error"
    assert len(outcome.trace_id) == 32
