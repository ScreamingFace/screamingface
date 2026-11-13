"""A run holding url4's largest legal attachments still fits in one gateway request (OME-1545).

FEATURE: image and PDF inputs (epic ``OME-1529``; PR #1588 review blocker 2, owner decision
2026-11-13). Every model call of a url4 run carries the run's files as base64 ``data:`` URIs, and
the gateway refuses a body over its cap with a permanent 413 ``request_too_large``. Before, url4
admitted 8,000,000 decoded bytes, which encode to 10,666,668 — every such run failed every call.

INVARIANT: ``4 * ceil(cap / 3)`` for the files, plus the base64 padding of 20 entries, plus a
per-part overhead for each, plus the request envelope reserve, is at most the gateway's default
body cap. The gateway's cap is read from its source with ``ast``
(``apps/aigateway/src/aigateway/config.py`` ``max_request_bytes``; aigateway is a separate uv
project and is not installed here). The gateway suite holds the twin
(``apps/aigateway/tests/unit/test_url4_attachment_cap_request.py``), which posts the bound's
request through the gateway's real body cap.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import math
from pathlib import Path

import httpx
import pytest
from test_aigateway_connector import _MODEL
from test_picture_case_limits_fit_the_gateway import _gateway_body_cap

from screamingface_engine.world.attachment_parts import attachment_parts
from screamingface_engine.world.config import ModelSpec, routes_for
from screamingface_engine.world.connector import AigatewayConfig, _ModelEndpoint
from url4 import Attachment
from url4.peer.server import Request

_URL4_CAPS = Path(__file__).resolve().parents[4] / "packages/url4/src/url4/dag/_caps.py"


def _url4_cap(name: str) -> int:
    """An int constant of url4's private caps module, read from its source with ``ast``.

    WHY not an import: ``url4.dag._caps`` is private, and the engine's private-import ratchet
    (``test_url4_private_import_ratchet.py``) keeps such imports from growing.
    """
    for node in ast.walk(ast.parse(_URL4_CAPS.read_text())):
        if (
            isinstance(node, ast.Assign)
            and [getattr(target, "id", None) for target in node.targets] == [name]
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            return node.value.value
    raise AssertionError(f"{name} = <int> not found in {_URL4_CAPS}")


MAX_ATTACHMENT_BYTES = _url4_cap("MAX_ATTACHMENT_BYTES")
MAX_ATTACHMENTS = _url4_cap("MAX_ATTACHMENTS")

# WHY 256 KiB: the text a call carries besides its files — model, parameters, the JSON around the
# messages, the prompt, and a synthesizer's member answers; the same reserve as the picture-Case
# twin (``test_picture_case_limits_fit_the_gateway.py``).
_ENVELOPE_RESERVE = 256 * 1024
# WHY 1 KiB: one part's bytes besides its base64 — ``data:<media type>;base64,`` (a media type is
# at most 127 + 1 + 127 characters, RFC 6838 §4.2), the part's JSON keys, ``detail`` and a
# filename; pinned against the real part JSON below.
_PART_OVERHEAD = 1024


def _encoded_bound(decoded: int, parts: int) -> int:
    """The most base64 bytes ``parts`` files of ``decoded`` bytes in all can encode to.

    Each file of ``n`` bytes is ``4 * ceil(n / 3)``, at most ``4 * (n + 2) / 3``; summed, that is
    ``4 * decoded / 3`` plus ``8 / 3`` per file.
    """
    return math.floor(4 * decoded / 3 + 8 * parts / 3)


def test_the_largest_legal_run_plus_its_request_fits_under_the_gateways_body_cap() -> None:
    files = _encoded_bound(MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS)
    overhead = MAX_ATTACHMENTS * _PART_OVERHEAD + _ENVELOPE_RESERVE

    assert files + overhead <= _gateway_body_cap()


def test_the_encoded_bound_covers_one_file_and_twenty_within_a_few_bytes() -> None:
    one = 4 * math.ceil(6_000_000 / 3)
    assert one <= _encoded_bound(6_000_000, 1) <= one + 2
    worst = [1] * (MAX_ATTACHMENTS - 1) + [6_000_000 - (MAX_ATTACHMENTS - 1)]
    twenty = sum(len(base64.b64encode(b"x" * n)) for n in worst)
    assert twenty <= _encoded_bound(6_000_000, MAX_ATTACHMENTS) <= twenty + 3 * MAX_ATTACHMENTS


@pytest.mark.asyncio
async def test_one_parts_json_besides_its_base64_is_within_the_part_overhead() -> None:
    body = b"%PDF-1.4"
    big = Attachment(
        digest="sha256:" + hashlib.sha256(body).hexdigest(),
        media_type="application/" + "x" * 115 + "+" + "y" * 127,
        body=body,
        filename="f" * 255 + ".pdf",
        detail="high",
    )
    (part,) = await attachment_parts([big])
    payload = len(base64.b64encode(body))
    assert len(json.dumps(part, separators=(",", ":")).encode()) - payload <= _PART_OVERHEAD


class _GatewayBodyCap(httpx.AsyncBaseTransport):
    """The gateway's 413 ``request_too_large`` rule on the bytes delivered, nothing else."""

    def __init__(self) -> None:
        self.delivered: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.AsyncByteStream)
        size = 0
        async for chunk in request.stream:
            size += len(chunk)
        self.delivered.append(size)
        if size > _gateway_body_cap():
            return httpx.Response(413, json={"detail": {"code": "request_too_large"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "42"}}], "usage": {"total_tokens": 1}},
        )


@pytest.mark.asyncio
async def test_a_call_carrying_the_cap_in_one_picture_is_delivered_under_the_gateway_cap() -> None:
    # STORY: the reviewer's case at the new boundary — the largest legal picture, a long prompt.
    body = bytes(range(256)) * (MAX_ATTACHMENT_BYTES // 256) + b"\0" * (MAX_ATTACHMENT_BYTES % 256)
    picture = Attachment(
        digest="sha256:" + hashlib.sha256(body).hexdigest(), media_type="image/png", body=body
    )
    gateway = _GatewayBodyCap()
    models = (ModelSpec(id=_MODEL, web_search=False),)
    async with httpx.AsyncClient(transport=gateway, base_url="http://aigateway.test") as client:
        handler = _ModelEndpoint(
            http_client=client,
            cfg=AigatewayConfig(models=models, default_model=_MODEL),
            routes=routes_for(models),
            tavily_http=None,
            tavily_api_key=None,
        )
        prompt = "p" * (_ENVELOPE_RESERVE - 4096)
        request = Request(
            path=f"/{_MODEL}", context=prompt, intent="Answer.", params={}, attachments=(picture,)
        )
        assert await handler(request) == "42"

    (delivered,) = gateway.delivered
    assert delivered <= _gateway_body_cap()
