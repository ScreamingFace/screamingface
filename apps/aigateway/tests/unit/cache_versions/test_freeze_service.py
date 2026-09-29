"""CV-11, CV-15 and support: the freeze service, against a fake store (no database).

FEATURE: OME-1307 (E14) - one captured trace becomes one immutable version.
INVARIANT (CV-D7): a call whose outcome is `error` is counted as missing and never stored as a
blob. INVARIANT (CV-D3): a second freeze of the same trace returns the same version and hash.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from aigateway.core.cache_versions.archive import archive_prefix, blob_sha256, write_entries
from aigateway.core.cache_versions.freeze import FreezeService
from aigateway.core.cache_versions.ports import (
    ArchiveEntry,
    CacheVersionTooLarge,
    CaptureRow,
    LiveAnswer,
    NewBlob,
    NewEntry,
    ReceiptClaims,
    StoredVersion,
    TraceNotCaptured,
    VersionAlreadyExists,
)
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.core.request_cache.canonical import canonical_material

pytestmark = pytest.mark.asyncio

_ACCOUNT = "acct-1"
_TRACE = "ab" * 16
_NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def _key(n: int) -> str:
    return f"{n:064x}"


def _request(n: int) -> dict[str, Any]:
    return {"model": "m", "messages": [{"role": "user", "content": f"prompt {n}"}]}


def _response(n: int) -> dict[str, Any]:
    return {"choices": [{"message": {"content": f"answer {n}"}}]}


class FakeFreezeStore:
    """The FreezeStore contract in memory, with hooks to inject a race."""

    def __init__(self) -> None:
        self.rows: list[CaptureRow] = []
        self.prompts: dict[str, str] = {}
        self.live: dict[str, LiveAnswer] = {}
        self.blob_metadata: dict[str, str | None] = {}
        self.versions: dict[tuple[str, str], StoredVersion] = {}
        self.inserted: list[tuple[StoredVersion, list[NewBlob], list[NewEntry]]] = []
        self.race_winner: StoredVersion | None = None

    def add_call(
        self,
        n: int,
        outcome: str,
        *,
        prompt: bool = True,
        live: bool | str | None = None,
        inline: str | None = None,
        key: str | None = None,
    ) -> str:
        key_hash = key if key is not None else _key(n)
        self.rows.append(CaptureRow(len(self.rows) + 100, key_hash, outcome, inline))
        if prompt:
            self.prompts[key_hash] = canonical_material(_request(n))
        if live:
            text = live if isinstance(live, str) else json.dumps(_response(n))
            self.live[key_hash] = LiveAnswer(text, None)
        return key_hash

    async def find_version(self, owner_account_id: str, trace_id: str) -> StoredVersion | None:
        return self.versions.get((owner_account_id, trace_id))

    async def load_capture(self, account_id: str, trace_id: str) -> list[CaptureRow]:
        return list(self.rows) if (account_id, trace_id) == (_ACCOUNT, _TRACE) else []

    async def load_prompts(self, key_hashes: Collection[str]) -> dict[str, str]:
        return {k: v for k, v in self.prompts.items() if k in key_hashes}

    async def load_live_answers(self, key_hashes: Collection[str]) -> dict[str, LiveAnswer]:
        return {k: v for k, v in self.live.items() if k in key_hashes}

    async def load_blob_metadata(self, shas: Collection[str]) -> dict[str, str | None]:
        return {k: v for k, v in self.blob_metadata.items() if k in shas}

    async def insert_version(
        self, version: StoredVersion, blobs: Sequence[NewBlob], entries: Sequence[NewEntry]
    ) -> None:
        if self.race_winner is not None:
            self.versions[(version.owner_account_id, version.trace_id)] = self.race_winner
            raise VersionAlreadyExists
        self.versions[(version.owner_account_id, version.trace_id)] = version
        self.inserted.append((version, list(blobs), list(entries)))


class FakeSigner:
    kid = "fake-kid"

    def __init__(self) -> None:
        self.claims: list[ReceiptClaims] = []

    def sign(self, claims: ReceiptClaims) -> str:
        self.claims.append(claims)
        return f"receipt-for-{claims.vid}"


def _service(
    store: FakeFreezeStore,
    *,
    signer: FakeSigner | None = None,
    stats: CaptureStats | None = None,
    max_entries: int = 100,
    max_archive_bytes: int = 10**9,
    on_frozen: Any = None,
    vid: str = "11111111-2222-4333-8444-555555555555",
) -> FreezeService:
    return FreezeService(
        store=store,
        signer=signer or FakeSigner(),
        stats=stats or CaptureStats(),
        max_entries=max_entries,
        max_archive_bytes=max_archive_bytes,
        on_frozen=on_frozen,
        new_id=lambda: UUID(vid),
        now=lambda: _NOW,
    )


async def _freeze(service: FreezeService, *, subject: str = "ada@example.org") -> Any:
    return await service.freeze(account_id=_ACCOUNT, subject=subject, trace_id=_TRACE)


async def test_freeze_unknown_trace_404() -> None:
    store = FakeFreezeStore()
    stats = CaptureStats()

    with pytest.raises(TraceNotCaptured):
        await _freeze(_service(store, stats=stats))

    assert store.inserted == []
    assert stats.freezes["not_found"] == 1


async def test_freeze_never_stores_error_outcome_as_blob() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=True)
    error_key = store.add_call(2, "error")

    result = await _freeze(_service(store))

    assert (result.call_count, result.entry_count, result.missing_count) == (2, 1, 1)
    assert result.coverage_status == "partial"
    (_, blobs, entries) = store.inserted[0]
    assert len(blobs) == 1
    assert error_key not in {e.key_hash for e in entries}
    assert all("prompt 2" not in b.request_json for b in blobs)


async def test_freeze_digest_uses_the_stored_blob_metadata() -> None:
    # WHY: blobs are shared across versions and the first metadata wins. The digest must follow
    # the STORED metadata, or the exporter rebuilds other bytes and never archives the version.
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=True)
    store.live[_key(1)] = LiveAnswer(json.dumps(_response(1)), json.dumps({"who": "M2"}))
    sha = blob_sha256(_request(1), _response(1))
    store.blob_metadata[sha] = json.dumps({"who": "M1"})

    result = await _freeze(_service(store))

    expected = write_entries(
        [ArchiveEntry(_key(1), 0, _request(1), _response(1), {"who": "M1"})],
        None,
        max_bytes=10**9,
    )
    assert result.archive_sha256 == expected.sha256


async def test_freeze_takes_blob_metadata_of_none_when_the_stored_blob_has_none() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=True)
    store.live[_key(1)] = LiveAnswer(json.dumps(_response(1)), json.dumps({"who": "M2"}))
    store.blob_metadata[blob_sha256(_request(1), _response(1))] = None

    result = await _freeze(_service(store))

    expected = write_entries(
        [ArchiveEntry(_key(1), 0, _request(1), _response(1), None)], None, max_bytes=10**9
    )
    assert result.archive_sha256 == expected.sha256


async def test_freeze_builds_blobs_entries_and_a_signed_receipt() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "hit", live=True)
    store.add_call(2, "bypass", inline=json.dumps(_response(2)))
    signer, stats, woken = FakeSigner(), CaptureStats(), []

    result = await _freeze(
        _service(store, signer=signer, stats=stats, on_frozen=lambda: woken.append(1))
    )

    (version, blobs, entries) = store.inserted[0]
    assert result.created is True
    assert result.version_id == version.id
    assert (version.status, version.archive_key) == ("frozen", archive_prefix(version.id))
    assert version.created_at == _NOW
    assert [(e.key_hash, e.first_ordinal) for e in entries] == [(_key(1), 0), (_key(2), 1)]
    shas = {b.sha256 for b in blobs}
    assert shas == {e.blob_sha256 for e in entries}
    first = next(b for b in blobs if b.sha256 == blob_sha256(_request(1), _response(1)))
    assert json.loads(first.request_json) == _request(1)
    assert first.request_json == canonical_material(_request(1))
    assert first.metadata_json is None
    assert first.size_bytes == len(first.request_json.encode()) + len(first.response_json.encode())
    assert signer.claims == [
        ReceiptClaims(
            sub="ada@example.org",
            vid=version.id,
            tid=_TRACE,
            sha=result.archive_sha256,
            n=2,
            c=2,
            cov="complete",
        )
    ]
    assert result.receipt == f"receipt-for-{version.id}"
    assert woken == [1]
    assert stats.freezes["created"] == 1
    assert stats.missing_total == 0


async def test_freeze_stores_live_metadata_for_hit_and_stored_calls() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "hit", live=True)
    store.live[_key(1)] = LiveAnswer(json.dumps(_response(1)), json.dumps({"tokens": 7}))

    await _freeze(_service(store))

    (_, blobs, _) = store.inserted[0]
    assert blobs[0].metadata_json == canonical_material({"tokens": 7})


_MISSING_CASES = [
    pytest.param(lambda s: s.add_call(1, "hit", live=False), id="hit-without-a-live-row"),
    pytest.param(lambda s: s.add_call(1, "stored", live=False), id="stored-without-a-live-row"),
    pytest.param(lambda s: s.add_call(1, "stored", live=True, prompt=False), id="prompt-absent"),
    pytest.param(lambda s: s.add_call(1, "bypass", inline=None), id="inline-without-a-body"),
    pytest.param(lambda s: s.add_call(1, "stored", live="{not json"), id="undecodable-live-answer"),
    pytest.param(
        lambda s: s.rows.append(CaptureRow(1, None, "bypass", None)), id="call-without-a-key"
    ),
]


@pytest.mark.parametrize("arrange", _MISSING_CASES)
async def test_a_call_that_cannot_be_copied_is_counted_as_missing(arrange: Any) -> None:
    store = FakeFreezeStore()
    arrange(store)
    stats = CaptureStats()

    result = await _freeze(_service(store, stats=stats))

    assert (result.call_count, result.entry_count, result.missing_count) == (1, 0, 1)
    assert result.coverage_status == "partial"
    assert stats.missing_total == 1


async def test_a_trace_with_every_call_missing_makes_an_empty_partial_version() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "error")

    result = await _freeze(_service(store))

    assert (result.entry_count, result.call_count, result.missing_count) == (0, 1, 1)
    assert store.inserted[0][1:] == ([], [])
    assert result.archive_sha256 == write_entries([], None, max_bytes=10**9).sha256


async def test_the_same_request_and_answer_twice_is_one_entry_and_not_missing() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "hit", live=True)
    store.add_call(1, "hit", live=True)

    result = await _freeze(_service(store))

    assert (result.call_count, result.entry_count, result.missing_count) == (2, 1, 0)
    assert result.coverage_status == "complete"


async def test_the_same_request_with_two_answers_makes_two_entries() -> None:
    # CV-D6: the replay rule (lowest first_ordinal) belongs to GW-replay. Freeze keeps both.
    store = FakeFreezeStore()
    store.add_call(1, "bypass", inline=json.dumps(_response(1)))
    store.add_call(1, "bypass", inline=json.dumps(_response(99)))

    await _freeze(_service(store))

    (_, blobs, entries) = store.inserted[0]
    assert [(e.key_hash, e.first_ordinal) for e in entries] == [(_key(1), 0), (_key(1), 1)]
    assert len(blobs) == 2


async def test_second_freeze_returns_the_same_version_without_a_write() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=True)
    signer, stats, woken = FakeSigner(), CaptureStats(), []
    service = _service(store, signer=signer, stats=stats, on_frozen=lambda: woken.append(1))
    first = await _freeze(service)

    second = await _freeze(service, subject="other@example.org")

    assert second.created is False
    assert (second.version_id, second.archive_sha256) == (first.version_id, first.archive_sha256)
    assert (second.entry_count, second.call_count, second.missing_count) == (1, 1, 0)
    assert len(store.inserted) == 1
    assert signer.claims[1].sub == "other@example.org"
    assert (signer.claims[1].vid, signer.claims[1].sha) == (first.version_id, first.archive_sha256)
    assert woken == [1], "a reused version does not wake the exporter"
    assert (stats.freezes["created"], stats.freezes["reused"]) == (1, 1)


async def test_a_lost_insert_race_returns_the_winner() -> None:
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=True)
    winner = StoredVersion(
        id=UUID("99999999-2222-4333-8444-555555555555"),
        owner_account_id=_ACCOUNT,
        trace_id=_TRACE,
        status="frozen",
        entry_count=1,
        call_count=1,
        missing_count=0,
        coverage_status="complete",
        archive_sha256="ee" * 32,
        archive_key="cache-versions/x/",
        created_at=_NOW,
    )
    store.race_winner = winner
    stats = CaptureStats()

    result = await _freeze(_service(store, stats=stats))

    assert result.created is False
    assert (result.version_id, result.archive_sha256) == (winner.id, "ee" * 32)
    assert stats.freezes["reused"] == 1


async def test_a_lost_race_with_no_winner_row_raises() -> None:
    class _RaceWithNoWinner(FakeFreezeStore):
        async def insert_version(
            self, version: StoredVersion, blobs: Sequence[NewBlob], entries: Sequence[NewEntry]
        ) -> None:
            raise VersionAlreadyExists

    store = _RaceWithNoWinner()
    store.add_call(1, "stored", live=True)

    with pytest.raises(VersionAlreadyExists):
        await _freeze(_service(store))


async def test_freeze_over_the_entry_cap_raises_and_writes_nothing() -> None:
    store = FakeFreezeStore()
    for n in range(3):
        store.add_call(n, "stored", live=True)
    stats = CaptureStats()

    with pytest.raises(CacheVersionTooLarge) as excinfo:
        await _freeze(_service(store, stats=stats, max_entries=2))

    assert excinfo.value.limit == "entries"
    assert store.inserted == []
    assert stats.freezes["too_large"] == 1


async def test_freeze_over_the_archive_cap_raises_and_writes_nothing() -> None:
    store = FakeFreezeStore()
    for n in range(3):
        store.add_call(n, "stored", live=True)

    with pytest.raises(CacheVersionTooLarge) as excinfo:
        await _freeze(_service(store, max_archive_bytes=64))

    assert excinfo.value.limit == "archive_bytes"
    assert store.inserted == []


async def test_freeze_never_logs_prompt_text_for_an_undecodable_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FakeFreezeStore()
    store.add_call(1, "stored", live="{not json")

    with caplog.at_level("DEBUG"):
        await _freeze(_service(store))

    assert "prompt 1" not in caplog.text
    assert "not json" not in caplog.text
