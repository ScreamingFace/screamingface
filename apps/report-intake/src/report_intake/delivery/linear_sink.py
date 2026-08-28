"""`LinearSink` — the adapter that files a ticket into Linear directly, over its GraphQL API.

**CLAUDE.md rule 9 governs SELECTING this adapter, and this file does not select it.** Rule 9 as
written says Linear is reached through MCP only and that API tokens and raw GraphQL are forbidden
in product code; the amendment that would carve out an exception for this service (`OME-976`) has
not been made, and this pass does not make it. So say it plainly: **this module is inert.** It is
imported by one line of `delivery/registry.py`'s name table and by nothing else; `create_app`
constructs it only when an operator sets `REPORT_INTAKE_TICKET_SINK=linear`, and `build_sink`
refuses to start that deployment unless the same operator also supplied an API key and a team id.
A deployment that keeps the `queue` default — which is every deployment today (spec §9) — makes
no outbound call to Linear, holds no Linear credential, and is unchanged by this file existing.
Selecting it is the decision rule 9 governs; it belongs to whoever owns that rule, in a
deployment, not to this repo by shipping the code the day the rule moves.

THE TRAP THIS MODULE EXISTS NOT TO FALL INTO: **GraphQL answers HTTP 200 for a request it
refused.** A response carries an `errors` array, and `data.issueCreate.success` can be `false`,
both under a perfectly healthy status line. An adapter that checks `response.status_code` and
nothing else reports every one of those as a delivered ticket: the row goes `delivered` with a
null `ticket_id`, nothing is alarmed, the reporter was told `202`, and the bug report exists
nowhere. Both are checked here, and neither is a success.

THE ERROR MAPPING IS DELIBERATE, because the `Retryable`/`Permanent` split in `delivery/ports.py`
is the retry policy's only input — `OME-1010` re-attempts a `pending` row six times over 24 h and
never touches a `failed` one:

- **Retryable** — a transport failure or timeout (Linear or the network, not this report), HTTP
  `5xx`, HTTP `429`, HTTP `408`, and a GraphQL `extensions.code` naming a rate limit or a server
  error **under any status, not only `200`**. All of these are "not now", and the same request
  will work later.
- **Permanent** — HTTP `401`/`403` (the key is wrong, revoked, or unscoped), any other `4xx`
  *whose body names nothing transient* (this adapter builds the same request every time, so a
  request Linear calls malformed stays malformed), a GraphQL error that is not transient (a
  validation error, a team id that does not exist), and `success: false`. Retrying those six
  times helps nobody: it is six identical refusals spread over a day, and the row ends `failed`
  regardless.

THE STATUS IS NOT RULED ON BEFORE THE BODY IS READ, and that ordering is the correction `OME-1002`'s
review pass made. One condition — a rate limit — is spelled two ways, and Linear is free to send
both at once: a status AND an `extensions.code`. A `deliver` that classified the status to
completion first made an `HTTP 400` carrying `{"errors":[{"extensions":{"code":"RATELIMITED"}}]}`
*permanent* with the `errors` array never read, which marks the row `failed` — and `OME-1010`'s
sweep never re-attempts a `failed` row, so that is a dropped bug report whose reporter was already
told `202`. `401`/`403` and the retryable statuses are still decided on the status alone (no body
is needed to know a credential was refused, or that Linear is down); everything else reads the
body first and lets a transient code win, falling through to the status verdict only when the
body names nothing.
- **Anything this module cannot classify is Retryable**, per `ports.py`: an adapter unsure which
  it is holding raises the retryable one, and the retry budget running out turns persistent
  uncertainty into `failed` on its own. Six wasted calls are cheaper than a dropped bug report.

INVARIANT: **the API key never appears in a log record, in a `repr`, or in an exception message.**
It is a long-lived credential to the private tracker the team works in, and every failure path
here ends in a log line the dispatcher writes at ERROR. The key is held in one private attribute,
set as a request header and nowhere else, and `__repr__` is written out by hand so that a future
`@dataclass` on this class cannot start printing it. `tests/unit/test_linear_sink.py` asserts
this rather than trusting it — of everything in this module it is the property most likely to be
broken by a well-meant "include the request in the error" edit.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from ..reports.models import TICKET_ID_MAX_LENGTH, TICKET_URL_MAX_LENGTH
from .ports import (
    Delivered,
    PermanentDeliveryError,
    RetryableDeliveryError,
    SinkResult,
    TicketContent,
)

logger = logging.getLogger(__name__)

ISSUE_CREATE = """\
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      id
      identifier
      url
      title
    }
  }
}
"""
"""The one mutation this service sends. `identifier` as well as `id`, because `identifier` is the
human key (`OME-1042`) spec §2.2's success shape returns and `id` is the UUID; asking for both
costs one line and means the response carries whichever a future reader needs."""

_RETRYABLE_STATUS = frozenset({httpx.codes.REQUEST_TIMEOUT, httpx.codes.TOO_MANY_REQUESTS})
"""`429` is the rate limit — the reference page publishes no thresholds, so it is recognised by
status rather than by arithmetic — and `408` is a timeout wearing a status code."""

_PERMANENT_STATUS = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})
"""The credential, not the report. No number of retries turns a rejected key into an accepted
one, and a `pending` row would hide a revoked credential behind a queue that quietly grows."""

_RETRYABLE_ERROR_CODES = frozenset(
    {"ratelimited", "toomanyrequests", "internalservererror", "serviceunavailable", "timeout"}
)
"""`errors[].extensions.code` values that mean "not now" rather than "not this".

