"""Content-addressed spill store on the local filesystem.

FEATURE: deliver large results in full instead of cutting them off at 1 MiB (OME-892).

Think of it as the parcel counter behind the mail slot: the runner leaves the complete
result here under its own fingerprint, the terminal frame carries only the claim ticket
(`ResultArtifact`), and the REST route hands the file over when the client redeems the
ticket. Stage order per run: `write_text` (runner, at completion) → `content` (REST GET),
with `sweep` — at app startup AND periodically — collecting parcels nobody ever picked up
(crashed runs, clients that vanished).

INVARIANT: fetching NEVER deletes. Content addressing means one file can back many claim
tickets (identical results dedupe onto one path), a dropped connection must be retryable,
and a Range request must leave the rest of the file fetchable — delete-on-first-GET broke
all three (review finding on OME-892). Artifacts die by TTL alone.

INVARIANT: the filename IS the sha256 of the content, so the id doubles as the integrity
check and a well-formed id can never name anything outside the flat store root.

AIDEV-NOTE: correct for `inprocess`/local, where the writer and the reader are ONE process
and share this directory by construction. It is NOT correct for the `k8s`/`jetstream`
backends — see `s3.py` and OME-929. Selecting it there is what produced a 404 after a full
run's spend, so the selection is derived rather than configurable.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from pathlib import Path

from screamingface_engine.artifacts.ports import ArtifactContent, LocalFile
from url4.streaming.protocol.signals import ResultArtifact

_ARTIFACT_ID = re.compile(r"^[0-9a-f]{64}$")


class FilesystemArtifactStore:
    """Flat directory of files named by the lowercase sha256 hex of their content."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def write_text(self, body: str) -> ResultArtifact:
        """Persist `body` and return its claim ticket. See `write_bytes`."""
        return self.write_bytes(body.encode("utf-8"))

    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        """Persist already-encoded content and return its claim ticket. Idempotent.

        Takes bytes so a caller that has already UTF-8-encoded (the executor encodes
        once to measure the size) never pays a second gigabyte-scale copy.

        The write is tmp-file + `os.replace` so a crash mid-write never leaves a
        half-parcel under a valid id — an id either resolves to complete content or to
        nothing.
        """
        digest = hashlib.sha256(encoded).hexdigest()
        self._root.mkdir(parents=True, exist_ok=True)
        final = self._root / digest
        # INVARIANT: a dedup hit re-stamps mtime — re-depositing a parcel restarts its
        # TTL clock. Tickets are per run but the file is shared by content, so without
        # the touch a byte-identical result re-arriving near (or past) the first copy's
        # TTL would mint a fresh ticket pointing at a file the next sweep removes.
        try:
            os.utime(final)
        except FileNotFoundError:
            tmp = self._root / f".{digest}.{uuid.uuid4().hex}.tmp"
            tmp.write_bytes(encoded)
            os.replace(tmp, final)
        return ResultArtifact(id=digest, size_bytes=len(encoded), sha256=digest)

    def content(self, artifact_id: str) -> ArtifactContent | None:
        """The stored content for `artifact_id`, or None when absent or malformed.

        Returns `LocalFile` — the route renders it with `FileResponse`, which is what keeps
        bounded memory and HTTP Range on this path.
        """
        path = self.path_for(artifact_id)
        return None if path is None else LocalFile(path=path)

    def path_for(self, artifact_id: str) -> Path | None:
        """The stored file for `artifact_id`, or None when absent or malformed.

        AIDEV-NOTE: kept alongside `content` because 14 call sites and their append-only
        tests name it. It is the filesystem adapter's own detail, NOT part of the
        `ArtifactReader` port — an object-storage reader has no path to return.
        """
        if _ARTIFACT_ID.fullmatch(artifact_id) is None:
            return None
        path = self._root / artifact_id
        return path if path.is_file() else None

    def delete(self, artifact_id: str) -> None:
        """Remove a parcel once redeemed. Absence is not an error — deletes race sweeps."""
        path = self.path_for(artifact_id)
        if path is not None:
            path.unlink(missing_ok=True)

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Delete artifacts (and `.tmp` write leftovers) older than `ttl_seconds`.

        Age is mtime-based: `write_bytes` stamps it on first write AND re-stamps it on
        every dedup hit, so mtime is the parcel's LAST deposit time — the youngest
        ticket's age, never the oldest's. Returns how many files were removed.

        INVARIANT: tolerant of concurrent life — a file may vanish between listing and
        stat (another sweep, an operator's rm); that is a completed job, not an error.
        The sweeper loop in `app.py` must never die of a race.
        """
        if not self._root.is_dir():
            return 0
        cutoff = (time.time() if now is None else now) - ttl_seconds
        removed = 0
        for path in self._root.iterdir():
            # `.tmp` files are crash leftovers from `write_bytes`'s atomic-rename dance —
            # invisible to `path_for`, but they hold real bytes and must age out too.
            named_like_ours = _ARTIFACT_ID.fullmatch(path.name) is not None or path.name.endswith(
                ".tmp"
            )
            if not named_like_ours:
                continue
            try:
                expired = path.stat().st_mtime < cutoff
            except FileNotFoundError:
                continue
            if expired:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


__all__ = ["FilesystemArtifactStore"]
