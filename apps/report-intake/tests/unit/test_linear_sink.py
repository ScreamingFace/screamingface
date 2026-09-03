"""`LinearSink` — the adapter that files a ticket into Linear directly.

Every case here runs against a STUBBED httpx transport. Nothing in this file reaches a Linear
workspace, and nothing in it holds a real credential: `_API_KEY` below is a string shaped like
one so the "this never leaks" assertions have something recognisable to search for.

Two properties carry the file:

- **HTTP 200 is not success.** GraphQL answers `200` for a request it refused, so a `200` with a
  populated `errors` array and a `200` with `issueCreate.success: false` are both failures. An
  adapter that read the status code alone would mark the row `delivered` with a null ticket id,
  alarm nothing, and lose the bug report — with the reporter already told `202`.
- **The retryable/permanent split is the retry policy's only input.** A rate limit retried is a
  ticket filed a minute later; a rate limit marked permanent is a report dropped. A revoked key
  retried is six identical refusals over 24 h behind a `pending` row nobody alarms on.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from report_intake.delivery.dispatch import TicketDispatcher
from report_intake.delivery.linear_sink import MAX_ECHOED_ERRORS, LinearSink
from report_intake.delivery.ports import (
    Delivered,
    PermanentDeliveryError,
    RetryableDeliveryError,
    TicketContent,
    TicketSink,
)
from report_intake.delivery.registry import close_sink
from report_intake.reports.binding import bind
from report_intake.reports.models import TICKET_ID_MAX_LENGTH, TICKET_URL_MAX_LENGTH

from .test_report_schema import a_report, as_body

pytestmark = pytest.mark.asyncio

_API_URL = "https://linear.test/graphql"
_API_KEY = "lin_api_thisisnotarealcredential"
_TEAM_ID = "b9c1f0de-team"
_REF = "r_8f21c0"

_ISSUE = {
    "id": "b0a1c2d3-issue",
    "identifier": "OME-1042",
    "url": "https://linear.app/openmined/issue/OME-1042",
}
_CREATED: dict[str, Any] = {"data": {"issueCreate": {"success": True, "issue": _ISSUE}}}


def _sink(transport: httpx.MockTransport) -> LinearSink:
    """The real adapter over a fake network, so these tests drive its own request building and
    response decoding rather than a stub that agrees with it by construction."""
    return LinearSink(
        api_key=_API_KEY,
        team_id=_TEAM_ID,
        api_url=_API_URL,
        timeout_s=3.0,
        transport=transport,
    )


def _answering(payload: Any, status_code: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, str):
            return httpx.Response(status_code, text=payload)
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handle)


def _raising(error: type[httpx.RequestError], message: str = "no") -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        raise error(message, request=request)

    return httpx.MockTransport(handle)


def _graphql_error(**members: Any) -> dict[str, Any]:
    return {"errors": [{"message": "Argument Validation Error", **members}]}


def _content() -> TicketContent:
    return TicketContent(
        ref=_REF,
        title="[r_8f21c0] ExecutionError: the candidate never answered",
        body="## Report\n\n- ref: r_8f21c0",
    )


class _Captured(logging.Handler):
    """Every record this service emitted, collected from its own logger tree.

    Not `caplog`, which installs its handler on the ROOT logger: `logs.configure` sets
    `propagate = False` across the `report_intake` tree on purpose, and any test in this session
    that builds an app has already called it — so a root handler would see nothing and the
    assertions below would pass for the wrong reason.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        """Formatted, not raw: an argument that never reaches `%s` would otherwise hide a value
        that a real handler's formatter puts straight into the stream."""
        return "\n".join(self.format(record) for record in self.records)


@contextmanager
def _capturing(level: int = logging.DEBUG) -> Iterator[_Captured]:
    logger = logging.getLogger("report_intake")
    handler = _Captured()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


# --- a filed issue -----------------------------------------------------------------------------


async def test_a_created_issue_comes_back_as_its_identifier_and_its_url() -> None:
    """Spec §2.2's success shape: `ticket.id` is the human key a triager quotes (`OME-1042`),
    not the UUID beside it, and `ticket.url` is where the reporter's `ref` ended up."""
    result = await _sink(_answering(_CREATED)).deliver(_content())

    assert result == Delivered(ticket_id="OME-1042", ticket_url=_ISSUE["url"])


