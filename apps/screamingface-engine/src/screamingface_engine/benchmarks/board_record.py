"""The ``board.json`` record of an Imported Board: its schema, and what may open (OME-1803).

FEATURE (OME-1803, owner 2026-11-04, review on #1645): admission reads ``modalities`` from this
record instead of scanning the rows, so the record must be canonical AND bound to the Cases it
describes. Schema v3 carries ``cases_sha256``, the hex SHA-256 of ``cases.json``; the open
re-hashes the file in blocks and refuses a mismatch. A v2 record has no digest and is refused
by name (re-prepare); v1 keeps the legacy full scan in :func:`board_store.open_board`.

AIDEV-NOTE: split out of ``board_store`` to keep that file under the 450-line limit; the store
re-exports every public name, so callers import from ``board_store`` as before.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable
from screamingface_engine.benchmarks.picture_admission import PART_MODALITIES
from url4.core.errors import ResolutionError

BOARD_FILE = "board.json"
OFFSETS_FILE = "cases.offsets"
CASES_FILE = "cases.json"
BOARD_SCHEMA = "screamingface.board.v3"
BOARD_SCHEMA_V2 = "screamingface.board.v2"
"""The OME-1803 record without a digest: refused at open, the bundle must be re-prepared."""
BOARD_SCHEMA_V1 = "screamingface.board.v1"
"""The OME-1790 record (``has_pictures``), read only through the legacy full scan."""

_NEEDS: frozenset[str] = frozenset(PART_MODALITIES.values())
"""The only values a recorded ``modalities`` set may hold: the table's non-text types."""
_DIGEST_BLOCK = 1 << 20
"""Bytes of ``cases.json`` hashed per read at open: memory stays one block for any board."""


def broken(detail: str) -> ResolutionError:
    """The bounded ``benchmark_unavailable`` every refused board raises."""

    return benchmark_unavailable(f"imported board cases are unavailable: {detail}")


def v3_record(meta: object) -> dict[str, object]:
    """``meta`` as a v3 record; a v2 one is refused by name so its owner knows to re-prepare."""

    if isinstance(meta, dict) and meta.get("schema") == BOARD_SCHEMA_V2:
        raise broken(
            f"{BOARD_FILE} is a {BOARD_SCHEMA_V2} record with no {CASES_FILE} digest; "
            "re-prepare the board"
        )
    if not isinstance(meta, dict) or meta.get("schema") != BOARD_SCHEMA:
        raise broken(f"{BOARD_FILE} is not a {BOARD_SCHEMA} record")
    return meta


def recorded_modalities(modalities: object) -> list[str]:
    """The record's set, only in the canonical form ``encode_board`` writes.

    INVARIANT: a missing or malformed set fails closed; reading it as "text only" would admit a
    blind model to a picture or PDF board.
    """

    if not isinstance(modalities, list) or not all(
        isinstance(modality, str) for modality in modalities
    ):
        raise broken(f"{BOARD_FILE} modalities is not a list of strings")
    # INVARIANT (review on #1645, blocker 1): a set naming "text" or an unknown type would be
    # satisfied by a text-only model, so a PDF board relabelled ["text"] would be admitted to
    # one; sorted and distinct keeps the record the pure function of the rows.
    if modalities != sorted(set(modalities)) or not set(modalities) <= _NEEDS:
        raise broken(
            f"{BOARD_FILE} modalities {modalities!r} is not a sorted, distinct subset of "
            f"{sorted(_NEEDS)}"
        )
    return modalities


def cases_digest(cases: Path) -> str:
    """The hex SHA-256 of ``cases``, read one ``_DIGEST_BLOCK`` at a time.

    AIDEV-NOTE: O(board) I/O on every open (the Cases route opens per run), O(1) memory. Owner
    decision 2026-11-04: integrity over the OME-1790 I/O saving at open.
    """

    digest = hashlib.sha256()
    try:
        with cases.open("rb") as handle:
            for block in iter(lambda: handle.read(_DIGEST_BLOCK), b""):
                digest.update(block)
    except OSError as exc:
        raise broken(f"{CASES_FILE} cannot be read ({exc})") from exc
    return digest.hexdigest()


__all__ = [
    "BOARD_FILE",
    "BOARD_SCHEMA",
    "BOARD_SCHEMA_V1",
    "BOARD_SCHEMA_V2",
    "CASES_FILE",
    "OFFSETS_FILE",
    "broken",
    "cases_digest",
    "recorded_modalities",
    "v3_record",
]
