"""CV-20 and support: the version lookup adapter, on a real (SQLite) database.

FEATURE: OME-1307 (E14) - replay finds one call in a frozen version by its key hash.
INVARIANT (CV-D6, RP-D5): when a key repeats in a version, the LOWEST first_ordinal wins, so a
replay of a repeated call always gets the same answer (the first one the original run saw).
INVARIANT (CV-D10): the blob body is model output. The lookup returns it as data and logs none
of it.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID, uuid4

import pytest

from aigateway.core.cache_versions.lookup import TortoiseCacheVersionLookup
from aigateway.core.cache_versions.models import CacheVersion, CacheVersionBlob, CacheVersionEntry
from aigateway.core.cache_versions.ports import VersionHit

_KEY = "ab" * 32
_OTHER_KEY = "cd" * 32


async def _version() -> UUID:
    version = await CacheVersion.create(
        owner_account_id="acct-1",
        trace_id=uuid4().hex,
        entry_count=1,
        call_count=1,
        missing_count=0,
        coverage_status="complete",
        archive_sha256="0" * 64,
        archive_key="k",
    )
    return version.id


async def _entry(
    version: UUID,
    key: str,
    sha: str,
    ordinal: int,
    *,
    response: str,
    metadata: str | None = None,
) -> None:
    blob, _ = await CacheVersionBlob.get_or_create(
        sha256=sha,
        defaults={
            "request_json": "{}",
            "response_json": response,
            "metadata_json": metadata,
            "size_bytes": len(response),
        },
    )
    await CacheVersionEntry.create(
        version_id=version, key_hash=key, blob_id=blob.sha256, first_ordinal=ordinal
    )


def _run(client: Any, fn: Any) -> Any:
    return client.portal.call(fn)


def test_duplicate_key_replay_returns_lowest_ordinal(client: Any) -> None:
    async def scenario() -> VersionHit | None:
        version = await _version()
        # A was seen at position 3, B at position 0. The blob hashes are ordered the other way, so a
        # `blob_id` order alone would pick A.
        await _entry(version, _KEY, "aa" * 32, 3, response='{"answer":"A"}')
        await _entry(version, _KEY, "bb" * 32, 0, response='{"answer":"B"}')
        return await TortoiseCacheVersionLookup().find(version, _KEY)

    hit = _run(client, scenario)

    assert hit is not None
    assert hit.response == {"answer": "B"}


def test_equal_first_ordinal_breaks_the_tie_by_blob_id(client: Any) -> None:
    async def scenario() -> VersionHit | None:
        version = await _version()
        await _entry(version, _KEY, "bb" * 32, 2, response='{"answer":"B"}')
        await _entry(version, _KEY, "aa" * 32, 2, response='{"answer":"A"}')
        return await TortoiseCacheVersionLookup().find(version, _KEY)

    hit = _run(client, scenario)

    assert hit is not None
    assert hit.response == {"answer": "A"}


def test_find_returns_none_for_another_version(client: Any) -> None:
    async def scenario() -> tuple[VersionHit | None, VersionHit | None]:
        version, other = await _version(), await _version()
        await _entry(version, _KEY, "aa" * 32, 0, response='{"answer":"A"}')
        lookup = TortoiseCacheVersionLookup()
        return await lookup.find(other, _KEY), await lookup.find(version, _OTHER_KEY)

    other_version, other_key = _run(client, scenario)

    assert other_version is None
    assert other_key is None


def test_find_returns_the_metadata_block_as_stored(client: Any) -> None:
    metadata = json.dumps({"schema": "aigw.cache_entry_metadata"})

    async def scenario() -> tuple[VersionHit | None, VersionHit | None]:
        version = await _version()
        await _entry(version, _KEY, "aa" * 32, 0, response='{"a":1}', metadata=metadata)
        await _entry(version, _OTHER_KEY, "bb" * 32, 1, response='{"b":2}')
        lookup = TortoiseCacheVersionLookup()
        return await lookup.find(version, _KEY), await lookup.find(version, _OTHER_KEY)

    with_metadata, without = _run(client, scenario)

    assert with_metadata is not None and with_metadata.metadata_json == metadata
    assert without is not None and without.metadata_json is None


@pytest.mark.parametrize("body", ["[1, 2]", '"text"', "7", "null"])
def test_a_blob_that_is_not_an_object_is_a_miss_and_is_not_logged(
    client: Any, caplog: pytest.LogCaptureFixture, body: str
) -> None:
    async def scenario() -> VersionHit | None:
        version = await _version()
        await _entry(version, _KEY, "aa" * 32, 0, response=body)
        return await TortoiseCacheVersionLookup().find(version, _KEY)

    with caplog.at_level(logging.WARNING, logger="aigateway.core.cache_versions.lookup"):
        hit = _run(client, scenario)

    assert hit is None
    assert _KEY[:12] in caplog.text
    assert _KEY not in caplog.text, "only a key prefix is logged"
    assert body not in caplog.text


def test_version_exists(client: Any) -> None:
    async def scenario() -> tuple[bool, bool]:
        version = await _version()
        lookup = TortoiseCacheVersionLookup()
        return await lookup.version_exists(version), await lookup.version_exists(uuid4())

    assert _run(client, scenario) == (True, False)