Matched against a NORMALIZED code (lower-cased, letters only), because the reference page does
not publish the enumeration and the same condition is spelled `RATE_LIMITED`, `RATELIMITED` and
`rate-limited` by different APIs. Any code that still contains `ratelimit` after normalizing is
treated as a rate limit too, which is the one condition it is worth being generous about: it is
the failure a healthy deployment actually meets.
"""

_NOT_LETTERS = re.compile(r"[^a-z]")
_WHITESPACE = re.compile(r"\s+")

MAX_ECHOED_ERRORS = 3
MAX_ECHOED_CHARS = 200
"""How much of somebody else's error text is repeated into ours. Bounded because the message is
a third party's string arriving on a path that ends in a log line, and an unbounded one turns a
log record into a page of GraphQL."""


class LinearSink:
    """One POST per report, inside a deadline. Answers `Delivered`, or raises from the taxonomy.

    The client is created on first delivery and closed by `registry.close_sink`, which the app's
    lifespan calls. Lazily, for the same reason `HttpTurnstileVerifier` does it: `create_app` runs
    at import in the deployed process and in every test that builds an app, and most of those
    never file anything.
    """

    def __init__(
        self,
        *,
        api_key: str,
        team_id: str,
        api_url: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._team_id = team_id
        self._api_url = api_url
        self._timeout_s = timeout_s
        # httpx's own injection point, so a test drives the real request building and response
        # decoding below rather than a stub that agrees with them by construction. `None` is
        # httpx's default transport, which is what the deployed process uses.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def __repr__(self) -> str:
        """The team and the endpoint. NEVER the key.

        Written out rather than inherited: the default `object.__repr__` is already safe, but a
        later `@dataclass(frozen=True)` on this class — the shape every other type in this package
        has — would generate one that prints every field, including the credential, into any
        traceback that renders `self`.
        """
        return f"LinearSink(team_id={self._team_id!r}, api_url={self._api_url!r})"

    async def deliver(self, content: TicketContent) -> SinkResult:
        """File `content` as a Linear issue and answer where it landed.

        THE ORDER OF THESE LINES IS THE ERROR POLICY — see the module docstring for why the body
        is read before a status other than `401`/`403`/`5xx`/`429`/`408` is ruled on.
        """
        response = await self._post(content)
        status = response.status_code
        _raise_for_refused_credential(status)
        _raise_for_transient_status(status)
        # The body under a healthy status is load-bearing (GraphQL answers `200` for a refusal),
        # so a `200` this module cannot decode is itself a failure. Under any other status the
        # status already carries a verdict, so an undecodable body is simply nothing to add.
        body = _decoded(response) if status == httpx.codes.OK else _decoded_or_nothing(response)
        _raise_for_graphql_errors(body, status)
        _raise_for_refusing_status(status)
        return _delivered(body, content.ref)

    async def aclose(self) -> None:
        """Close the connection pool, if one was ever opened. Safe to call twice."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, content: TicketContent) -> httpx.Response:
        try:
            return await self._client_for().post(
                self._api_url,
                json={"query": ISSUE_CREATE, "variables": {"input": self._input(content)}},
            )
        except httpx.HTTPError as exc:
            # Timeout, DNS, connection refused, a protocol error — all one thing to the retry
            # policy: Linear was not reached, and this report will be reached for again.
            # `httpx.HTTPError` is the base of every transport and protocol error httpx raises,
            # and `TimeoutException` is under it. The message names the error's TYPE rather than
            # repeating its text, so nothing httpx chose to put in it can carry a header through.
            raise RetryableDeliveryError(
                f"Linear could not be reached ({type(exc).__name__})"
            ) from exc

    def _client_for(self) -> httpx.AsyncClient:
        if self._client is None:
            # Constructing an AsyncClient is synchronous and binds no loop, and this block has no
            # `await` in it, so two concurrent first deliveries on one event loop cannot both run
            # it. The key is set ONCE, here, and is never a parameter of a per-request call.
            #
            # NOTE the bare key: Linear authenticates a personal/scoped API key with
            # `Authorization: <key>` and reserves `Bearer <token>` for OAuth. A `Bearer` prefix on
            # this key is a 401 on every report — permanent, so it would surface as a `failed` row
            # rather than as a queue quietly growing, which is why that mapping matters.
            self._client = httpx.AsyncClient(
                timeout=self._timeout_s,
                transport=self._transport,
                headers={"Authorization": self._api_key, "Content-Type": "application/json"},
            )
        return self._client

    def _input(self, content: TicketContent) -> dict[str, str]:
        """`IssueCreateInput`, from the strings the port handed us and nothing else.

        Named members only, exactly as `render.py` renders named fields only: an input built by
        spreading a mapping is one refactor away from forwarding a member this service has never
        seen. `description` is Markdown, which is what `render.py` produces.
        """
        return {"title": content.title, "description": content.body, "teamId": self._team_id}


