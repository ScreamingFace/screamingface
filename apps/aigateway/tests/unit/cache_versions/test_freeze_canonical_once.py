"""The freeze parses and canonicalises each part of a call at most once (OME-1307, E14).

FEATURE: OME-1307 (E14) - a stored prompt IS the canonical key material, so `sha256(prompt) ==
key_hash` proves it canonical and the freeze copies it as is. The response and the metadata are not
canonical, so each is parsed and rendered once.
INVARIANT: a prompt is NEVER trusted without that check: a prompt that fails it takes the old
parse-and-render path and gives the same bytes as before.
"""

from __future__ import annotations

import hashlib
import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from aigateway.core.cache_versions import freeze as freeze_module
from aigateway.core.cache_versions.archive import (
    CanonicalEntry,
    blob_digest,
    write_canonical,
    write_entries,
)
from aigateway.core.cache_versions.ports import ArchiveEntry, CaptureRow, LiveAnswer
from aigateway.core.request_cache.canonical import canonical_material
from tests.unit.cache_versions.test_freeze_service import (
    FakeFreezeStore,
    _freeze,
    _key,
    _request,
    _response,
    _service,
)

pytestmark = pytest.mark.asyncio

_RESPONSE_TEXT = '{"choices": [{"message": {"content": "café"}}]}'
_METADATA_TEXT = '{"who": "Mé", "n": 1.0}'


