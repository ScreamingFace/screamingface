"""#1603 review round 4 (HupBaHa, 2026-11-04): a compressed S3 body cannot bypass the read caps.

FEATURE: run blob store (OME-1540), epic OME-1529.
STORY: as an operator, a store or proxy answering an object read with a small compressed body
that inflates to many megabytes cannot exhaust the App's or the Runner's memory.

WHY: HTTPX decodes `Content-Encoding` BEFORE it chunks `iter_bytes()` / `aiter_bytes()`, so a
19 KB gzip body expanding to 20 MB peaked near 50 MB with a 100-byte cap (review probe).

INVARIANT: object stores return the stored bytes and we never ask for compression. A response
carrying any `Content-Encoding` other than identity is refused as `S3StorageError` WITHOUT being
decoded — on success reads, on error diagnostics, and on the async artifact stream.
"""

from __future__ import annotations

import asyncio
import gzip
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest

from screamingface_engine.artifacts.blobs import BlobScope, S3BlobObjects
from screamingface_engine.artifacts.ports import RemoteStream
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config, S3StorageError
from screamingface_engine.artifacts.sigv4 import Credentials

RUN = "e" * 64
KEY = f"{BlobScope.for_caller('alice@example.org', RUN).key_prefix}/{'d' * 64}"
ARTIFACT_ID = "b" * 64
INFLATED = 20_000_000
# WHY 1 MB: the bomb inflates to 20 MB; reading the raw compressed bytes costs ~20 KB. Anything
# near a megabyte above baseline means a decoder ran.
PEAK_BOUND = 1_000_000
WIRE_CHUNK = 4096

_BOMB_PLAIN = b"\0" * INFLATED
BOMBS: dict[str, bytes] = {
    "gzip": gzip.compress(_BOMB_PLAIN),
    "deflate": zlib.compress(_BOMB_PLAIN),
}
del _BOMB_PLAIN


def _sync_chunks(body: bytes) -> Iterator[bytes]:
    for at in range(0, len(body), WIRE_CHUNK):
        yield body[at : at + WIRE_CHUNK]


async def _async_chunks(body: bytes) -> AsyncIterator[bytes]:
    for chunk in _sync_chunks(body):
        yield chunk


def _config() -> S3Config:
    return S3Config(
        endpoint_url="http://blobs.garage.svc:3900",
        bucket="blobs",
        credentials=Credentials(access_key="GKblobs", secret_key="blobs-secret", region="garage"),
    )


def _sync_store(status: int, encoding: str, body: bytes) -> S3ArtifactStore:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, headers={"content-encoding": encoding}, content=_sync_chunks(body)
        )

    return S3ArtifactStore(
        _config(), client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle))
    )


def _async_store(status: int, encoding: str, body: bytes) -> S3ArtifactStore:
    def handle_head(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": str(INFLATED)})

    async def handle_get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, headers={"content-encoding": encoding}, content=_async_chunks(body)
        )

    return S3ArtifactStore(
        _config(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle_head)),
        async_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle_get)),
    )


def _peak_above_baseline(action: Callable[[], object]) -> tuple[int, BaseException | None]:
    """The tracemalloc peak `action` reaches above the traced baseline, and what it raised."""
    tracemalloc.start()
    try:
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        raised: BaseException | None = None
        try:
            action()
        except Exception as exc:
            raised = exc
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak - baseline, raised


def _drain(store: S3ArtifactStore) -> None:
    found = store.content(ARTIFACT_ID)
    assert isinstance(found, RemoteStream)

    async def drain() -> None:
        async for _chunk in found.stream:
            pass

    asyncio.run(drain())


@pytest.mark.parametrize("encoding", sorted(BOMBS))
def test_a_compressed_bomb_on_a_capped_success_read_is_refused_undecoded(encoding: str) -> None:
    store = _sync_store(200, encoding, BOMBS[encoding])

    peak, raised = _peak_above_baseline(lambda: store.get_object_at_most(KEY, 100))

    assert isinstance(raised, S3StorageError)
    assert encoding in str(raised)
    assert peak < PEAK_BOUND


