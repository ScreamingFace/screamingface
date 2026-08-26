"""The artifact writer/reader PORTS, and that the App can serve a non-filesystem reader.

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

WHY this file exists: until now one `ArtifactStore` class served both sides because they
shared a filesystem. On the hosted Engine they do not — the Runner Job pod and the App pod
each mount their own `emptyDir` — so the write side and the read side are two different
things and the type system should say so.

INVARIANT: `ArtifactContent` carries no HTTP concept. `screamingface_engine.artifacts` is a
SHARED LEAF of the layering gate (both halves import it), so a Starlette type reaching into
it would put the serving framework in a Runner Job's cold start. The route decides how to
render; the port only says what there is to render.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.artifacts import (
    ArtifactContent,
    ArtifactReader,
    ArtifactStore,
    ArtifactWriter,
    FilesystemArtifactStore,
    LocalFile,
    RemoteStream,
)
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol.signals import ResultArtifact

SECRET = "artifact-ports-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 8, 21, 9, 0, 0, tzinfo=UTC)


def _cap(topic: str) -> dict[str, str]:
    return {
        "URL4-Capability": JwtCodec(
            secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
        ).sign(topic, T0)
    }


# --- the ports are satisfied by the filesystem adapter -----------------------------------


def test_the_filesystem_adapter_satisfies_both_ports(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)

    assert isinstance(store, ArtifactWriter)
    assert isinstance(store, ArtifactReader)


def test_a_round_trip_through_port_typed_helpers_returns_the_written_bytes(
    tmp_path: Path,
) -> None:
    """Exercised through the PORTS, not the concrete class — pyright checks the shape here."""

    def deposit(writer: ArtifactWriter, payload: bytes) -> ResultArtifact:
        return writer.write_bytes(payload)

    def redeem(reader: ArtifactReader, artifact_id: str) -> ArtifactContent | None:
        return reader.content(artifact_id)

    store = FilesystemArtifactStore(tmp_path)
    ref = deposit(store, b'{"cases":[1,2,3]}')
    content = redeem(store, ref.id)

    assert isinstance(content, LocalFile)
    assert content.path.read_bytes() == b'{"cases":[1,2,3]}'


def test_the_legacy_name_still_resolves_to_the_filesystem_adapter() -> None:
    """24 call sites and 4 test modules import `ArtifactStore`; tests are append-only."""
    assert ArtifactStore is FilesystemArtifactStore


# --- content() replaces path_for at the port boundary ------------------------------------


def test_content_is_none_for_an_absent_artifact(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)

    assert store.content("a" * 64) is None


def test_content_is_none_for_a_malformed_id(tmp_path: Path) -> None:
    """INVARIANT: a traversal id and an unknown id are indistinguishable to a caller."""
    store = FilesystemArtifactStore(tmp_path)
    store.write_bytes(b"payload")

    assert store.content("../../etc/passwd") is None
    assert store.content("NOTHEX" * 10) is None


def test_a_remote_stream_carries_its_length_alongside_its_chunks() -> None:
    """A blob store cannot offer a path, so the port carries the size the file system implied."""

    async def chunks() -> AsyncIterator[bytes]:
        yield b"ab"
        yield b"cd"

    content = RemoteStream(stream=chunks(), size_bytes=4)

    assert content.size_bytes == 4


# --- the route serves a reader that has no filesystem at all -----------------------------


class _StreamOnlyReader:
    """A reader with NO filesystem — the shape an object-storage adapter has."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def content(self, artifact_id: str) -> ArtifactContent | None:
        if artifact_id != "b" * 64:
            return None

        async def chunks() -> AsyncIterator[bytes]:
            # Deliberately several chunks: a single-chunk stream would pass even if the
            # route only ever forwarded the first one.
            for start in range(0, len(self._payload), 8):
                yield self._payload[start : start + 8]

        return RemoteStream(stream=chunks(), size_bytes=len(self._payload))

    def delete(self, artifact_id: str) -> None: ...

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        return 0


def _app_with_reader(tmp_path: Path, reader: object) -> FastAPI:
    app = create_app(
        Settings(
            jwt_secret=SECRET,
            iat_window_s=WINDOW_S,
            artifacts_dir=str(tmp_path / "artifacts"),
        ),
        stream=InMemoryEventStream(),
        job_runner=RecordingJobRunner(),
        clock=lambda: T0,
    )
    app.state.artifact_store = reader
    return app


@pytest.mark.asyncio
async def test_the_route_serves_every_byte_of_a_stream_only_reader(tmp_path: Path) -> None:
    """STORY: as a researcher on the hosted Engine, I redeem a ticket for a result the
    Runner Job parked in object storage — the App has never had it on disk."""
    payload = b'{"cases":[' + b"1," * 5_000 + b"1]}"
    app = _app_with_reader(tmp_path, _StreamOnlyReader(payload))

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/artifacts/{'b' * 64}", headers=_cap("t"))

    assert response.status_code == 200
    assert response.content == payload


@pytest.mark.asyncio
async def test_a_stream_only_reader_still_404s_an_unknown_id(tmp_path: Path) -> None:
    app = _app_with_reader(tmp_path, _StreamOnlyReader(b"x"))

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/artifacts/{'c' * 64}", headers=_cap("t"))

    assert response.status_code == 404


def test_the_filesystem_route_still_uses_a_file_response(tmp_path: Path) -> None:
    """INVARIANT: `LocalFile` keeps `FileResponse`, which is what preserves HTTP Range on
    the local path — `test_a_range_request_does_not_consume_the_artifact` depends on it."""
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    ref = store.write_bytes(b"rangeable")
    app = _app_with_reader(tmp_path, store)

    with TestClient(app) as client:
        response = client.get(f"/artifacts/{ref.id}", headers={**_cap("t"), "Range": "bytes=0-3"})

    assert response.status_code == 206
    assert response.content == b"rang"
