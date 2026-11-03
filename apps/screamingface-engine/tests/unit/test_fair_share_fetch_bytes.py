"""Local mode's fair-share wrapper forwards the binary-safe ``fetch_bytes`` port (e2e F2).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1545``; e2e finding F2, 2026-11-02).
STORY: as a local-mode user I run ``/model(src=https://…/chart.png;accept=image/png)!'…'`` and
the picture reaches the model, instead of every https attachment failing ``unsupported_mode``
("needs a binary-safe io layer (fetch_bytes)") with 0 model calls because ``serve --local``
wraps every run's io in ``FairShareIOLayer``.

INVARIANT: ``fetch_bytes`` is forwarded only when the inner layer has it, and is admitted
through the same fair-share gate as every other fetch (mirrors url4's ``BoundedIOLayer``).
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
import url4.io.http as http_mod
from screamingface_engine import job_env
from screamingface_engine.runner.fair_share import FairShareGate, FairShareIOLayer
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig

MODEL = "anthropic/claude-haiku-4-5"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-fair-share"
IMG_URL = "https://img.example/chart.png"


class _BytesInner:
    """An inner layer with ``fetch_bytes`` that parks until the test lets it proceed."""

    def __init__(self) -> None:
        self.proceed = asyncio.Event()
        self.requests: list[Any] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        return target

    async def fetch_bytes(self, request: Any) -> bytes:
        self.requests.append(request)
        await self.proceed.wait()
        return PNG


class _TextOnlyInner:
    async def fetch(self, target: str, *, relative: bool) -> str:
        return target


async def _settle(rounds: int = 3) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_fetch_bytes_is_forwarded_and_admitted_through_the_share() -> None:
    gate = FairShareGate(1)
    inner = _BytesInner()
    layer = FairShareIOLayer(inner, gate, "run-a")  # type: ignore[arg-type]
    assert hasattr(layer, "fetch_bytes")

    first = asyncio.get_running_loop().create_task(layer.fetch_bytes("req-1"))
    second = asyncio.get_running_loop().create_task(layer.fetch_bytes("req-2"))
    await _settle()
    snapshot = gate.snapshot()
    assert snapshot.in_flight == 1  # capacity 1: the second bytes fetch waits for the permit
    assert inner.requests == ["req-1"]

    inner.proceed.set()
    assert await asyncio.gather(first, second) == [PNG, PNG]
    assert inner.requests == ["req-1", "req-2"]
    assert gate.snapshot().runs == ()  # every permit returned


@pytest.mark.asyncio
async def test_a_failed_bytes_fetch_releases_its_permit() -> None:
    class _Failing(_BytesInner):
        async def fetch_bytes(self, request: Any) -> bytes:
            raise RuntimeError("inner exploded")

    gate = FairShareGate(1)
    layer = FairShareIOLayer(_Failing(), gate, "run-a")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="inner exploded"):
        await layer.fetch_bytes("req")
    assert gate.snapshot().in_flight == 0


def test_fetch_bytes_is_not_exposed_without_an_inner_port() -> None:
    layer = FairShareIOLayer(_TextOnlyInner(), FairShareGate(1), "run-a")  # type: ignore[arg-type]
    assert not hasattr(layer, "fetch_bytes")


# --- end to end: a local (gate-bound) run with an https attachment reaches the model ----------


def _declared() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://gateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL),),
        )
    )


def _completion(_: httpx.Request) -> dict[str, Any]:
    return {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """The fake public web behind url4's guarded transport: answers the PNG."""
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    async def resolve(host: str, port: int) -> Sequence[str]:
        return ["93.184.215.14"]

    monkeypatch.setattr(guarded_mod, "_inner_transport", lambda: httpx.MockTransport(record))
    monkeypatch.setattr(http_mod, "system_resolver", resolve)
    return sent


@pytest.mark.asyncio
async def test_a_gate_bound_run_with_an_https_attachment_reaches_the_model(
    web: list[httpx.Request],
) -> None:
    posts: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        posts.append(request)
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(
                200, json={"data": [{"id": MODEL, "input_modalities": ["text", "image"]}]}
            )
        return httpx.Response(200, json=_completion(request))

    gate = FairShareGate(4)
    transport = httpx.MockTransport(gateway)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        executor = build_executor(
            {job_env.TOPIC: "run-a"}, _declared(), client=client, io_gate=gate
        )
        frames = [
            frame
            async for frame in executor.execute(
                f"/{MODEL}(src={IMG_URL};accept=image/png)!'What is the chart title code?'"
            )
        ]

    assert frames  # the run streamed to completion
    # fetched once, as bytes, through the guard (which pins the vetted address)
    assert [request.url.path for request in web] == ["/chart.png"]
    chat = [p for p in posts if p.url.path.endswith("/chat/completions")]
    assert len(chat) == 1
    content = json.loads(chat[0].content)["messages"][-1]["content"]
    image = f"data:image/png;base64,{base64.b64encode(PNG).decode()}"
    assert content[0] == {"type": "image_url", "image_url": {"url": image}}
    assert gate.snapshot().runs == ()
