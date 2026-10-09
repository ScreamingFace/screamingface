"""The outbound adapter keeps a remote url4 node's error code (row 26, E10).

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a code pointer on a remote node that fails with intent_error reaches
# my caller with its code and its permanence, not as a generic retryable failure.
#
# INVARIANT: only a url4:// target reads the {"error": {"code"}} body. Any other scheme keeps the
# transient resolution_failed error, whatever its body says.
"""

from __future__ import annotations

import httpx
import pytest

from url4.core.errors import ResolutionError
from url4.io.http import HttpIOLayer
from url4.peer.server import Request, Url4Node
from url4.wire.rds import encode_rds_document, encode_rds_target

_DOC = encode_rds_document({"member_1": "A 4", "extract_pattern": "ANSWER: \\d+"})


def _error_body(code: str) -> dict:
    return {"error": {"code": code, "message": "remote said no"}}


def _mock_io(status: int, *, json_body: dict | None = None, text: str = "") -> HttpIOLayer:
    def handler(request: httpx.Request) -> httpx.Response:
        if json_body is not None:
            return httpx.Response(status, json=json_body)
        return httpx.Response(status, text=text)

    return HttpIOLayer(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_a_remote_intent_error_keeps_its_code_and_is_permanent() -> None:
    """Row 26: a remote code pointer that raises ValueError reaches the caller as intent_error."""

    async def score(request: Request) -> str:
        raise ValueError("bad input")

    node = Url4Node("t")
    node.endpoint("/score/v1")(score)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=node.asgi()), base_url="http://t")
    io = HttpIOLayer(client=client)
    target = "url4://t" + encode_rds_target("/score/v1", "", _DOC)

    with pytest.raises(ResolutionError) as exc:
        await io.fetch(target, relative=False)
    assert exc.value.code == "intent_error"
    assert exc.value.permanent is True


@pytest.mark.asyncio
async def test_a_remote_5xx_with_a_known_code_keeps_the_code_and_is_transient() -> None:
    io = _mock_io(503, json_body=_error_body("quorum_not_met"))

    with pytest.raises(ResolutionError) as exc:
        await io.fetch("url4://t/score/v1", relative=False)
    assert exc.value.code == "quorum_not_met"
    assert exc.value.permanent is False


@pytest.mark.asyncio
async def test_a_remote_quorum_not_met_is_permanent_when_the_server_sends_500() -> None:
    """F6/F5: the server answers a permanent unmapped code with 500 (peer/_http status_for_code)."""
    io = _mock_io(500, json_body=_error_body("quorum_not_met"))

    with pytest.raises(ResolutionError) as exc:
        await io.fetch("url4://t/score/v1", relative=False)
    assert exc.value.code == "quorum_not_met"
    assert exc.value.permanent is True


@pytest.mark.asyncio
async def test_a_remote_code_outside_the_code_pointer_set_is_not_adopted() -> None:
    """SF6: `timeout` is reserved for the engine's boundary, so a remote body cannot inject it."""
    io = _mock_io(404, json_body=_error_body("timeout"))

    with pytest.raises(ResolutionError) as exc:
        await io.fetch("url4://t/score/v1", relative=False)
    assert exc.value.code == "resolution_failed"
    assert exc.value.permanent is False


@pytest.mark.asyncio
async def test_a_url4_target_with_a_non_json_error_body_is_transient_resolution_failed() -> None:
    io = _mock_io(422, text="<html>not json</html>")

    with pytest.raises(ResolutionError) as exc:
        await io.fetch("url4://t/score/v1", relative=False)
    assert exc.value.code == "resolution_failed"
    assert exc.value.permanent is False


@pytest.mark.asyncio
async def test_a_url4_target_with_an_unknown_error_code_is_transient_resolution_failed() -> None:
    io = _mock_io(422, json_body=_error_body("x.custom"))

    with pytest.raises(ResolutionError) as exc:
        await io.fetch("url4://t/score/v1", relative=False)
    assert exc.value.code == "resolution_failed"
    assert exc.value.permanent is False


@pytest.mark.asyncio
async def test_an_https_target_with_a_known_error_body_is_still_transient() -> None:
    """Non-url4 targets keep today's behavior, even when the body has the RDS error shape."""
    io = _mock_io(422, json_body=_error_body("intent_error"))

    with pytest.raises(ResolutionError) as exc:
        await io.fetch("https://t/score/v1", relative=False)
    assert exc.value.code == "resolution_failed"
    assert exc.value.permanent is False
