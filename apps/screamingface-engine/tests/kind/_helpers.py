"""Shared wire helpers for the kind suite — token minting, the WS attach protocol
(`ws/endpoint.py`, `ws/bridge.py`), and the url4 expression this suite calls the stub model
with. Not `conftest.py`: these are plain functions test modules import, not fixtures.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import websockets

# A one-model-call expression: `('hi')` is the context, `!'answer'` the intent — the exact
# grammar `scripts/bench/sync_latency.py` and `tests/unit/test_run_path_fixes.py` use. It
# resolves through the world's `default_route` (url4-kind.toml: `/anthropic/claude-haiku-4-5`),
# which the stub answers.
EXPRESSION = "('hi')!'answer'"

# The two mounts url4-kind.toml/values-kind.yaml declare (test-plan §5 K3): a model endpoint
# (already declared by `BUILTIN_MODEL_WORLD`, no url4.toml entry needed) and the one `[data]`
# route this environment adds.
MODEL_MOUNT = "/anthropic/claude-haiku-4-5"
DATA_MOUNT = "/corpus/papers"

# The caller identity every mount/run call forwards (`X-User-Email`, the header Envoy would
# inject in a real deployment — nothing here verifies it, so any well-formed address works).
IDENTITY = {"X-User-Email": "kind-tests@example.com"}

_HEARTBEAT = "ai.url4.heartbeat"
_TERMINATED = "ai.url4.terminated"


async def mint_token(client: httpx.AsyncClient) -> str:
    response = await client.post("/token")
    response.raise_for_status()
    return str(response.json()["token"])


def ws_uri(base_url: str, ticket: str) -> str:
    return (
        base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        + f"/ws?ticket={ticket}"
    )


async def attach(ws: websockets.ClientConnection, *, from_sequence: int | None = None) -> None:
    """Send the `ai.url4.attach` frame the WS bridge expects before a run's frames replay
    (`tests/integration/test_local_spine.py`'s attach envelope, byte for byte)."""
    data: dict[str, object] = {} if from_sequence is None else {"from_sequence": from_sequence}
    await ws.send(
        json.dumps(
            {
                "specversion": "1.0",
                "id": "attach-1",
                "source": "/test",
                "type": "ai.url4.attach",
                "data": data,
            }
        )
    )


async def read_until_terminal(
    ws: websockets.ClientConnection, *, timeout: float = 30.0, total: float = 180.0
) -> list[dict]:
    """Every non-heartbeat frame up to and including `ai.url4.terminated`.

    `timeout` bounds one receive; `total` bounds the whole read — heartbeats keep a receive
    alive, so without it a run that never starts hangs the case forever (kind K6 finding).
    """
    frames: list[dict] = []
    deadline = asyncio.get_running_loop().time() + total
    while True:
        left = deadline - asyncio.get_running_loop().time()
        if left <= 0:
            raise TimeoutError(f"no terminal frame within {total}s; got {frames!r}")
        raw = await asyncio.wait_for(ws.recv(), timeout=min(timeout, left))
        frame = json.loads(raw)
        if frame.get("type") == _HEARTBEAT:
            continue
        frames.append(frame)
        if frame.get("type") == _TERMINATED:
            return frames


def gauge_value(metrics_text: str, name: str) -> float | None:
    """One no-label Prometheus gauge's current value from a `/metrics` scrape, or `None` if it
    was never rendered (e.g. before the App's first store-usage refresh)."""
    prefix = f"{name} "
    for line in metrics_text.splitlines():
        if line.startswith(prefix):
            return float(line[len(prefix) :])
    return None


def sequence_numbers(frames: list[dict]) -> list[int]:
    """The `sequence` CloudEvents extension (`url4.streaming.codec`) of every frame that
    carries one, in the order received."""
    return [int(frame["sequence"]) for frame in frames if "sequence" in frame]


def assert_gapfree(frames: list[dict]) -> None:
    sequences = sequence_numbers(frames)
    assert sequences, f"no sequenced frames at all: {frames!r}"
    assert sequences == list(range(1, len(sequences) + 1)), (
        f"gap or reorder in the frame sequence: {sequences!r}"
    )


async def run_async_over_ws(
    client: httpx.AsyncClient,
    ws: websockets.ClientConnection,
    token: str,
    *,
    identity: dict[str, str] = IDENTITY,
) -> tuple[httpx.Response, list[dict]]:
    """Attach, start an async run for `token`'s topic, and read its frames to the terminal one.

    Returns the `202` response from starting the run and the frames read off the WebSocket —
    the K1 shape (uniform executor test-plan §5).
    """
    await attach(ws)
    response = await client.get(
        "/",
        params={"q": EXPRESSION},
        headers={"URL4-Capability": token, "Prefer": "respond-async", **identity},
    )
    assert response.status_code == 202, (response.status_code, response.text)
    frames = await read_until_terminal(ws)
    return response, frames
