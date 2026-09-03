"""The bot gate an anonymous caller passes through (spec §7).

A mesh-verified caller never reaches this module: identity already answers the question the gate
asks. Everyone else presents a Cloudflare Turnstile token, which this service hands to
siteverify — it verifies nothing itself, exactly as it verifies no Access assertion itself.

The split this module exists to keep straight is `403` versus `503`, and it is not cosmetic.
Spec §8 gives the client two different instructions:

- **`403`** — the token was missing or Cloudflare rejected it. Fetch a fresh one and retry once.
- **`503`** — the gate could not be *evaluated*: siteverify was unreachable, too slow, answered
  something unreadable, or rejected OUR secret. Nothing was stored and nothing about the caller
  was wrong, so they retry the same request unchanged.

Answering `403` for the second case sends a caller to fetch a token that was never the problem,
and they would loop until they gave up. Answering `503` for the first would tell them to keep
retrying a token Cloudflare has already refused. That is why the error-code table below sorts
Cloudflare's failures into two piles rather than treating `success: false` as one thing.

INVARIANT: the token never appears in a log line or a problem detail. It arrives on an
unauthenticated request and the response goes back out on one; a rejected token is still a token
somebody might replay. The `error-codes` list is logged, because it names the failure without
naming the secret or the token.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from ..core.problem_catalogue import bot_gate_required, bot_gate_unverifiable

logger = logging.getLogger(__name__)

TURNSTILE_RESPONSE_HEADER = "CF-Turnstile-Response"
"""Where the widget's token arrives. Read here and nowhere else — deliberately absent from
`core/headers.read_allowed()`, like the identity header, because a general-purpose reader that
returns it is one refactor away from a caller that believes it without checking it."""

MAX_TOKEN_LENGTH = 4096
"""Longer than any token Cloudflare issues (documented at 2048 characters), and short enough that
this endpoint cannot be used to push an arbitrary body at siteverify. Over it, the token is
refused WITHOUT an outbound call: an unauthenticated caller must not be able to make this service
generate traffic on demand."""

_UNEVALUABLE_ERROR_CODES = frozenset(
    {
        # Our secret, not their token. A client cannot fix any of these by fetching a new one.
        "missing-input-secret",
        "invalid-input-secret",
        # Cloudflare's own words for "we built this wrong" and "try again later" — both are this
        # service's problem or Cloudflare's, never the caller's.
        "bad-request",
        "internal-error",
    }
)
"""Failures that mean the gate was not evaluated, so the answer is `503`.

Everything else — `invalid-input-response`, `timeout-or-duplicate`, an unrecognised code — is
treated as a rejected token and answered `403`. An unknown code is far more likely to be a new
way of saying "bad token" than a new way of saying "our fault", and `403` is the answer that
still ends with the report on the reporter's disk (spec §8) rather than in a retry loop.
"""


class TurnstileUnavailable(RuntimeError):
    """Siteverify could not be reached, or could not be believed. Becomes a `503`.

    Deliberately distinct from "the token is invalid", which is a plain ``False``. Merging them
    into one falsy answer is exactly how a client ends up being told to fetch a new token because
    Cloudflare was down.
    """


class TurnstileVerifier(Protocol):
    async def verify(self, token: str) -> bool:
        """True when Cloudflare vouched for the token. Raises :class:`TurnstileUnavailable`."""
        ...


class HttpTurnstileVerifier:
    """The real adapter: one POST to siteverify, inside a deadline.

    The client is created on first use and closed by the app's lifespan. Lazily, because
    `create_app` runs at import in the deployed process and in every test that builds an app,
    and most of those never verify anything.
    """

    def __init__(
        self,
        *,
        secret: str,
        verify_url: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret = secret
        self._verify_url = verify_url
        self._timeout_s = timeout_s
        # httpx's own injection point, so a test drives the real request-building and
        # response-decoding code above rather than a stub that agrees with it by construction.
        # `None` is httpx's default transport, which is what the deployed process uses.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def verify(self, token: str) -> bool:
        try:
            response = await self._post(token)
        except httpx.HTTPError as exc:
            # Timeout, DNS, connection refused, a malformed response — all one thing to the
            # caller: the gate did not run. `httpx.HTTPError` is the base of every transport and
            # protocol error httpx raises, and `TimeoutException` is under it.
            raise TurnstileUnavailable(f"siteverify could not be reached: {exc!r}") from exc
        if response.status_code != httpx.codes.OK:
            raise TurnstileUnavailable(f"siteverify answered HTTP {response.status_code}")
        return _believed(_decoded(response))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, token: str) -> httpx.Response:
        if self._client is None:
            # Constructing an AsyncClient is synchronous and binds no loop, and this block has no
            # `await` in it, so two concurrent first requests on one event loop cannot both run it.
            self._client = httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport)
        # NOTE the absence of `remoteip`. It is optional, and the address this process can see is
        # the mesh proxy's rather than the browser's — sending it would ask Cloudflare to match a
        # token against the wrong address and reject every legitimate caller.
        return await self._client.post(
            self._verify_url, data={"secret": self._secret, "response": token}
        )


def _decoded(response: httpx.Response) -> Mapping[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise TurnstileUnavailable("siteverify answered something that is not JSON") from exc
    if not isinstance(body, Mapping):
        raise TurnstileUnavailable("siteverify answered JSON that is not an object")
    return body


def _believed(body: Mapping[str, Any]) -> bool:
    """Cloudflare's verdict, or :class:`TurnstileUnavailable` when it is one we cannot act on."""
    if body.get("success") is True:
        return True
    codes = _error_codes(body)
    logger.info("turnstile rejected a token: %s", ", ".join(codes) or "no error codes given")
    if codes & _UNEVALUABLE_ERROR_CODES:
        raise TurnstileUnavailable(f"siteverify could not evaluate the gate: {sorted(codes)}")
    return False


def _error_codes(body: Mapping[str, Any]) -> set[str]:
    """The `error-codes` member, defensively: it is somebody else's JSON and may be anything."""
    codes = body.get("error-codes")
    if not isinstance(codes, list):
        return set()
    return {code for code in codes if isinstance(code, str)}


async def enforce(headers: Mapping[str, str], verifier: TurnstileVerifier) -> None:
    """Let an anonymous caller through, or raise the problem that says why not.

    ``headers`` must look up case-insensitively (starlette's ``Headers`` does).
    """
    token = (headers.get(TURNSTILE_RESPONSE_HEADER) or "").strip()
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise bot_gate_required(
            "this report was sent without mesh identity, so it needs a Cloudflare Turnstile "
            f"token in the {TURNSTILE_RESPONSE_HEADER} header; nothing was stored"
        )
    try:
        verified = await verifier.verify(token)
    except TurnstileUnavailable as exc:
        # Logged with the reason, answered without it: the reason names our own configuration.
        logger.warning("the turnstile gate could not be evaluated: %s", exc)
        raise bot_gate_unverifiable() from exc
    if not verified:
        raise bot_gate_required(
            "the Cloudflare Turnstile token was not accepted; fetch a fresh one and retry once. "
            "Nothing was stored"
        )