async def test_the_adapter_satisfies_the_port() -> None:
    """The registry hands `create_app` a `TicketSink`; this makes that true of the concrete class
    rather than only of the annotation."""
    assert isinstance(_sink(_answering(_CREATED)), TicketSink)


async def test_the_mutation_carries_the_rendered_title_body_and_the_configured_team() -> None:
    """`render.py` decides what a ticket says and this adapter is transport. The input is built
    from named members only — an input spread from a mapping is one refactor away from
    forwarding a member this service has never seen."""
    sent: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json=_CREATED)

    content = _content()
    await _sink(httpx.MockTransport(capture)).deliver(content)

    assert sent["variables"]["input"] == {
        "title": content.title,
        "description": content.body,
        "teamId": _TEAM_ID,
    }
    assert "issueCreate" in sent["query"]


async def test_the_api_key_is_sent_bare_and_never_with_a_bearer_prefix() -> None:
    """Linear authenticates a personal/scoped API key with `Authorization: <key>` and reserves
    `Bearer <token>` for OAuth. A `Bearer` prefix here is a 401 on every single report."""
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json=_CREATED)

    await _sink(httpx.MockTransport(capture)).deliver(_content())

    assert seen["authorization"] == _API_KEY


# --- HTTP 200 that is not a success ------------------------------------------------------------


async def test_a_200_carrying_a_populated_errors_array_is_a_failure_not_a_ticket() -> None:
    """THE TRAP. GraphQL answers `200` for a request it refused; an adapter that checks only the
    status code reports every one of those as a filed ticket."""
    with pytest.raises(PermanentDeliveryError, match="Argument Validation Error"):
        await _sink(_answering(_graphql_error())).deliver(_content())


async def test_an_errors_array_beside_a_populated_data_member_is_still_a_failure() -> None:
    """A GraphQL response may carry both, and a reader that trusts `data` first would report a
    refused mutation as a filed ticket — which is the same bug wearing a different hat."""
    body = {**_CREATED, **_graphql_error()}

    with pytest.raises(PermanentDeliveryError):
        await _sink(_answering(body)).deliver(_content())


async def test_success_false_is_a_failure_even_under_a_healthy_status_line() -> None:
    """Linear evaluated the request and declined it. Permanent: the same input declines again."""
    body = {"data": {"issueCreate": {"success": False, "issue": None}}}

    with pytest.raises(PermanentDeliveryError, match="success"):
        await _sink(_answering(body)).deliver(_content())


async def test_an_issue_linear_will_not_name_is_permanent_rather_than_a_duplicate() -> None:
    """`success: true` means the issue very probably exists, so a retry would file a duplicate of
    a ticket nobody can name. `failed` sends a human to look, and what they find is that this
    adapter and Linear's response shape have stopped agreeing."""
    body = {"data": {"issueCreate": {"success": True, "issue": {"id": "b0a1c2d3-issue"}}}}

    with pytest.raises(PermanentDeliveryError, match="identifier"):
        await _sink(_answering(body)).deliver(_content())


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("identifier", "OME-" + "9" * TICKET_ID_MAX_LENGTH),
        ("url", "https://linear.app/openmined/issue/" + "x" * TICKET_URL_MAX_LENGTH),
    ],
)
async def test_a_ticket_reference_wider_than_its_column_is_permanent_not_a_second_issue(
    member: str, value: str
) -> None:
    """Same reasoning as the unnameable issue above — it EXISTS, so a retry files a duplicate —
    but this one is worth its own check because of where it would otherwise surface. Left to
    tortoise's validator at `save`, it is a `StorageUnavailable` that both writers of that column
    swallow by design, leaving the row `pending` with `attempts` unmoved. `attempts` is the retry
    budget's only input, so the sweep would re-claim it every five minutes for the whole 90-day
    retention window, filing a fresh Linear issue on each pass and never reaching MAX_ATTEMPTS."""
    body = {"data": {"issueCreate": {"success": True, "issue": {**_ISSUE, member: value}}}}

    with pytest.raises(PermanentDeliveryError, match="retry would file a second one"):
        await _sink(_answering(body)).deliver(_content())