@pytest.mark.parametrize("encoding", sorted(BOMBS))
def test_a_compressed_bomb_on_a_capped_error_read_is_not_decoded(encoding: str) -> None:
    store = _sync_store(500, encoding, BOMBS[encoding])

    peak, raised = _peak_above_baseline(lambda: store.get_object_at_most(KEY, 100))

    assert isinstance(raised, S3StorageError)
    assert "500" in str(raised)
    assert encoding in str(raised)
    assert peak < PEAK_BOUND


@pytest.mark.parametrize("encoding", sorted(BOMBS))
def test_a_compressed_bomb_on_a_signed_request_error_is_not_decoded(encoding: str) -> None:
    """`_request` (PUT/HEAD/DELETE) shares the synchronous error-diagnostic path."""
    store = _sync_store(500, encoding, BOMBS[encoding])

    peak, raised = _peak_above_baseline(lambda: store.put_object(KEY, b"data"))

    assert isinstance(raised, S3StorageError)
    assert "500" in str(raised)
    assert peak < PEAK_BOUND


@pytest.mark.parametrize("encoding", sorted(BOMBS))
def test_a_compressed_bomb_through_the_blob_backend_is_refused_undecoded(encoding: str) -> None:
    objects = S3BlobObjects(_sync_store(200, encoding, BOMBS[encoding]))

    peak, raised = _peak_above_baseline(lambda: objects.get_at_most(f"{KEY}.json", 100))

    assert isinstance(raised, S3StorageError)
    assert peak < PEAK_BOUND


@pytest.mark.parametrize("encoding", sorted(BOMBS))
def test_a_compressed_bomb_on_the_artifact_stream_success_is_refused_undecoded(
    encoding: str,
) -> None:
    store = _async_store(200, encoding, BOMBS[encoding])

    peak, raised = _peak_above_baseline(lambda: _drain(store))

    assert isinstance(raised, S3StorageError)
    assert encoding in str(raised)
    assert peak < PEAK_BOUND


@pytest.mark.parametrize("encoding", sorted(BOMBS))
def test_a_compressed_bomb_on_the_artifact_stream_error_is_not_decoded(encoding: str) -> None:
    store = _async_store(500, encoding, BOMBS[encoding])

    peak, raised = _peak_above_baseline(lambda: _drain(store))

    assert isinstance(raised, S3StorageError)
    assert "500" in str(raised)
    assert peak < PEAK_BOUND


def test_an_explicit_identity_encoding_still_reads_the_stored_bytes() -> None:
    store = _sync_store(200, "identity", b"stored bytes")

    assert store.get_object_at_most(KEY, 100) == b"stored bytes"


def test_an_explicit_identity_encoding_still_streams_the_stored_bytes() -> None:
    store = _async_store(200, "identity", b"stored bytes")
    found = store.content(ARTIFACT_ID)
    assert isinstance(found, RemoteStream)

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in found.stream])

    assert asyncio.run(collect()) == b"stored bytes"


def test_an_identity_error_body_still_names_the_cause() -> None:
    store = _sync_store(503, "identity", b"<Error><Code>SlowDown</Code></Error>")

    with pytest.raises(S3StorageError) as caught:
        store.get_object_at_most(KEY, 100)
    assert "SlowDown" in str(caught.value)


def test_a_streamed_unencoded_body_is_read_raw_and_whole() -> None:
    """The on-the-wire shape: a streamed body (not pre-read) goes through `iter_raw`."""
    stored = bytes(range(256)) * 64
    store = _sync_store(200, "identity", stored)

    assert store.get_object_at_most(KEY, len(stored)) == stored


def test_a_streamed_unencoded_artifact_is_streamed_raw_and_whole() -> None:
    stored = bytes(range(256)) * 512
    store = _async_store(200, "identity", stored)
    found = store.content(ARTIFACT_ID)
    assert isinstance(found, RemoteStream)

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in found.stream])

    assert asyncio.run(collect()) == stored