def _raise_for_refused_credential(status: int) -> None:
    """The one permanent verdict that needs no body. Runs FIRST, so a sign-in page's HTML under a
    `401` cannot turn a revoked key into "something else is answering here"."""
    if status in _PERMANENT_STATUS:
        raise PermanentDeliveryError(
            f"Linear rejected this service's credentials with HTTP {status}. The API key is "
            "missing, wrong, revoked, or lacks the scope to create an issue — no number of "
            "retries changes any of those."
        )


def _raise_for_transient_status(status: int) -> None:
    """The statuses that mean "not now" on their own. Also body-free: a `503` from a load balancer
    carries no GraphQL at all, and reading one would only be a second way to reach `pending`."""
    if status in _RETRYABLE_STATUS or status >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise RetryableDeliveryError(f"Linear answered HTTP {status}; the report stays pending")


def _raise_for_refusing_status(status: int) -> None:
    """What is left of the status once the body has had its say, per `ports.py`'s rule that an
    adapter unsure which error it is holding raises the recoverable one.

    Reached only when the body named nothing transient, so a `4xx` here really is a request Linear
    will refuse identically next time. Anything outside `2xx`/`4xx` — a redirect, a `1xx` — is a
    response this adapter cannot read, and a stored report is not marked `failed` on a guess.
    """
    if status == httpx.codes.OK:
        return
    if status >= httpx.codes.BAD_REQUEST:
        raise PermanentDeliveryError(
            f"Linear answered HTTP {status} to a request this adapter builds the same way every "
            "time, so the next five attempts would be answered identically"
        )
    raise RetryableDeliveryError(
        f"Linear answered HTTP {status}, which is not a response this adapter can read; treating "
        "it as transient so a stored report is not marked failed on a guess"
    )


