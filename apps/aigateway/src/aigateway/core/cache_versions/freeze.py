"""The freeze service (OME-1307, GW-freeze; contract C2b).

FEATURE: OME-1307 (E14) - one traced run becomes one immutable cache version.

INVARIANT: depends on ports only. No Tortoise, no plugin, no route.
INVARIANT (CV-D4): a version never changes after insert. Nothing reads capture rows again.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..request_cache.canonical import canonical_material
from .archive import CanonicalEntry, archive_prefix, blob_digest, write_canonical
from .ports import (
    ArchiveTooLarge,
    CacheVersionTooLarge,
    CaptureRow,
    CoverageStatus,
    FreezeResult,
    FreezeStore,
    LiveAnswer,
    NewBlob,
    NewEntry,
    ReceiptClaims,
    ReceiptSigner,
    StoredVersion,
    TraceNotCaptured,
    VersionAlreadyExists,
)
from .stats import CaptureStats

logger = logging.getLogger(__name__)

# The outcomes whose answer lives in the live cache row, not inline in the capture row (CV-D8).
_LIVE_OUTCOMES = frozenset({"hit", "stored"})


class FreezeService:
    def __init__(
        self,
        *,
        store: FreezeStore,
        signer: ReceiptSigner,
        stats: CaptureStats,
        max_entries: int,
        max_archive_bytes: int,
        on_frozen: Callable[[], None] | None = None,
        new_id: Callable[[], UUID] = uuid4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._signer = signer
        self._stats = stats
        self._max_entries = max_entries
        self._max_archive_bytes = max_archive_bytes
        self._on_frozen = on_frozen
        self._new_id = new_id
        self._now = now

    async def freeze(self, *, account_id: str, subject: str, trace_id: str) -> FreezeResult:
        existing = await self._store.find_version(account_id, trace_id)
        if existing is not None:
            return self._result(existing, subject=subject, created=False)

        rows = await self._store.load_capture(account_id, trace_id)
        if not rows:
            # CV-E1. Another account's rows are invisible, so CV-D2 gives the same answer.
            self._stats.freezes["not_found"] += 1
            raise TraceNotCaptured(trace_id)

        entries, shas, stored, missing_count = await self._copy_calls(rows)
        version, blobs, new_entries = await self._off_loop(
            self._build,
            account_id,
            trace_id,
            call_count=len(rows),
            missing_count=missing_count,
            entries=entries,
            shas=shas,
            stored=stored,
        )

        try:
            await self._store.insert_version(version, blobs, new_entries)
        except VersionAlreadyExists:
            winner = await self._store.find_version(account_id, trace_id)
            if winner is None:
                raise
            return self._result(winner, subject=subject, created=False)

        if self._on_frozen is not None:
            self._on_frozen()
        self._stats.missing_total += version.missing_count
        return self._result(version, subject=subject, created=True)

    async def _copy_calls(
        self, rows: list[CaptureRow]
    ) -> tuple[list[CanonicalEntry], list[str], dict[str, str | None], int]:
        """The entries, their blob shas, the stored blob metadata, and the missing-call count."""
        keys = {r.key_hash for r in rows if r.key_hash}
        prompts = await self._store.load_prompts(keys)
        live = await self._store.load_live_answers(
            {r.key_hash for r in rows if r.key_hash and r.outcome in _LIVE_OUTCOMES}
        )
        entries, shas, missing_count = await self._off_loop(
            _collect_entries, rows, prompts, live, self._max_entries
        )
        # WHY (4b): blobs are shared across versions and `insert_version` keeps the FIRST blob row.
        # The exporter rebuilds the archive from the STORED blob rows, so the digest must be
        # computed over the stored metadata, or the exporter would see a mismatch forever.
        stored = await self._store.load_blob_metadata(set(shas))
        return entries, shas, stored, missing_count

    async def _off_loop[**P, T](self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Run CPU-bound ``fn`` in a thread, so a large trace cannot stall the event loop.

        A too-large refusal is counted here: the counter is only ever touched on the loop.
        """
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except CacheVersionTooLarge:
            self._stats.freezes["too_large"] += 1
            raise

    def _build(
        self,
        account_id: str,
        trace_id: str,
        *,
        call_count: int,
        missing_count: int,
        entries: list[CanonicalEntry],
        shas: list[str],
        stored: Mapping[str, str | None],
    ) -> tuple[StoredVersion, list[NewBlob], list[NewEntry]]:
        entries = _with_stored_metadata(entries, shas, stored)
        try:
            digest = write_canonical(entries, None, max_bytes=self._max_archive_bytes)
        except ArchiveTooLarge:
            raise CacheVersionTooLarge("archive_bytes") from None
        version_id = self._new_id()
        blobs: dict[str, NewBlob] = {}
        new_entries: list[NewEntry] = []
        for entry, sha in zip(entries, shas, strict=True):
            if sha not in blobs:
                blobs[sha] = NewBlob(
                    sha256=sha,
                    request_json=entry.request_json,
                    response_json=entry.response_json,
                    metadata_json=entry.metadata_json,
                    size_bytes=len(entry.request_json.encode()) + len(entry.response_json.encode()),
                )
            new_entries.append(NewEntry(entry.key_hash, sha, entry.first_ordinal))
        coverage: CoverageStatus = "complete" if missing_count == 0 else "partial"
        version = StoredVersion(
            id=version_id,
            owner_account_id=account_id,
            trace_id=trace_id,
            status="frozen",
            entry_count=len(entries),
            call_count=call_count,
            missing_count=missing_count,
            coverage_status=coverage,
            archive_sha256=digest.sha256,
            archive_key=archive_prefix(version_id),
            created_at=self._now(),
        )
        return version, list(blobs.values()), new_entries

    def _result(self, version: StoredVersion, *, subject: str, created: bool) -> FreezeResult:
        self._stats.freezes["created" if created else "reused"] += 1
        receipt = self._signer.sign(
            ReceiptClaims(
                sub=subject,
                vid=version.id,
                tid=version.trace_id,
                sha=version.archive_sha256,
                n=version.entry_count,
                c=version.call_count,
                cov=version.coverage_status,
            )
        )
        return FreezeResult(
            created=created,
            version_id=version.id,
            entry_count=version.entry_count,
            call_count=version.call_count,
            missing_count=version.missing_count,
            coverage_status=version.coverage_status,
            archive_sha256=version.archive_sha256,
            receipt=receipt,
        )