async def test_a_rate_limit_named_in_the_extensions_code_is_retried_not_failed() -> None:
    """The reference page publishes no thresholds, so the code is what says "not now". Marked
    permanent, a rate limit during a burst of reports would drop every one of them."""
    body = _graphql_error(extensions={"code": "RATELIMITED"}, message="rate limit exceeded")

    with pytest.raises(RetryableDeliveryError):
        await _sink(_answering(body)).deliver(_content())


@pytest.mark.parametrize("code", ["RATE_LIMITED", "rate-limited", "TOO_MANY_REQUESTS"])
async def test_a_rate_limit_is_recognised_however_the_code_spells_it(code: str) -> None:
    """The enumeration is not published, and the same condition is spelled three ways by three
    APIs. Generous on exactly the one condition a healthy deployment actually meets."""
    with pytest.raises(RetryableDeliveryError):
        await _sink(_answering(_graphql_error(extensions={"code": code}))).deliver(_content())


async def test_a_validation_error_is_permanent_rather_than_retried_six_times() -> None:
    """A body Linear will never accept does not become acceptable on the sixth attempt — that is
    six pointless calls spread over 24 h, ending in the same `failed` row."""
    body = _graphql_error(extensions={"code": "ARGUMENT_VALIDATION_ERROR"}, path=["issueCreate"])

    with pytest.raises(PermanentDeliveryError, match="issueCreate"):
        await _sink(_answering(body)).deliver(_content())


async def test_a_server_side_graphql_error_is_retryable() -> None:
    """Linear's own words for "our fault" are not this report's fault either."""
    with pytest.raises(RetryableDeliveryError):
        await _sink(
            _answering(_graphql_error(extensions={"code": "INTERNAL_SERVER_ERROR"}))
        ).deliver(_content())


async def test_a_malformed_errors_array_does_not_crash_the_adapter() -> None:
    """Somebody else's JSON, read defensively — but still a failure: an `errors` member this
    module cannot parse is not permission to call the ticket delivered."""
    body = {"errors": [7, {"extensions": "not-an-object"}, {"message": None}]}

    with pytest.raises(PermanentDeliveryError, match="no message given"):
        await _sink(_answering(body)).deliver(_content())


async def test_an_empty_errors_array_is_not_a_failure() -> None:
    """`errors: []` is the shape some servers send on success. Treating it as a refusal would
    fail a report that WAS filed, and the retry would then file it twice."""
    body = {**_CREATED, "errors": []}

    assert await _sink(_answering(body)).deliver(_content()) == Delivered(
        ticket_id="OME-1042", ticket_url=_ISSUE["url"]
    )


async def test_a_wall_of_graphql_errors_is_summarized_rather_than_repeated_whole() -> None:
    """The text is a third party's and it ends up in a log record. Bounded, and it says how many
    it left out rather than pretending there were three."""
    body = {"errors": [{"message": "x" * 500} for _ in range(9)]}

    with pytest.raises(PermanentDeliveryError) as raised:
        await _sink(_answering(body)).deliver(_content())

    assert f"and {9 - MAX_ECHOED_ERRORS} more" in str(raised.value)
    assert len(str(raised.value)) < 1000


# --- the HTTP statuses GraphQL never gets to answer --------------------------------------------


@pytest.mark.parametrize("status", [429, 408, 500, 502, 503, 504])
async def test_a_rate_limited_or_broken_linear_is_retried_not_failed(status: int) -> None:
    """All of these are "not now". Marked permanent, a five-minute Linear outage would drop every
    report filed during it — and the row would be `failed`, which is never re-attempted."""
    with pytest.raises(RetryableDeliveryError):
        await _sink(_answering({}, status_code=status)).deliver(_content())


