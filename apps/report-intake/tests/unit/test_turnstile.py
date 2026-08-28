"""The bot gate, and the `403`/`503` split that is the whole reason it is a separate module.

Spec §8 gives a client two different instructions, and getting the split wrong loops them: told
to fetch a fresh token when Cloudflare was unreachable, they retry forever against a service that
was never going to answer; told to back off when their token was actually rejected, they never
fetch the one that would work.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from report_intake.core.problem import ProblemException
from report_intake.identity.turnstile import (
    MAX_TOKEN_LENGTH,
    TURNSTILE_RESPONSE_HEADER,
    HttpTurnstileVerifier,
    TurnstileUnavailable,
    enforce,
)

pytestmark = pytest.mark.asyncio

_VERIFY_URL = "https://siteverify.test/v0/siteverify"
_TOKEN = "a-token-from-the-widget"


class _StubVerifier:
    """Stands in for Cloudflare in the `enforce` tests: the transport is exercised separately."""

    def __init__(self, answer: bool | Exception) -> None:
        self.answer = answer
        self.tokens: list[str] = []

    async def verify(self, token: str) -> bool:
        self.tokens.append(token)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _verifier(transport: httpx.MockTransport) -> HttpTurnstileVerifier:
    """The real adapter over a fake network, so these tests drive its own request building and
    response decoding rather than a stub that agrees with it by construction."""
    return HttpTurnstileVerifier(
        secret="s3cret", verify_url=_VERIFY_URL, timeout_s=3.0, transport=transport
    )


def _answering(payload: Any, status_code: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, str):
            return httpx.Response(status_code, text=payload)
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handle)


async def test_a_report_with_no_bot_token_is_403_and_says_which_header_it_wanted() -> None:
    """Spec §10: an anonymous request with no Turnstile token is `403` and creates nothing."""
    with pytest.raises(ProblemException) as raised:
        await enforce({}, _StubVerifier(True))

    assert raised.value.problem.status == 403
    assert TURNSTILE_RESPONSE_HEADER in (raised.value.problem.detail or "")


async def test_a_rejected_bot_token_is_403_and_tells_the_client_to_fetch_a_fresh_one() -> None:
    with pytest.raises(ProblemException) as raised:
        await enforce({TURNSTILE_RESPONSE_HEADER: _TOKEN}, _StubVerifier(False))

    assert raised.value.problem.status == 403
    assert "fresh" in (raised.value.problem.detail or "")


async def test_an_accepted_bot_token_lets_the_report_through() -> None:
    verifier = _StubVerifier(True)

    await enforce({TURNSTILE_RESPONSE_HEADER: _TOKEN}, verifier)

    assert verifier.tokens == [_TOKEN]


async def test_an_unevaluable_gate_is_503_and_not_403() -> None:
    """Spec §10 names this one explicitly: the client must be told to retry unchanged rather than
    to fetch a new token, because the token was never the problem."""
    with pytest.raises(ProblemException) as raised:
        await enforce(
            {TURNSTILE_RESPONSE_HEADER: _TOKEN},
            _StubVerifier(TurnstileUnavailable("siteverify could not be reached")),
        )

    assert raised.value.problem.status == 503
    assert "retry the same request" in (raised.value.problem.detail or "")


async def test_an_oversized_token_is_refused_without_an_outbound_call() -> None:
    """An unauthenticated caller must not be able to make this service generate traffic, or push
    an arbitrary body at somebody else's API, on demand."""
    verifier = _StubVerifier(True)

    with pytest.raises(ProblemException) as raised:
        await enforce({TURNSTILE_RESPONSE_HEADER: "x" * (MAX_TOKEN_LENGTH + 1)}, verifier)

    assert raised.value.problem.status == 403
    assert verifier.tokens == []


async def test_no_refusal_ever_echoes_the_token() -> None:
    """It arrived on an unauthenticated request and the response goes back out on one; a rejected
    token is still a token somebody might replay."""
    secretish = "token-worth-replaying"

    for answer in (False, TurnstileUnavailable("down")):
        with pytest.raises(ProblemException) as raised:
            await enforce({TURNSTILE_RESPONSE_HEADER: secretish}, _StubVerifier(answer))

        assert secretish not in (raised.value.problem.detail or "")


async def test_cloudflare_vouching_for_a_token_is_a_pass() -> None:
    assert await _verifier(_answering({"success": True})).verify(_TOKEN)