def _collect_entries(
    rows: list[CaptureRow],
    prompts: dict[str, str],
    live: dict[str, LiveAnswer],
    max_entries: int,
) -> tuple[list[CanonicalEntry], list[str], int]:
    """The de-duplicated entries of ``rows``, their blob shas, and the number of missing calls.

    Raises ``CacheVersionTooLarge("entries")`` as soon as there are more than ``max_entries``
    entries, so an oversized trace is refused without copying the rest of it.
    """
    entries: list[CanonicalEntry] = []
    shas: list[str] = []
    seen: set[tuple[str, str]] = set()
    missing_count = 0
    # WHY position and not the capture ordinal (OD-F3): the global ordinal would leak the
    # gateway's other traffic volume into a public archive.
    for position, row in enumerate(rows):
        copied = _copy_call(row, prompts, live)
        if copied is None:
            missing_count += 1
            continue
        request_json, response_json, metadata_json, sha = copied
        assert row.key_hash is not None  # _copy_call returns None for a keyless row
        if (row.key_hash, sha) in seen:
            continue  # the same call twice is one entry, not a missing call
        seen.add((row.key_hash, sha))
        entries.append(
            CanonicalEntry(row.key_hash, position, request_json, response_json, metadata_json)
        )
        shas.append(sha)
        if len(entries) > max_entries:
            raise CacheVersionTooLarge("entries")
    return entries, shas, missing_count


def _canonical_or_none(text: str | None) -> str | None:
    """The canonical text of JSON ``text``. An empty text and JSON ``null`` are no metadata."""
    if not text:
        return None
    value = json.loads(text)
    return None if value is None else canonical_material(value)


def _with_stored_metadata(
    entries: list[CanonicalEntry], shas: Sequence[str], stored: Mapping[str, str | None]
) -> list[CanonicalEntry]:
    """``entries`` with the metadata of each blob that is already stored (the stored row wins).

    The stored text is parsed and re-rendered, never spliced: it may not be canonical.
    """
    merged = list(entries)
    for index, sha in enumerate(shas):
        if sha in stored and stored[sha] != merged[index].metadata_json:
            merged[index] = dataclasses.replace(
                merged[index], metadata_json=_canonical_or_none(stored[sha])
            )
    return merged


def _request_text(prompt: str, key_hash: str) -> str:
    """The canonical text of a stored prompt.

    The prompt IS the key material, so ``sha256(prompt) == key_hash`` proves it canonical and it
    is used as is. A prompt that fails the check (a test fake, a foreign row) is parsed and
    rendered. NEVER trust a prompt without the check.
    """
    if hashlib.sha256(prompt.encode("utf-8")).hexdigest() == key_hash:
        return prompt
    return canonical_material(json.loads(prompt))


def _copy_call(
    row: CaptureRow, prompts: dict[str, str], live: dict[str, LiveAnswer]
) -> tuple[str, str, str | None, str] | None:
    """The canonical (request, response, metadata) TEXTS and blob sha of one call.

    ``None`` when the call is missing.
    """
    if row.outcome == "error" or row.key_hash is None:  # CV-D7
        return None
    prompt = prompts.get(row.key_hash)
    if prompt is None:
        return None
    metadata_text: str | None = None
    if row.outcome in _LIVE_OUTCOMES:
        answer = live.get(row.key_hash)
        if answer is None:  # CV-E2: the live row was pruned or has expired
            return None
        response_text, metadata_text = answer.response_json, answer.metadata_json
    else:
        if row.response_json is None:
            return None
        response_text = row.response_json
    try:
        request_json = _request_text(prompt, row.key_hash)
        response_json = canonical_material(json.loads(response_text))
        # In the guard on purpose: hashing encodes the texts, which a lone surrogate refuses.
        sha = blob_digest(request_json, response_json)
        return request_json, response_json, _canonical_or_none(metadata_text), sha
    except ValueError:
        # Covers a JSON decode error, a non-canonicalisable value (NaN) and an unencodable text.
        # The key prefix only: the row holds prompt and answer text.
        logger.warning(
            "freeze: call %s... cannot be canonicalised; counted as missing", row.key_hash[:12]
        )
        return None
