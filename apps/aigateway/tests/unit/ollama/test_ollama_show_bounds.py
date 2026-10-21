"""OME-1537 review (HupBaHa 2026-10-20, findings 1-2) — bounded ``/api/show`` probes.

``/api/show`` carries the modelfile, template, license and model metadata; a remote
host can make it arbitrarily large. The probe STREAMS the body under a byte cap and
stops reading at the cap, and a pathologically nested document is unknown, never a
crash. Concurrent cold lookups of the same (host, model) share ONE upstream call.

Any bound tripped -> ``None`` -> text-only (unknown never means vision).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import httpx
import pytest

from aigateway.plugins.ollama_provider import discovery as ollama_discovery
from aigateway.plugins.ollama_provider.discovery import (
    DEFAULT_OLLAMA_HOST,
    SHOW_MAX_BYTES,
    clear_ollama_discovery_cache,
    discover_ollama_input_modalities,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_ollama_discovery_cache()
    yield
    clear_ollama_discovery_cache()


def _factory(handler):
    def factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    return factory


class _Stream(httpx.SyncByteStream):
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self.pulled = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk


def test_an_oversized_show_body_is_unknown_and_reading_stops_at_the_cap() -> None:
    chunk = b" " * 65_536
    total_chunks = (SHOW_MAX_BYTES // len(chunk)) * 4
    stream = _Stream(iter([b'{"capabilities": ["vision"], "license": "', *[chunk] * total_chunks]))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    got = discover_ollama_input_modalities(
        DEFAULT_OLLAMA_HOST, "big:1b", http_client_factory=_factory(handler)
    )
    assert got is None
    assert stream.pulled < total_chunks


def test_a_body_just_under_the_cap_is_still_read() -> None:
    body = b'{"capabilities": ["vision"], "license": "' + b"x" * 1_000 + b'"}'
    assert len(body) < SHOW_MAX_BYTES

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    got = discover_ollama_input_modalities(
        DEFAULT_OLLAMA_HOST, "ok:1b", http_client_factory=_factory(handler)
    )
    assert got == ("text", "image")


def test_a_pathologically_nested_show_body_is_unknown_not_a_crash() -> None:
    depth = 100_000
    body = b'{"capabilities": ["vision"], "x": ' + b"[" * depth + b"]" * depth + b"}"
    assert len(body) < SHOW_MAX_BYTES

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    got = discover_ollama_input_modalities(
        DEFAULT_OLLAMA_HOST, "deep:1b", http_client_factory=_factory(handler)
    )
    assert got is None


def test_concurrent_cold_lookups_of_one_model_share_one_upstream_call() -> None:
    release = threading.Event()
    asked: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        asked.append("show")
        release.wait(timeout=5)
        return httpx.Response(200, json={"capabilities": ["vision"]})

    factory = _factory(handler)
    results: list[object] = []

    def lookup() -> None:
        results.append(
            discover_ollama_input_modalities(
                DEFAULT_OLLAMA_HOST, "shared:1b", http_client_factory=factory
            )
        )

    first = threading.Thread(target=lookup)
    first.start()
    deadline = time.monotonic() + 5
    while not asked and time.monotonic() < deadline:
        time.sleep(0.005)
    second = threading.Thread(target=lookup)
    second.start()
    # Give the second lookup time to reach the cache; it must WAIT, not dial.
    time.sleep(0.1)
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert asked == ["show"]
    assert results == [("text", "image"), ("text", "image")]


def test_a_failed_leader_releases_waiters_to_retry_later() -> None:
    # The in-flight marker must be cleared even when the probe raises unexpectedly.
    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        discover_ollama_input_modalities(
            DEFAULT_OLLAMA_HOST, "boom:1b", http_client_factory=_factory(handler)
        )
    assert (DEFAULT_OLLAMA_HOST, "boom:1b") not in ollama_discovery._MODALITIES_IN_FLIGHT
