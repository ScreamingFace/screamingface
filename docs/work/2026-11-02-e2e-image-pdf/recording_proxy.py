"""Loopback proxy between the engine and aigateway that records each chat request's content parts.

Every request is forwarded byte for byte. The log never holds base64: an attachment part is
recorded as its media type, base64 length and the sha256 of its decoded bytes.

Usage: python recording_proxy.py <listen_port> <upstream_base_url> <log.jsonl>
"""

import base64
import hashlib
import json
import sys
import time

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

PORT, UPSTREAM, LOG = int(sys.argv[1]), sys.argv[2].rstrip("/"), sys.argv[3]
client = httpx.AsyncClient(timeout=1900)


def _digest_data_uri(uri: str) -> dict:
    head, _, b64 = uri.partition(",")
    raw = base64.b64decode(b64)
    return {
        "media": head,
        "b64_len": len(b64),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _part(p: dict) -> dict:
    t = p.get("type")
    if t == "text":
        return {"type": t, "text": p["text"][:300]}
    if t == "image_url":
        url = (
            p["image_url"]["url"]
            if isinstance(p.get("image_url"), dict)
            else p.get("image_url")
        )
        return {
            "type": t,
            **(_digest_data_uri(url) if url.startswith("data:") else {"url": url}),
        }
    if t == "file":
        f = dict(p.get("file") or {})
        data = f.pop("file_data", None)
        return {"type": t, **f, **(_digest_data_uri(data) if data else {})}
    return {"type": t}


def _summary(body: dict) -> dict:
    msgs = []
    for m in body.get("messages", []):
        c = m.get("content")
        parts = (
            [_part(p) for p in c]
            if isinstance(c, list)
            else [{"type": "text", "text": str(c)[:300]}]
        )
        msgs.append({"role": m.get("role"), "parts": parts})
    return {"model": body.get("model"), "messages": msgs}


async def proxy(request: Request) -> Response:
    raw = await request.body()
    entry = {"t": time.time(), "method": request.method, "path": request.url.path}
    if request.url.path.endswith("/chat/completions") and raw:
        try:
            entry["request"] = _summary(json.loads(raw))
        except Exception as exc:  # record, never block the call
            entry["request_error"] = repr(exc)
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    url = (
        UPSTREAM
        + request.url.path
        + (("?" + request.url.query) if request.url.query else "")
    )
    up = await client.request(request.method, url, content=raw, headers=headers)
    entry["status"] = up.status_code
    if request.url.path.endswith("/chat/completions"):
        try:
            rb = up.json()
            entry["usage"] = rb.get("usage")
            ch = (rb.get("choices") or [{}])[0].get("message", {})
            entry["answer"] = (ch.get("content") or "")[:1500]
            if up.status_code >= 400:
                entry["error"] = json.dumps(rb)[:1500]
        except Exception:
            entry["response_head"] = up.text[:500]
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    drop = ("content-length", "content-encoding", "transfer-encoding", "connection")
    return Response(
        up.content,
        status_code=up.status_code,
        headers={k: v for k, v in up.headers.items() if k.lower() not in drop},
    )


app = Starlette(
    routes=[Route("/{path:path}", proxy, methods=["GET", "POST", "PUT", "DELETE"])]
)
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
