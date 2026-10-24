"""OME-1537 review (finding 2): the sync ``/api/show`` reader has a TOTAL deadline.

httpx's read timeout restarts on every chunk, so a host that dribbles one byte at a
time never trips it. ``_read_capped`` stops at a whole-request deadline as well as at
the byte cap, and the probe reports unknown (``None``) — never a hang.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx
import pytest

from aigateway.plugins.ollama_provider.discovery import (
    DEFAULT_OLLAMA_HOST,
    clear_ollama_discovery_cache,
    discover_ollama_input_modalities,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_ollama_discovery_cache()
    yield
    clear_ollama_discovery_cache()


class _Drip(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.pulled = 0

    def __iter__(self) -> Iterator[bytes]:
        yield b'{"capabilities": ["vision"], "license": "'
        while True:
            self.pulled += 1
            time.sleep(0.01)
            yield b" "


def test_a_slow_drip_show_body_is_unknown_within_the_deadline() -> None:
    stream = _Drip()

    def factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, stream=stream)),
            timeout=timeout,
        )

    started = time.monotonic()
    got = discover_ollama_input_modalities(
        DEFAULT_OLLAMA_HOST, "drip:1b", http_client_factory=factory, timeout_seconds=0.2
    )
    elapsed = time.monotonic() - started

    assert got is None
    assert elapsed < 2.0
    assert stream.pulled > 0
