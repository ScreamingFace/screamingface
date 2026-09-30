"""SR-5 (the url4 half): the frozen golden vectors of the system fingerprint.

STORY: as a maintainer of three consumers (this package, the scoreboard and the SDK) I want one
frozen oracle, so that a change that moves a fingerprint fails a test before it moves the
leaderboard.

# AIDEV-NOTE: the scoreboard half (SR-5-SB) and the SDK half read this SAME file by repository
# path (packages/url4/tests/fixtures/fingerprint_vectors.json), and pass the same
# `exclude_bindings` that the file records. Do not regenerate the file to make a test pass.
# INVARIANT: the two fixture guards do not call the code under test. They stop a bad edit of
# the file itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from url4 import build, render
from url4.fingerprint import canonical_system_url4, system_fingerprint

_DATA: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "fingerprint_vectors.json").read_text(
        encoding="utf-8"
    )
)
BINDING: str = _DATA["binding"]
EXCLUDE = frozenset(_DATA["exclude_bindings"])
VECTORS: list[dict[str, str]] = _DATA["vectors"]


def test_vectors_file_has_fifty_unique_entries() -> None:
    assert len(VECTORS) == 50
    assert len({v["id"] for v in VECTORS}) == 50
    assert len({v["linked_url4"] for v in VECTORS}) == 50
    assert _DATA["schema"] == "url4.fingerprint.vectors.v1"
    assert BINDING == "candidate"
    assert _DATA["exclude_bindings"] == ["_sf_recipe"]


def test_vectors_match_their_independent_oracle() -> None:
    for v in VECTORS:
        assert render(build(v["candidate_url4"])) == v["candidate_url4"], v["id"]
        assert "_sf_recipe" not in v["candidate_url4"], v["id"]
        digest = hashlib.sha256(v["candidate_url4"].encode("utf-8")).hexdigest()
        assert digest == v["fingerprint"], v["id"]


def test_vectors_hold_the_sr_h3_twin() -> None:
    by_id = {v["id"]: v for v in VECTORS}
    for j in range(1, 6):
        first, second = by_id[f"c08-b{j}"], by_id[f"c09-b{j}"]
        assert first["linked_url4"] != second["linked_url4"]
        assert first["fingerprint"] == second["fingerprint"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_fingerprint_parity_sdk_and_scoreboard(vector: dict[str, str]) -> None:
    linked = vector["linked_url4"]
    assert system_fingerprint(linked, BINDING, exclude_bindings=EXCLUDE) == vector["fingerprint"]
    assert (
        canonical_system_url4(linked, BINDING, exclude_bindings=EXCLUDE) == vector["candidate_url4"]
    )