@pytest.mark.parametrize("status", [401, 403])
async def test_a_rejected_credential_is_permanent_not_retried(status: int) -> None:
    """No number of retries turns a revoked key into an accepted one, and `pending` would hide it
    behind a queue that quietly grows. `failed` is the state an operator is alarmed on."""
    with pytest.raises(PermanentDeliveryError, match="credentials"):
        await _sink(_answering({}, status_code=status)).deliver(_content())


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_another_4xx_is_permanent_because_the_next_request_is_identical(
    status: int,
) -> None:
    """This adapter builds the same request every time, so a request Linear calls malformed stays
    malformed — the remaining five attempts would be answered the same way."""
    with pytest.raises(PermanentDeliveryError):
        await _sink(_answering({}, status_code=status)).deliver(_content())


@pytest.mark.parametrize("code", ["RATELIMITED", "INTERNAL_SERVER_ERROR"])
async def test_a_rate_limit_linear_spells_with_a_status_and_a_code_is_still_retried_not_failed(
    code: str,
) -> None:
    """One condition, two spellings, and Linear may send both at once. Ruling on the status to
    completion before the body was read made `HTTP 400` + `extensions.code: RATELIMITED` PERMANENT
    with the errors array never opened — and a `failed` row is one `OME-1010`'s sweep never
    re-attempts, so that is a dropped bug report whose reporter was already told `202`."""
    body = _graphql_error(extensions={"code": code}, message="rate limit exceeded")

    with pytest.raises(RetryableDeliveryError):
        await _sink(_answering(body, status_code=400)).deliver(_content())


async def test_a_4xx_whose_body_names_nothing_transient_stays_permanent() -> None:
    """The other side of reading the body first: it may only ever RESCUE a status, never soften
    one. A validation error under a `400` is still a request Linear refuses identically next
    time, and the message names the status that actually arrived rather than 200."""
    body = _graphql_error(extensions={"code": "ARGUMENT_VALIDATION_ERROR"})

    with pytest.raises(PermanentDeliveryError, match="HTTP 422") as raised:
        await _sink(_answering(body, status_code=422)).deliver(_content())

    assert "Argument Validation Error" in str(raised.value)


async def test_a_4xx_with_a_body_this_adapter_cannot_read_keeps_the_status_verdict() -> None:
    """Reading the body must not RECLASSIFY a status it has nothing to say about. A `404` of HTML
    — a wrong API URL, an auth proxy — carries no `errors` array, so the status stands and the
    row is `failed` rather than pending on a body that will never contain a code."""
    with pytest.raises(PermanentDeliveryError, match="HTTP 404"):
        await _sink(_answering("<html>not found</html>", status_code=404)).deliver(_content())


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_credential_is_permanent_even_when_the_body_names_a_rate_limit(
    status: int,
) -> None:
    """The credential is decided on the status ALONE and before any body is read. A revoked key
    behind something that also answers "rate limited" must not become a queue that quietly grows —
    `failed` is the state an operator is alarmed on."""
    body = _graphql_error(extensions={"code": "RATELIMITED"})

    with pytest.raises(PermanentDeliveryError, match="credentials"):
        await _sink(_answering(body, status_code=status)).deliver(_content())


async def test_a_status_this_adapter_cannot_read_is_treated_as_transient() -> None:
    """`ports.py`'s rule: an adapter unsure which error it is holding raises the retryable one.
    Six wasted calls are cheaper than a dropped bug report, and the budget running out turns
    persistent uncertainty into `failed` on its own."""
    with pytest.raises(RetryableDeliveryError):
        await _sink(_answering({}, status_code=302)).deliver(_content())


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError],
)
async def test_a_linear_that_cannot_be_reached_is_retried(error: type[httpx.RequestError]) -> None:
    """Timeout, DNS, connection refused, a protocol error — one thing to the retry policy: Linear
    was not reached, and this report will be reached for again."""
    with pytest.raises(RetryableDeliveryError, match="could not be reached"):
        await _sink(_raising(error)).deliver(_content())


async def test_a_sign_in_page_in_front_of_the_api_is_diagnosed_rather_than_believed() -> None:
    """An auth proxy answers `200` with HTML. Believing its absent `errors` and absent `data`
    would report every report as filed; this says what actually arrived, and names the host so an
    operator can see which endpoint is answering."""
    with pytest.raises(RetryableDeliveryError, match="not JSON") as raised:
        await _sink(_answering("<html>sign in</html>")).deliver(_content())

    assert "linear.test" in str(raised.value)


