"""FEATURE memory fix 3 (OME-1835), unit 2: read_text returns the exact parked text.

INVARIANT under test: the text a parked Case returns is the exact compact JSON it was parked
as, so the parked Candidate Result body can write a Case verbatim. A key that does not resolve
fails closed with the typed ``CaseResultStoreError``, exactly as ``read`` does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.case_result_store import (
    CaseResultStore,
    CaseResultStoreError,
)


def test_read_text_returns_the_exact_compact_json(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    record = {"b": 1, "a": "é → 😀", "n": float("nan"), "l": [1, None, True]}
    key = store.append(record)
    assert store.read_text(key) == json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    store.close()


def test_read_is_read_text_decoded(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    record = {"x": [1, 2], "y": "z"}
    key = store.append(record)
    assert store.read(key) == json.loads(store.read_text(key)) == record
    store.close()


def test_read_text_of_an_unknown_key_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    store.append({"a": 1})
    with pytest.raises(CaseResultStoreError):
        store.read_text("99")
    store.close()


def test_read_text_of_a_tampered_row_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"answer": "B"})
    data = store.path.read_bytes()
    store.path.write_bytes(data.replace(b'"B"', b'"C"'))
    with pytest.raises(CaseResultStoreError, match="corrupt"):
        store.read_text(key)
    store.close()


def test_read_text_after_close_fails_closed(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"a": 1})
    store.close()
    with pytest.raises(CaseResultStoreError):
        store.read_text(key)


def test_two_reads_give_the_same_text(tmp_path: Path) -> None:
    store = CaseResultStore.create(tmp_path)
    key = store.append({"a": [1, "é"]})
    assert store.read_text(key) == store.read_text(key)
    store.close()