async def test_cloudflare_refusing_a_token_is_a_rejection_not_an_outage() -> None:
    """`invalid-input-response` is the caller's problem, so it must stay a plain False and become
    a `403` rather than being swept into the unevaluable pile."""
    verifier = _verifier(_answering({"success": False, "error-codes": ["invalid-input-response"]}))

    assert await verifier.verify(_TOKEN) is False


async def test_a_duplicate_token_is_a_rejection() -> None:
    """`timeout-or-duplicate` means the token was already spent — a fresh one is exactly the fix,
    which is what `403` tells the client to get."""
    verifier = _verifier(_answering({"success": False, "error-codes": ["timeout-or-duplicate"]}))

    assert await verifier.verify(_TOKEN) is False


@pytest.mark.parametrize(
    "code", ["invalid-input-secret", "missing-input-secret", "bad-request", "internal-error"]
)
async def test_a_failure_that_is_ours_rather_than_the_callers_is_unevaluable(code: str) -> None:
    """Our own secret being wrong must not be answered `403`: the caller would fetch fresh tokens
    forever against a gate that cannot accept any of them."""
    verifier = _verifier(_answering({"success": False, "error-codes": [code]}))

    with pytest.raises(TurnstileUnavailable):
        await verifier.verify(_TOKEN)


async def test_an_unrecognised_error_code_is_treated_as_a_rejected_token() -> None:
    """The `403` path still ends with the report on the reporter's disk (spec §8); the `503` path
    ends in a retry loop, so an unknown code takes the recoverable one."""
    verifier = _verifier(_answering({"success": False, "error-codes": ["a-code-from-2027"]}))

    assert await verifier.verify(_TOKEN) is False


async def test_siteverify_being_unreachable_is_unevaluable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(TurnstileUnavailable):
        await _verifier(httpx.MockTransport(refuse)).verify(_TOKEN)


async def test_siteverify_timing_out_is_unevaluable() -> None:
    """The deadline is spec §6's shape: a reporter must not wait on somebody else's service."""

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(TurnstileUnavailable):
        await _verifier(httpx.MockTransport(hang)).verify(_TOKEN)


async def test_a_non_200_from_siteverify_is_unevaluable() -> None:
    with pytest.raises(TurnstileUnavailable):
        await _verifier(_answering({"success": True}, status_code=502)).verify(_TOKEN)


async def test_an_answer_that_is_not_json_is_unevaluable() -> None:
    """An auth-proxy sign-in page in front of siteverify answers `200` with HTML, and believing
    its falsy `success` would refuse every caller."""
    with pytest.raises(TurnstileUnavailable):
        await _verifier(_answering("<html>sign in</html>")).verify(_TOKEN)


async def test_json_that_is_not_an_object_is_unevaluable() -> None:
    with pytest.raises(TurnstileUnavailable):
        await _verifier(_answering(["success"])).verify(_TOKEN)


async def test_error_codes_that_are_not_strings_do_not_crash_the_gate() -> None:
    """Somebody else's JSON, so it is read defensively: a malformed list must degrade to a plain
    rejection rather than to a 500 on an unauthenticated request."""
    verifier = _verifier(_answering({"success": False, "error-codes": [{"nested": 1}, 7]}))

    assert await verifier.verify(_TOKEN) is False


async def test_the_secret_and_the_token_are_posted_as_form_fields_and_no_client_address_is() -> (
    None
):
    """`remoteip` is optional, and the address this process can see is the mesh proxy's rather
    than the browser's — sending it would ask Cloudflare to match against the wrong address."""
    sent: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        sent.update(dict(pair.split("=", 1) for pair in request.content.decode().split("&")))
        return httpx.Response(200, json={"success": True})

    await _verifier(httpx.MockTransport(capture)).verify(_TOKEN)

    assert sent["secret"] == "s3cret"
    assert "remoteip" not in sent


async def test_a_rejection_with_no_error_codes_is_still_only_a_rejection() -> None:
    """`error-codes` is optional and may be absent, or may not be a list at all. Reading it must
    not turn a plain rejection into an unevaluable gate — that would flip the client from "fetch a
    fresh token" to "retry unchanged" on a token Cloudflare has already refused."""
    assert await _verifier(_answering({"success": False})).verify(_TOKEN) is False
    assert (
        await _verifier(_answering({"success": False, "error-codes": "oops"})).verify(_TOKEN)
        is False
    )


async def test_the_client_is_closed_on_shutdown_and_closing_twice_is_harmless() -> None:
    """The lifespan closes the verifier this app built; a second close must not be an error at
    teardown, and closing one that never made a request must not be either."""
    verifier = _verifier(_answering({"success": True}))
    await verifier.verify(_TOKEN)

    await verifier.aclose()
    await verifier.aclose()
