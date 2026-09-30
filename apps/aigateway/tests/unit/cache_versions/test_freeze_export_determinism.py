"""Freeze, then export: the rebuilt archive is the frozen one, byte for byte (OME-1307, E14).

FEATURE: OME-1307 (E14) - the freeze hashes the archive it WOULD write, and the exporter rebuilds it
later from the stored blob rows. The two must agree, or the exporter refuses to upload forever.
INVARIANT: this covers what the older equality tests do not: a blob shared by two versions whose
live metadata changed between the freezes (non-canonical and non-ASCII), the inline (`unstored`)
call whose answer is in the capture row, and a prompt that is not sha-keyed.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from aigateway.core.cache_versions.archive import ENTRIES_OBJECT, archive_prefix, write_entries
from aigateway.core.cache_versions.exporter import CacheVersionExporter
from aigateway.core.cache_versions.freeze import FreezeService
from aigateway.core.cache_versions.freeze_store import TortoiseFreezeStore
from aigateway.core.cache_versions.models import CacheCaptureEntry, RequestCachePrompt
from aigateway.core.cache_versions.ports import ReceiptClaims, StoredVersion
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.core.request_cache.canonical import canonical_material
from aigateway.core.request_cache.models import RequestCacheEntry

_ACCOUNT = "acct-determinism"
_TRACE_ONE = "d1" * 16
_TRACE_TWO = "d2" * 16

_REQUEST = {"model": "mé", "messages": [{"role": "user", "content": 'café   "q"'}]}
_INLINE_REQUEST = {"model": "m", "messages": [{"role": "user", "content": "inline ☃"}]}
_SHARED_ANSWER = '{"choices": [{"message": {"content": "réponse"}}],  "usage": {"x": 1.50}}'
_INLINE_ANSWER = '{"z": 1, "a": ["ü", 1e2]}'
_METADATA_ONE = '{"who": "M1 é", "n": 1.0}'
_METADATA_TWO = '{"who": "M2 ü",  "n": 2.0}'


class _Signer:
    kid = "k"

    def sign(self, claims: ReceiptClaims) -> str:
        return "receipt"


class _Archive:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_once(
        self, key: str, path: Path, *, sha256_hex: str
    ) -> Literal["written", "exists"]:
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha256_hex
        self.objects[key] = data
        return "written"


def _key_of(request: dict[str, Any]) -> tuple[str, str]:
    material = canonical_material(request)
    return material, hashlib.sha256(material.encode()).hexdigest()


async def _seed_prompt(request: dict[str, Any]) -> str:
    material, key = _key_of(request)
    await RequestCachePrompt.get_or_create(key_hash=key, defaults={"request_json": material})
    return key


async def _set_live(key: str, *, metadata: str) -> None:
    await RequestCacheEntry.filter(key_hash=key).delete()
    await RequestCacheEntry.create(
        key_hash=key,
        prompt_hash=key,
        provider="test",
        model="m",
        response_json=_SHARED_ANSWER,
        response_size_bytes=len(_SHARED_ANSWER),
        metadata_json=metadata,
        expires_at=None,
    )


async def _capture(trace: str, key: str, outcome: str, inline: str | None = None) -> None:
    await CacheCaptureEntry.create(
        account_id=_ACCOUNT, trace_id=trace, key_hash=key, outcome=outcome, response_json=inline
    )


def _oracle_line(key: str, ordinal: int, request: Any, response: str, metadata: str | None) -> str:
    """One expected line, from the inputs alone: parse, then ONE `canonical_material`."""
    return canonical_material(
        {
            "key_hash": key,
            "first_ordinal": ordinal,
            "request": request,
            "response": json.loads(response),
            "metadata": json.loads(metadata) if metadata is not None else None,
        }
    )


def _lines(data: bytes) -> list[str]:
    # WHY not `splitlines`: it also splits on U+2028, which a canonical line holds verbatim.
    text = gzip.decompress(data).decode("utf-8")
    assert text.endswith("\n")
    return text[:-1].split("\n")


def test_a_shared_blob_and_a_changed_live_metadata_export_to_the_frozen_digest(
    client: Any,
) -> None:
    archive, stats = _Archive(), CaptureStats()
    store = TortoiseFreezeStore()
    service = FreezeService(
        store=store,
        signer=_Signer(),
        stats=CaptureStats(),
        max_entries=100,
        max_archive_bytes=10**9,
    )
    exporter = CacheVersionExporter(
        store=store,
        archive=archive,
        stats=stats,
        poll_interval_s=3600.0,
        jitter=lambda: 0.0,
    )

    async def _scenario() -> tuple[StoredVersion, StoredVersion, list[bytes], int]:
        shared_key = await _seed_prompt(_REQUEST)
        inline_key = await _seed_prompt(_INLINE_REQUEST)

        await _set_live(shared_key, metadata=_METADATA_ONE)
        await _capture(_TRACE_ONE, shared_key, "stored")
        await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=_TRACE_ONE)

        # The live row changes AFTER the first freeze. The stored blob keeps M1, so the second
        # version must hash M1 too, or its export would mismatch forever.
        await _set_live(shared_key, metadata=_METADATA_TWO)
        await _capture(_TRACE_TWO, shared_key, "hit")
        await _capture(_TRACE_TWO, inline_key, "unstored", _INLINE_ANSWER)
        await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=_TRACE_TWO)

        one = await store.find_version(_ACCOUNT, _TRACE_ONE)
        two = await store.find_version(_ACCOUNT, _TRACE_TWO)
        assert one is not None and two is not None
        archived = await exporter.run_once()
        rebuilt: list[bytes] = []
        for version in (one, two):
            buffer = io.BytesIO()
            entries = await store.load_archive_entries(version.id)
            write_entries(entries, buffer, max_bytes=10**9)
            again = io.BytesIO()
            write_entries(await store.load_archive_entries(version.id), again, max_bytes=10**9)
            assert buffer.getvalue() == again.getvalue(), "the same rows give the same bytes"
            rebuilt.append(buffer.getvalue())
        return one, two, rebuilt, archived

    one, two, rebuilt, archived = client.portal.call(_scenario)

    assert archived == 2
    assert stats.export_digest_mismatches == 0
    shared_key = _key_of(_REQUEST)[1]
    inline_key = _key_of(_INLINE_REQUEST)[1]

    one_bytes = archive.objects[archive_prefix(one.id) + ENTRIES_OBJECT]
    two_bytes = archive.objects[archive_prefix(two.id) + ENTRIES_OBJECT]
    assert hashlib.sha256(one_bytes).hexdigest() == one.archive_sha256
    assert hashlib.sha256(two_bytes).hexdigest() == two.archive_sha256
    assert rebuilt == [one_bytes, two_bytes]

    shared_one = _oracle_line(shared_key, 0, _REQUEST, _SHARED_ANSWER, _METADATA_ONE)
    shared_two = _oracle_line(shared_key, 0, _REQUEST, _SHARED_ANSWER, _METADATA_ONE)
    inline = _oracle_line(inline_key, 1, _INLINE_REQUEST, _INLINE_ANSWER, None)
    assert _lines(one_bytes) == [shared_one]
    assert _lines(two_bytes) == [shared_two, inline]
    assert "M2" not in gzip.decompress(two_bytes).decode(), "the stored metadata wins"


def test_a_prompt_that_is_not_sha_keyed_exports_to_the_frozen_digest(client: Any) -> None:
    # The fallback path: the stored prompt is not the key material of its key, so the freeze parses
    # and renders it. The stored blob is then canonical, and the export must agree.
    archive, stats = _Archive(), CaptureStats()
    store = TortoiseFreezeStore()
    service = FreezeService(
        store=store,
        signer=_Signer(),
        stats=CaptureStats(),
        max_entries=100,
        max_archive_bytes=10**9,
    )
    exporter = CacheVersionExporter(
        store=store, archive=archive, stats=stats, poll_interval_s=3600.0, jitter=lambda: 0.0
    )
    foreign_key = f"{7:064x}"
    foreign_prompt = '{"model": "m",  "messages": [{"content": "café", "role": "user"}]}'

    async def _scenario() -> tuple[UUID, str, int]:
        await RequestCachePrompt.create(key_hash=foreign_key, request_json=foreign_prompt)
        await _set_live(foreign_key, metadata=_METADATA_ONE)
        await _capture(_TRACE_ONE, foreign_key, "stored")
        result = await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=_TRACE_ONE)
        return result.version_id, result.archive_sha256, await exporter.run_once()

    version_id, frozen_sha, archived = client.portal.call(_scenario)

    assert archived == 1
    assert stats.export_digest_mismatches == 0
    data = archive.objects[archive_prefix(version_id) + ENTRIES_OBJECT]
    assert hashlib.sha256(data).hexdigest() == frozen_sha
    assert _lines(data) == [
        _oracle_line(foreign_key, 0, json.loads(foreign_prompt), _SHARED_ANSWER, _METADATA_ONE)
    ]
