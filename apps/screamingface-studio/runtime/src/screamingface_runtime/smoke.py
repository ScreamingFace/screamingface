"""Deterministic end-to-end check for the local Engine execution protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect

_SUBPROTOCOL = "cloudevents.json"
_EXPRESSION = "'screamingface-runtime-ok'"


def _websocket_url(engine_url: str, token: str) -> str:
    parsed = urlsplit(engine_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, "/ws", urlencode({"ticket": token}), ""))


async def smoke(engine_url: str) -> str:
    """Execute one credential-free URL4 expression through the production protocol."""

    async with httpx.AsyncClient(base_url=engine_url, timeout=30.0) as http:
        token_response = await http.post("/token")
        token_response.raise_for_status()
        token = str(token_response.json()["token"])
        headers = {"URL4-Capability": token}
        async with connect(
            _websocket_url(engine_url, token),
            subprotocols=[_SUBPROTOCOL],
            open_timeout=10,
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "specversion": "1.0",
                        "id": "desktop-runtime-smoke-attach",
                        "source": "/screamingface-runtime-smoke",
                        "type": "ai.url4.attach",
                        "data": {},
                    }
                )
            )
            response = await http.get("/", params={"q": _EXPRESSION}, headers=headers)
            response.raise_for_status()
            result = response.text

            terminal: dict[str, Any] | None = None
            while terminal is None:
                frame = json.loads(
                    await asyncio.wait_for(websocket.recv(), timeout=10.0)
                )
                if frame.get("type") == "ai.url4.terminated":
                    terminal = frame

    status = terminal.get("data", {}).get("status")
    if status != "succeeded":
        raise RuntimeError(f"URL4 smoke run terminated with status {status!r}")
    if result != "screamingface-runtime-ok":
        raise RuntimeError(f"URL4 smoke run returned an unexpected result: {result!r}")
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-url", default="http://127.0.0.1:9108")
    args = parser.parse_args(argv)
    result = asyncio.run(smoke(args.engine_url))
    print(f"SCREAMINGFACE_RUNTIME_SMOKE_OK {result}", flush=True)


if __name__ == "__main__":
    main()
