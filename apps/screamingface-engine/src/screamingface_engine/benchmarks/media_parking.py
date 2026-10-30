"""Park each Case's pictures and files in the result store, so a researcher can open one later.

FEATURE (OME-1271, PR 5): since PR 3 a Case Result shows each picture or file as a placeholder
(type, size, sha256), never its bytes. Think of a cloakroom: when a run finishes, each picture is
hung on a peg numbered by its sha256, and the result carries only the peg number. The pegs are the
result store the App already serves at ``GET /artifacts/{id}``, which names every item by the
sha256 of its bytes; the client-facing App can't read the Benchmark files, but it can read that.

INVARIANT: the name a picture is parked under is the sha256 of the bytes the model was sent, the
same value ``media_placeholder`` writes into the placeholder. Both decode the reader-checked
``data:`` URI as written.

AIDEV-NOTE: parked items expire only by the store's own rule. The filesystem store sweeps them after
``artifact_ttl_s`` (48 hours by default), restarted each time a run parks the same bytes again. The
S3 store leaves expiry to a bucket lifecycle rule (``artifacts/s3.py`` ``sweep``), and no
deployment configures one today, so a deployment keeps every parked picture until someone deletes
it. A fetch after expiry is a named miss in the SDK, never a different picture.

AIDEV-NOTE: the writer is synchronous (the ``ArtifactWriter`` port), so the async callers run
``park_cases_media`` under ``asyncio.to_thread``; parked on the run's event loop, a slow store
would freeze every other step of the run while it waits.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import logging
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from screamingface_engine.artifacts import ArtifactWriter, S3StorageError
from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    CandidateMessage,
    parse_candidate_input,
)

logger = logging.getLogger(__name__)


class MediaParking:
    """One run's cloakroom attendant: hang each distinct picture or file once, by its sha256."""

    def __init__(self, writer: ArtifactWriter) -> None:
        self._writer: ArtifactWriter = writer
        # WHY remembered per run: every Candidate of a run finishes over the same Cases, so a
        # lineup of four would otherwise upload FigQA's 181 pictures four times.
        self._parked: set[str] = set()
        # WHY stop after one failure: a store that is down answers each write only at its
        # timeout (30 s for S3), so FigQA's 181 pictures would hold the run's finish for
        # 90 minutes, once per Candidate. The first failure says so; the rest are skipped.
        self._stopped: bool = False
        # WHY a lock: two Candidates of a Fusion can finish at once, each parking from its own
        # thread, and the same picture must still be written once.
        self._lock: threading.Lock = threading.Lock()

    def park(self, case_input: str) -> None:
        """Park every picture and file in ``case_input`` not yet parked in this run.

        Stage 1 — read the Case by the members' rules. A plain prompt, a text conversation or a
            Case the reader refuses has no bytes to park; a refused Case already failed when
            the Candidate was asked, and its Case Result shows one line instead of it.
        Stage 2 — per picture or file part: decode the ``data:`` URI and hash the bytes; a
            sha256 already parked in this run is skipped.
        Stage 3 — write the bytes. A store that fails is logged by sha256 and never raised: the
            picture is for looking at later, and a run that graded every Case must keep its result.
            After that first failure this attendant parks nothing more for the rest of the run.

        e.g. a FigQA Case with one 300 KB PNG → one write of those 300 KB under
        ``sha256 9f86…``; the same Case for the next Candidate → no write.
        """

        with self._lock:
            if not self._stopped:
                self._park(case_input)

    def _park(self, case_input: str) -> None:
        """``park``'s stages, run under the lock while the store still answers."""

        # Stage 1 — read the Case.
        try:
            messages: list[CandidateMessage] | None = parse_candidate_input(case_input)
        except CandidateInputError:
            return
        for message in messages or ():
            content = message["content"]
            if isinstance(content, str):
                continue
            for part in content:
                if part["type"] == "text":
                    continue
                # Stage 2 — decode and name. WHY no error branch: the reader accepted only the
                # standard base64 spelling, which always decodes.
                uri: str = (
                    part["image_url"]["url"]
                    if part["type"] == "image_url"
                    else part["file"]["file_data"]
                )
                data: bytes = base64.b64decode(uri.partition(",")[2], validate=True)
                digest: str = hashlib.sha256(data).hexdigest()
                if digest in self._parked:
                    continue
                # Stage 3 — write.
                try:
                    self._writer.write_bytes(data)
                except (OSError, S3StorageError) as exc:
                    logger.warning(
                        "could not park picture or file sha256 %s, so this run parks no more: %s",
                        digest,
                        exc,
                    )
                    self._stopped = True
                    return
                self._parked.add(digest)


_parking: contextvars.ContextVar[MediaParking | None] = contextvars.ContextVar(
    "screamingface_media_parking", default=None
)


@contextmanager
def parking_media(parking: MediaParking | None) -> Iterator[None]:
    """Bind the run's attendant for the enclosed steps; ``None`` leaves the run parking nothing.

    INVARIANT: the binding never leaks past its context, so one run never parks into another's
    store.
    """

    token: contextvars.Token[MediaParking | None] = _parking.set(parking)
    try:
        yield
    finally:
        _parking.reset(token)


def park_case_media(case_input: str) -> None:
    """Park ``case_input``'s pictures and files with the bound run's attendant, if there is one."""

    parking: MediaParking | None = _parking.get()
    if parking is not None:
        parking.park(case_input)


def park_cases_media(case_inputs: Sequence[str]) -> None:
    """Park every Case's pictures and files; the async callers run this in a worker thread.

    WHY a thread can see the binding: ``asyncio.to_thread`` runs the call in a copy of the
    caller's context, so the run's attendant bound by ``parking_media`` is the one used.
    """

    for case_input in case_inputs:
        park_case_media(case_input)


__all__ = ["MediaParking", "park_case_media", "park_cases_media", "parking_media"]