class _Spies:
    """Records what the freeze module parses (``json.loads``) and canonicalises."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.parsed: list[str] = []
        self.rendered: list[Any] = []
        real_material = freeze_module.canonical_material

        def loads(text: str, *args: Any, **kwargs: Any) -> Any:
            self.parsed.append(text)
            return json.loads(text, *args, **kwargs)

        def material(value: Any) -> str:
            self.rendered.append(value)
            return real_material(value)

        monkeypatch.setattr(freeze_module, "json", SimpleNamespace(loads=loads))
        monkeypatch.setattr(freeze_module, "canonical_material", material)


def _add_sha_keyed_call(
    store: FakeFreezeStore, n: int, *, response: str = _RESPONSE_TEXT, metadata: str | None = None
) -> tuple[str, str]:
    """A live `stored` call whose prompt is the canonical material and whose key is its sha256."""
    prompt = canonical_material(_request(n))
    key = hashlib.sha256(prompt.encode()).hexdigest()
    store.rows.append(CaptureRow(len(store.rows) + 100, key, "stored", None))
    store.prompts[key] = prompt
    store.live[key] = LiveAnswer(response, metadata)
    return key, prompt


async def test_a_sha_keyed_prompt_is_never_parsed_and_the_rest_is_canonicalised_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeFreezeStore()
    key, prompt = _add_sha_keyed_call(store, 1, metadata=_METADATA_TEXT)
    spies = _Spies(monkeypatch)

    result = await _freeze(_service(store))

    assert spies.parsed == [_RESPONSE_TEXT, _METADATA_TEXT]
    assert spies.rendered == [json.loads(_RESPONSE_TEXT), json.loads(_METADATA_TEXT)]
    (_, blobs, entries) = store.inserted[0]
    (blob,) = blobs
    assert blob.request_json == prompt
    assert blob.response_json == canonical_material(json.loads(_RESPONSE_TEXT))
    assert blob.metadata_json == canonical_material(json.loads(_METADATA_TEXT))
    assert blob.size_bytes == len(blob.request_json.encode()) + len(blob.response_json.encode())
    assert [(e.key_hash, e.blob_sha256) for e in entries] == [(key, blob.sha256)]
    expected = write_entries(
        [
            ArchiveEntry(
                key,
                0,
                json.loads(prompt),
                json.loads(_RESPONSE_TEXT),
                json.loads(_METADATA_TEXT),
            )
        ],
        None,
        max_bytes=10**9,
    )
    assert result.archive_sha256 == expected.sha256


async def test_a_call_with_no_metadata_canonicalises_the_response_once_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeFreezeStore()
    _add_sha_keyed_call(store, 1)
    spies = _Spies(monkeypatch)

    await _freeze(_service(store))

    assert spies.parsed == [_RESPONSE_TEXT]
    assert len(spies.rendered) == 1


async def test_stored_metadata_that_equals_the_entry_metadata_is_not_parsed_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeFreezeStore()
    _, prompt = _add_sha_keyed_call(store, 1, metadata=_METADATA_TEXT)
    canonical_response = canonical_material(json.loads(_RESPONSE_TEXT))
    store.blob_metadata[blob_digest(prompt, canonical_response)] = canonical_material(
        json.loads(_METADATA_TEXT)
    )
    spies = _Spies(monkeypatch)

    await _freeze(_service(store))

    assert spies.parsed == [_RESPONSE_TEXT, _METADATA_TEXT]
    assert len(spies.rendered) == 2


async def test_stored_metadata_that_differs_is_parsed_and_rendered_not_spliced() -> None:
    store = FakeFreezeStore()
    key, prompt = _add_sha_keyed_call(store, 1, metadata=_METADATA_TEXT)
    canonical_response = canonical_material(json.loads(_RESPONSE_TEXT))
    store.blob_metadata[blob_digest(prompt, canonical_response)] = '{"who": "M1" , "z": [1.0]}'

    result = await _freeze(_service(store))

    (_, blobs, _) = store.inserted[0]
    assert blobs[0].metadata_json == '{"who":"M1","z":[1.0]}'
    expected = write_entries(
        [
            ArchiveEntry(
                key, 0, json.loads(prompt), json.loads(_RESPONSE_TEXT), {"who": "M1", "z": [1.0]}
            )
        ],
        None,
        max_bytes=10**9,
    )
    assert result.archive_sha256 == expected.sha256


async def test_a_prompt_that_fails_the_sha_check_is_parsed_and_rendered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeFreezeStore()
    non_canonical = '{"b":1, "a":2}'
    store.rows.append(CaptureRow(100, _key(1), "stored", None))
    store.prompts[_key(1)] = non_canonical
    store.live[_key(1)] = LiveAnswer(_RESPONSE_TEXT, None)
    spies = _Spies(monkeypatch)

    await _freeze(_service(store))

    assert spies.parsed == [non_canonical, _RESPONSE_TEXT]
    assert spies.rendered[0] == {"b": 1, "a": 2}
    (_, blobs, _) = store.inserted[0]
    assert blobs[0].request_json == '{"a":2,"b":1}'


async def test_a_canonical_prompt_under_a_foreign_key_is_not_trusted_as_is() -> None:
    # The sha check is the only proof. The same canonical text under a non-sha key takes the
    # fallback and still gives the canonical bytes (here they are equal), never a skipped check.
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=True)

    await _freeze(_service(store))

    (_, blobs, _) = store.inserted[0]
    assert blobs[0].request_json == canonical_material(_request(1))
    assert blobs[0].response_json == canonical_material(_response(1))


async def test_a_response_with_a_nan_literal_counts_as_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=True)
    store.add_call(2, "stored", live='{"x": NaN, "secret": "PROMPT-TEXT"}')

    with caplog.at_level(logging.WARNING, logger=freeze_module.logger.name):
        result = await _freeze(_service(store))

    assert (result.call_count, result.entry_count, result.missing_count) == (2, 1, 1)
    assert result.coverage_status == "partial"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert _key(2)[:12] in warnings[0]
    assert "PROMPT-TEXT" not in warnings[0]


@pytest.mark.parametrize(
    "response",
    ['{"x": ', '"\\ud800"', "[1e999]"],
    ids=["truncated", "lone-surrogate", "infinity"],
)
async def test_an_undecodable_or_unencodable_response_counts_as_missing(response: str) -> None:
    store = FakeFreezeStore()
    store.add_call(1, "stored", live=response)

    result = await _freeze(_service(store))

    assert (result.entry_count, result.missing_count) == (0, 1)


async def test_a_prompt_with_a_lone_surrogate_counts_as_missing() -> None:
    store = FakeFreezeStore()
    store.rows.append(CaptureRow(100, _key(1), "stored", None))
    store.prompts[_key(1)] = '{"m": "\ud800"}'
    store.live[_key(1)] = LiveAnswer(_RESPONSE_TEXT, None)

    result = await _freeze(_service(store))

    assert (result.entry_count, result.missing_count) == (0, 1)


async def test_the_freeze_digest_equals_the_writer_over_the_texts_it_stored() -> None:
    store = FakeFreezeStore()
    _add_sha_keyed_call(store, 1, metadata=_METADATA_TEXT)
    _add_sha_keyed_call(store, 2)

    result = await _freeze(_service(store))

    (_, blobs, entries) = store.inserted[0]
    by_sha = {b.sha256: b for b in blobs}
    rebuilt = write_canonical(
        [
            CanonicalEntry(
                e.key_hash,
                e.first_ordinal,
                by_sha[e.blob_sha256].request_json,
                by_sha[e.blob_sha256].response_json,
                by_sha[e.blob_sha256].metadata_json,
            )
            for e in entries
        ],
        None,
        max_bytes=10**9,
    )
    assert result.archive_sha256 == rebuilt.sha256