async def test_json_that_is_not_an_object_is_a_failure_too() -> None:
    with pytest.raises(RetryableDeliveryError):
        await _sink(_answering(["issueCreate"])).deliver(_content())


async def test_a_200_with_no_data_member_at_all_is_a_failure() -> None:
    """No `errors`, no `data` — nothing was created, and nothing here may say otherwise."""
    with pytest.raises(PermanentDeliveryError):
        await _sink(_answering({})).deliver(_content())


# --- the credential never leaves this object ---------------------------------------------------


def _failing_transports() -> list[httpx.MockTransport]:
    """One transport per failure path in this module, so the leak assertions below cover the
    whole surface rather than the one case somebody remembered."""
    return [
        _answering({}, status_code=401),
        _answering({}, status_code=429),
        _answering({}, status_code=500),
        _answering({}, status_code=404),
        _answering({}, status_code=302),
        _answering(_graphql_error()),
        _answering(_graphql_error(extensions={"code": "RATELIMITED"})),
        _answering({"data": {"issueCreate": {"success": False}}}),
        _answering({"data": {"issueCreate": {"success": True, "issue": {}}}}),
        _answering("<html>sign in</html>"),
        _raising(httpx.ConnectError),
    ]


async def test_the_api_key_never_appears_in_an_exception_from_any_failure_path() -> None:
    """Every one of these exceptions is interpolated into the dispatcher's log line, so a key in
    the message is a key in the cluster's logs. Asserted rather than trusted: this is the property
    a well-meant "include the request in the error" edit breaks first."""
    for transport in _failing_transports():
        with pytest.raises((RetryableDeliveryError, PermanentDeliveryError)) as raised:
            await _sink(transport).deliver(_content())

        assert _API_KEY not in str(raised.value)
        assert _API_KEY not in repr(raised.value)


async def test_the_api_key_never_reaches_a_log_record_on_any_path() -> None:
    """Driven through `TicketDispatcher`, which is what actually logs a delivery failure — at
    ERROR, with the exception interpolated, and with a traceback for anything undeclared. Captured
    across the whole `report_intake` tree and FORMATTED, so an argument that never reaches `%s`
    cannot hide a value a real handler would have written to the stream.
    """
    document = bind(as_body(a_report())).document

    with _capturing() as captured:
        for transport in [*_failing_transports(), _answering(_CREATED)]:
            dispatcher = TicketDispatcher(_sink(transport), timeout=3.0)
            await dispatcher.dispatch(ref=_REF, document=document, caller_email=None)

    assert captured.records, "the dispatcher logged nothing at all, so this asserts nothing"
    assert _API_KEY not in captured.text


async def test_the_api_key_is_not_in_the_adapters_repr() -> None:
    """A `repr` is what a traceback renders for `self`, what a debugger shows, and what a future
    `@dataclass` on this class would generate for free — including the credential."""
    sink = _sink(_answering(_CREATED))

    assert _API_KEY not in repr(sink)
    assert _TEAM_ID in repr(sink)


# --- lifecycle ---------------------------------------------------------------------------------


async def test_the_connection_pool_is_closed_on_shutdown_and_closing_twice_is_harmless() -> None:
    """The app's lifespan closes the sink it built; a second close must not be an error at
    teardown, and closing one that never filed anything must not be either."""
    sink = _sink(_answering(_CREATED))
    await sink.deliver(_content())

    await close_sink(sink)
    await close_sink(sink)
    await close_sink(_sink(_answering(_CREATED)))


async def test_one_client_serves_every_report_rather_than_one_per_delivery() -> None:
    """A connection pool per report is a TLS handshake inside a 3 s deadline the retry queue also
    spends — and it is a pool nothing closes. Lazy, so an app that never files anything opens
    nothing at all, which is why `create_app` can build this adapter in a test with no cost.

    Reaches for the private attribute deliberately: "the same client" has no observable proxy
    through `httpx.MockTransport`, and the alternative is asserting nothing.
    """
    sink = _sink(_answering(_CREATED))
    assert sink._client is None

    await sink.deliver(_content())
    opened = sink._client
    await sink.deliver(_content())

    assert opened is not None
    assert sink._client is opened
    await close_sink(sink)
