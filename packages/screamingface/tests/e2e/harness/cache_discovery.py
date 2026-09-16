"""Test-only discovery compatibility for the credential-free response-cache replay.

Live provider access is deliberately absent. Omit that optional assertion so the Client
uses its supported legacy/unknown path and reaches the real Gateway cache. Never claim
configured credentials; chat, cache misses, other metadata and errors remain untouched.
"""

import json
from collections.abc import Awaitable, Callable, MutableMapping
from importlib import import_module
from typing import Any

Message = MutableMapping[str, Any]
Send = Callable[[Message], Awaitable[None]]


class ReplayDiscovery:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Message, receive: Any, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/v1/model-parameters":
            await self.app(scope, receive, send)
            return
        start: Message | None = None
        chunks: list[bytes] = []

        async def discovery_send(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start" and message["status"] == 200:
                start = message
            elif start is not None and message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    document = json.loads(b"".join(chunks))
                    document["context"].pop("execution_access", None)
                    body = json.dumps(document).encode()
                    headers = [
                        (k, v) for k, v in start["headers"] if k.lower() != b"content-length"
                    ]
                    headers.append((b"content-length", str(len(body)).encode()))
                    await send({**start, "headers": headers})
                    await send({"type": "http.response.body", "body": body})
            else:
                await send(message)

        await self.app(scope, receive, discovery_send)


def create_app() -> Any:
    # WHY: imported in the Gateway subprocess's venv, never the Client's dependency tree.
    app = import_module("aigateway.main").app
    app.add_middleware(ReplayDiscovery)
    return app
