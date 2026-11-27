"""Loopback-only reference server."""

import json
import re
from collections.abc import Callable, Iterable, Mapping

import uvicorn
from uvicorn._types import ASGI3Application, ASGIReceiveCallable, ASGISendCallable, Scope

from ._json import decode_object
from .artifacts import verify_snapshot
from .classifier import Head, Tokenizer, classify

MAX_BODY_BYTES = 65_536
_CONTENT_TYPE = re.compile(rb'application/json(?:[ \t]*;[ \t]*charset=(?:utf-8|"utf-8"))?')

type Loader = Callable[[Mapping[str, bytes]], tuple[Tokenizer, Head]]


def _accepts(headers: Iterable[tuple[bytes, bytes]]) -> bool:
    media: list[bytes] = []
    coding: list[bytes] = []
    for name, value in headers:
        match name.lower():
            case b"content-type":
                media.append(value.strip(b" \t").lower())
            case b"content-encoding":
                coding.append(value.strip(b" \t").lower())
            case _:
                pass
    return (
        len(media) == 1
        and bool(_CONTENT_TYPE.fullmatch(media[0]))
        and coding in ([], [b"identity"])
    )


async def _reply(send: ASGISendCallable, status: int, document: object) -> None:
    body = json.dumps(document, separators=(",", ":"), allow_nan=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _refuse(send: ASGISendCallable, status: int, code: str) -> None:
    await _reply(send, status, {"error": {"code": code}})


async def _body(receive: ASGIReceiveCallable, send: ASGISendCallable) -> bytearray | None:
    body = bytearray()
    while True:
        event = await receive()
        if event["type"] != "http.request":
            return None
        chunk = event.get("body", b"")
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            await _refuse(send, 413, "request_too_large")
            return None
        body.extend(chunk)
        if not event.get("more_body", False):
            return body


def _input(body: bytearray) -> str:
    document = decode_object(body)
    if document.keys() != {"inputs"} or not isinstance(text := document["inputs"], str):
        raise ValueError("invalid input shape")
    # WHY strict encoding check: JSON escapes can otherwise introduce a lone surrogate.
    text.encode("utf-8")
    return text


def create_application(tokenizer: Tokenizer, head: Head) -> ASGI3Application:
    async def app(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        if scope["type"] != "http":
            raise RuntimeError("expected an HTTP scope")
        if scope["path"] != "/classify" or scope["method"] != "POST":
            await _refuse(send, 404, "not_found")
            return
        if not _accepts(scope["headers"]):
            await _refuse(send, 415, "unsupported_media_type")
            return
        body = await _body(receive, send)
        if body is None:
            return
        try:
            text = _input(body)
        except (ValueError, RecursionError):
            await _refuse(send, 400, "invalid_request")
            return
        try:
            scores = classify(text, tokenizer, head)
        except Exception:
            # INVARIANT: backend exceptions cross this boundary as one fixed code, not log text.
            await _refuse(send, 500, "classifier_failed")
            return
        if scores is None:
            await _refuse(send, 422, "input_token_limit_exceeded")
        else:
            await _reply(send, 200, scores)

    return app


def prepare_application(environment: Mapping[str, str], loader: Loader) -> ASGI3Application:
    snapshot = verify_snapshot(environment)
    tokenizer, head = loader(snapshot)
    return create_application(tokenizer, head)


def loopback_server(environment: Mapping[str, str], loader: Loader, *, port: int) -> uvicorn.Server:
    """Compose only after verification; the caller runs the returned local server."""
    app = prepare_application(environment, loader)
    return uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            http="h11",
            ws="none",
            loop="asyncio",
            interface="asgi3",
            lifespan="off",
            proxy_headers=False,
            access_log=False,
            log_config=None,
        )
    )