def _decoded(response: httpx.Response) -> Mapping[str, Any]:
    """The response body as an object, or a retryable failure saying what arrived instead.

    An auth proxy's sign-in page in front of the API URL answers `200` with HTML, and a body that
    is not a JSON object is the shape that produces. Retryable rather than permanent: the URL
    being fronted by something is an operator's mistake to fix, and `pending` keeps the report
    deliverable once they fix it.

    The HOST, never the whole URL: this string ends up in a log line, and a URL is the one place
    somebody eventually writes a credential (`https://user:token@…`). The host is the whole
    diagnostic anyway — "something other than Linear is answering here".
    """
    try:
        body = response.json()
    except ValueError as exc:
        raise RetryableDeliveryError(
            "Linear answered something that is not JSON, which is what a sign-in page in front "
            f"of {response.request.url.host} looks like"
        ) from exc
    if not isinstance(body, Mapping):
        raise RetryableDeliveryError("Linear answered JSON that is not an object")
    return body


def _decoded_or_nothing(response: httpx.Response) -> Mapping[str, Any]:
    """The response body as an object, or an empty one — for a status that already has a verdict.

    Never raises, which is the whole difference from :func:`_decoded`: this is only ever called
    under a status the caller is about to rule on anyway, so a body that is HTML, or JSON that is
    not an object, is simply nothing the `errors` array can add. Returning `{}` leaves the status
    verdict exactly where it was before the body was consulted — which is what keeps this reading
    strictly additive rather than a reclassification of every non-`200` with an unreadable body.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, Mapping) else {}


def _raise_for_graphql_errors(body: Mapping[str, Any], status: int) -> None:
    """THE TRAP, closed. A populated `errors` array is a failure — including at HTTP 200.

    Checked before `data`, because a GraphQL response may legitimately carry both — a partial
    result beside the error that produced it — and a reader that trusts `data` first would report
    a refused mutation as a filed ticket.

    `status` is carried only so the message names what actually arrived. It is NOT part of the
    verdict: a retryable `extensions.code` wins under every status, which is the point of reading
    the body before the status is ruled on.
    """
    errors = body.get("errors")
    if not isinstance(errors, Sequence) or isinstance(errors, str) or not errors:
        return
    summary = _summarized(errors)
    if any(_is_retryable_code(code) for code in _codes(errors)):
        raise RetryableDeliveryError(
            f"Linear refused this request for now and it stays pending: {summary}"
        )
    raise PermanentDeliveryError(
        f"Linear answered HTTP {status} with a GraphQL error, so no issue was created: {summary}"
    )


def _delivered(body: Mapping[str, Any], ref: str) -> Delivered:
    """The issue, or the reason a `200` with no `errors` still did not create one."""
    result = _mapping(body.get("data"), "issueCreate")
    if result.get("success") is not True:
        raise PermanentDeliveryError(
            "Linear answered HTTP 200 and issueCreate.success is not true, which is a refusal "
            "with no error attached — the same input would be refused again"
        )
    issue = _mapping(result, "issue")
    identifier, url = issue.get("identifier"), issue.get("url")
    if not isinstance(identifier, str) or not isinstance(url, str) or not identifier or not url:
        # Permanent, and loud. `success: true` means the issue very probably EXISTS, so retrying
        # would file a duplicate of a ticket nobody can name; a `failed` row sends a human to
        # look, and what they will find is that this adapter and Linear's response shape have
        # stopped agreeing — a defect in this repo rather than an outage.
        raise PermanentDeliveryError(
            "Linear reported the issue created but named neither an identifier nor a url for it, "
            "so this adapter cannot say where the report went"
        )
    _raise_for_unstorable_reference(identifier, url)
    logger.info("report %s was filed as Linear issue %s", ref, identifier)
    return Delivered(ticket_id=identifier, ticket_url=url)


def _raise_for_unstorable_reference(identifier: str, url: str) -> None:
    """A ticket reference wider than the column it lands in is a PERMANENT failure, not a retry.

    Same reasoning as the unnameable-issue branch above, and the same consequence if it is left
    out: the issue exists, so a retry files a duplicate. What makes this one worth its own check
    is where the failure would otherwise surface — at `report.save()`, as tortoise's validator,
    which `ReportStore` turns into `StorageUnavailable` and both writers deliberately swallow. The
    row would keep `delivery_state='pending'` with `attempts` unmoved, and `attempts` is the retry
    budget's ONLY input: the sweep would re-claim it every five minutes for the whole 90-day
    retention window, filing a fresh Linear issue on each pass and never reaching `MAX_ATTEMPTS`.

    `failed` instead, which is the state a human is sent to look at — and what they will find is
    the same class of thing as an unnameable issue: this adapter and Linear no longer agree about
    the shape of a reference. The widths are imported from the model rather than restated so the
    column and the check cannot drift apart.
    """
    if len(identifier) > TICKET_ID_MAX_LENGTH:
        raise PermanentDeliveryError(
            f"Linear named the issue with a {len(identifier)}-character identifier and this "
            f"service stores at most {TICKET_ID_MAX_LENGTH}. The issue exists but cannot be "
            "recorded, and a retry would file a second one."
        )
    if len(url) > TICKET_URL_MAX_LENGTH:
        raise PermanentDeliveryError(
            f"Linear gave the issue a {len(url)}-character url and this service stores at most "
            f"{TICKET_URL_MAX_LENGTH}. The issue exists but cannot be recorded, and a retry would "
            "file a second one."
        )


def _mapping(value: object, key: str) -> Mapping[str, Any]:
    """`value[key]` as a mapping, or an empty one. Somebody else's JSON, read defensively: a
    `null` where an object was expected is a normal GraphQL answer, not a `TypeError`."""
    if not isinstance(value, Mapping):
        return {}
    nested = value.get(key)
    return nested if isinstance(nested, Mapping) else {}


def _codes(errors: Sequence[Any]) -> list[str]:
    """Every `extensions.code`, defensively — the array is a third party's and may be anything."""
    return [
        code
        for error in errors
        if isinstance(code := _mapping(error, "extensions").get("code"), str)
    ]


