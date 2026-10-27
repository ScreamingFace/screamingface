"""Park each Case's pictures and files in the result store, so a researcher can open one later.

FEATURE (OME-1271, PR 5): since PR 3 a Case Result shows each picture or file as a placeholder
(type, size, sha256), never its bytes. Think of a cloakroom: when a run finishes, each picture is
hung on a peg numbered by its sha256, and the result carries only the peg number. The pegs are the
result store the App already serves at ``GET /artifacts/{id}``, which names every item by the
sha256 of its bytes; the client-facing App can't read the Benchmark files, but it can read that.

INVARIANT: the name a picture is parked under is the sha256 of the bytes the model was sent, the
same value ``media_placeholder`` writes into the placeholder. Both decode the reader-checked
``data:`` URI as written.

AIDEV-NOTE: parked items expire with the store's own rule: the filesystem store's sweep after
``artifact_ttl_s`` (48 hours), restarted each time a run parks the same bytes again; the S3 store
leaves expiry to the bucket's lifecycle rule (``artifacts/s3.py`` ``sweep``). A fetch after that is
a named miss in the SDK, never a different picture.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import logging
from collections.abc import Iterator
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

    def park(self, case_input: str) -> None:
        """Park every picture and file in ``case_input`` not yet parked in this run.

        Stage 1 — read the Case by the members' rules. A plain prompt, a text conversation or a
            Case the reader refuses has no bytes to park; a refused Case already failed when
            the Candidate was asked, and its Case Result shows one line instead of it.
        Stage 2 — per picture or file part: decode the ``data:`` URI and hash the bytes; a
            sha256 already parked in this run is skipped.
        Stage 3 — write the bytes. A store that fails is logged by sha256 and never raised: the
            picture is for looking at later, and a run that graded every Case must keep its result.

        e.g. a FigQA Case with one 300 KB PNG → one write of those 300 KB under
        ``sha256 9f86…``; the same Case for the next Candidate → no write.
        """

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
                    logger.warning("could not park picture or file sha256 %s: %s", digest, exc)
                    continue
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


__all__ = ["MediaParking", "park_case_media", "parking_media"]
