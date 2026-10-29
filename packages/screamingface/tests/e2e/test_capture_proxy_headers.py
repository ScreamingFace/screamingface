"""The bless tool's capture proxy forwards only the headers the gateway still reads (OME-1138 L8).

Default lane: no docker and no gateway, just the proxy in front of a loopback recorder. Stage D
retired `X-Profile` (every nonblank value is a 400 `x_profile_unsupported`), so the proxy that
sits between the Engine and the gateway while blessing must not carry it.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fixtures.slice_snapshot import _CaptureProxy


class _Recorder:
    """A loopback stand-in for the gateway that keeps the headers of every request it gets."""

    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []
        seen = self.headers

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:  # quiet
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                self.rfile.read(length)
                seen.append({key.lower(): value for key, value in self.headers.items()})
                payload = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def proxied() -> Iterator[tuple[_Recorder, _CaptureProxy]]:
    recorder = _Recorder()
    proxy = _CaptureProxy(recorder.url)
    try:
        yield recorder, proxy
    finally:
        proxy.shutdown()
        recorder.shutdown()


def test_capture_proxy_does_not_forward_the_retired_x_profile_header(
    proxied: tuple[_Recorder, _CaptureProxy],
) -> None:
    recorder, proxy = proxied

    response = httpx.post(
        f"{proxy.url}/v1/chat/completions",
        content=b'{"model": "openrouter/m"}',
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Profile": "default",
        },
        timeout=10.0,
    )

    assert response.status_code == 200
    assert len(recorder.headers) == 1
    forwarded = recorder.headers[0]
    # INVARIANT: the proxy forwards Content-Type and Accept, so the body still reaches the gateway
    # as JSON; the retired selector is not among them.
    assert forwarded["content-type"] == "application/json"
    assert forwarded["accept"] == "application/json"
    assert "x-profile" not in forwarded
    assert proxy.records == [
        {"request_body": {"model": "openrouter/m"}, "status": 200, "cache_header": None}
    ]