def _is_retryable_code(code: str) -> bool:
    normalized = _NOT_LETTERS.sub("", code.lower())
    return normalized in _RETRYABLE_ERROR_CODES or "ratelimit" in normalized


def _summarized(errors: Sequence[Any]) -> str:
    """The errors' messages, bounded, on one line — never the request that provoked them.

    One line because a log record is one line by convention here, and bounded because this text
    is a third party's. The `path` is worth carrying and the `extensions` are not: the first names
    which field was refused, the second is a code this module has already acted on.
    """
    messages = [_one_line(_described(error)) for error in errors[:MAX_ECHOED_ERRORS]]
    remainder = len(errors) - MAX_ECHOED_ERRORS
    if remainder > 0:
        messages.append(f"(and {remainder} more)")
    return "; ".join(message for message in messages if message) or "no message given"


def _described(error: Any) -> str:
    if not isinstance(error, Mapping):
        return ""
    message = error.get("message")
    path = error.get("path")
    described = message if isinstance(message, str) else ""
    if isinstance(path, Sequence) and not isinstance(path, str):
        described = f"{described} at {'.'.join(str(part) for part in path)}"
    return described


def _one_line(text: str) -> str:
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if len(collapsed) <= MAX_ECHOED_CHARS:
        return collapsed
    return collapsed[: MAX_ECHOED_CHARS - 1].rstrip() + "…"


__all__ = ["ISSUE_CREATE", "LinearSink"]
