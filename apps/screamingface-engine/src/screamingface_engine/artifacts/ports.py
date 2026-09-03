"""The two sides of the artifact hand-off, as ports the adapters implement.

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

WHY two ports and not one store: a single class served both sides until now because they
shared a filesystem. On the hosted Engine they do not — the Runner is a Job pod and the App
is a Deployment pod, each with its own `emptyDir` — so "the thing that parks a result" and
"the thing that hands it over" are two roles that happen to coincide only in local mode.
Splitting them is what lets object storage back the write side without the read side
learning about it.

INVARIANT: nothing here knows about HTTP. `screamingface_engine.artifacts` is a SHARED LEAF
of the layering gate — both halves import it — so a Starlette type reaching in would put the
serving framework into a Runner Job's cold start, which is exactly what that gate exists to
prevent. The port says what there is to render; `rest.artifacts` decides how.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from url4.streaming.protocol.signals import ResultArtifact


@dataclass(frozen=True)
class LocalFile:
    """Content the reader can hand over as a path on its own disk.

    WHY a path rather than bytes: it is what lets the route keep `FileResponse`, and with it
    bounded memory and HTTP Range for resume — capabilities a stream cannot offer.
    """

    path: Path


@dataclass(frozen=True)
class RemoteStream:
    """Content the reader must pull from somewhere else as it serves it.

    Carries `size_bytes` explicitly because the filesystem's `stat()` is gone: a client (and
    a `Content-Length`) still needs the length, and an object store knows it before the body
    arrives.
    """

    stream: AsyncIterator[bytes]
    size_bytes: int


# WHY a union rather than one flattened shape: the two storage kinds genuinely differ in what
# they can offer. Flattening would either lose Range on the local path or fake it on the
# remote one, and faking it is worse — a Range request that silently returns the whole body
# breaks resume for a client that believes it worked.
ArtifactContent = LocalFile | RemoteStream


@runtime_checkable
class ArtifactWriter(Protocol):
    """The Runner's side: park a finished result and mint its claim ticket.

    Deliberately SYNC. `runner.executor.build_result` already runs this under
    `asyncio.to_thread` so a large spill cannot stall heartbeats (OME-892 finding 10), so an
    async port would add a second concurrency story to a path that already has a working one.
    """

    def write_bytes(self, encoded: bytes) -> ResultArtifact: ...

    def write_text(self, body: str) -> ResultArtifact:
        """Encode `body` as UTF-8 and park it.

        WHY on the port and not just on the adapters: callers legitimately hold a `str` (the
        executor is the exception — it encodes once to measure the size, then hands over bytes so
        a gigabyte-scale result is not copied twice). Leaving it off the port only pushed those
        callers back onto a concrete class, which is the coupling the port exists to remove.
        """
        ...


@runtime_checkable
class ArtifactReader(Protocol):
    """The App's side: resolve a claim ticket, and reclaim what nobody redeemed.

    Sync for the same reason as the writer, and because `sweep` and `delete` are already sync
    across every existing call site and their tests, which are append-only.
    """

    def content(self, artifact_id: str) -> ArtifactContent | None: ...

    def delete(self, artifact_id: str) -> None: ...

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int: ...


__all__ = [
    "ArtifactContent",
    "ArtifactReader",
    "ArtifactWriter",
    "LocalFile",
    "RemoteStream",
]
