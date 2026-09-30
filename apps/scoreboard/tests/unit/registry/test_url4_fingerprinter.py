"""The url4 adapter of the SystemFingerprinter port.

FEATURE: OME-1307 (E14). Ids: SR-5-SB (the scoreboard half of SR-5), SR-H3-SB (adapter half),
SR-19 (adapter half), SR-E6 (adapter).

INVARIANT: the oracle is ONE frozen file, `packages/url4/tests/fixtures/fingerprint_vectors.json`.
The url4 half of SR-5 reads it in `packages/url4`; this half reads it here. The scoreboard may not
import the SDK (C11), so no single test can call both.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import url4
from url4.fingerprint import ExcludedBindingError, system_fingerprint

import scoreboard.adapters.url4_fingerprinter as adapter_module
from scoreboard.adapters.url4_fingerprinter import SDK_METADATA_BINDINGS, Url4Fingerprinter
from scoreboard.core.registry import InvalidUrl4, SystemIdentity

_VECTORS_PATH = (
    Path(__file__).resolve().parents[5] / "packages/url4/tests/fixtures/fingerprint_vectors.json"
)


def _vectors() -> dict[str, Any]:
    return json.loads(_VECTORS_PATH.read_text(encoding="utf-8"))


def _by_id() -> dict[str, dict[str, str]]:
    return {vector["id"]: vector for vector in _vectors()["vectors"]}


def test_sr5_the_vectors_file_pins_one_call_shape() -> None:
    data = _vectors()

    assert data["schema"] == "url4.fingerprint.vectors.v1"
    assert len(data["vectors"]) == 50
    assert data["binding"] == "candidate"
    # D3: the scoreboard and the url4 half use one call shape.
    assert frozenset(data["exclude_bindings"]) == SDK_METADATA_BINDINGS


@pytest.mark.parametrize("vector", _vectors()["vectors"], ids=lambda vector: vector["id"])
def test_sr5_url4_fingerprinter_matches_golden_vectors(vector: dict[str, str]) -> None:
    identity = Url4Fingerprinter().identify(vector["linked_url4"])

    assert identity.fingerprint == vector["fingerprint"]
    assert identity.candidate_url4 == vector["candidate_url4"]
    # The D3 formula, called directly: a drift in the adapter's arguments fails here.
    assert (
        system_fingerprint(
            vector["linked_url4"], binding="candidate", exclude_bindings=frozenset({"_sf_recipe"})
        )
        == vector["fingerprint"]
    )


def test_sr5_an_adapter_without_the_exclude_set_would_hash_the_recipe_blob() -> None:
    # The second RED of SR-5-SB: the ten `c08-*` and `c09-*` vectors carry the `_sf_recipe`
    # source. Without the exclude set the recipe blob is in the hash, so they would differ.
    carrying = [vector for vector in _vectors()["vectors"] if vector["id"][:3] in {"c08", "c09"}]

    assert len(carrying) == 10
    for vector in carrying:
        assert system_fingerprint(vector["linked_url4"]) != vector["fingerprint"]


def test_sr_h3_sdk_recipe_rename_is_one_identity() -> None:
    vectors = _by_id()
    adapter = Url4Fingerprinter()

    unnamed, named, other_board = (
        vectors["c08-b1"]["linked_url4"],
        vectors["c09-b1"]["linked_url4"],
        vectors["c09-b3"]["linked_url4"],
    )

    assert unnamed != named
    identity = adapter.identify(unnamed)
    assert adapter.identify(named) == identity
    assert adapter.identify(other_board) == identity
    assert "_sf_recipe" not in identity.candidate_url4


def test_the_adapter_returns_a_frozen_identity_that_hashes_its_own_text() -> None:
    import hashlib

    identity = Url4Fingerprinter().identify(_by_id()["c01-b1"]["linked_url4"])

    assert isinstance(identity, SystemIdentity)
    assert identity.fingerprint == hashlib.sha256(identity.candidate_url4.encode()).hexdigest()


def test_sr19_adapter_maps_url4_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_parse_error(*args: object, **kwargs: object) -> str:
        raise url4.ParseError("bad")

    # The adapter imported the name, so patch it there, not in `url4.fingerprint`.
    monkeypatch.setattr(adapter_module, "canonical_system_url4", raise_parse_error)

    with pytest.raises(InvalidUrl4) as info:
        Url4Fingerprinter().identify("anything")

    assert info.value.code == "invalid_url4"
    assert isinstance(info.value.__cause__, url4.ParseError)


def test_sr19_a_real_unparseable_text_is_invalid_url4() -> None:
    with pytest.raises(InvalidUrl4):
        Url4Fingerprinter().identify("(((")


def _nested(depth: int) -> str:
    # `depth` source groups around one call: far under the 32,000 character cap.
    text = "/openrouter/model($input)"
    for _ in range(depth):
        text = f"(m:0.0:{text})!'x'"
    return text


def test_sr19_a_deeply_nested_url4_is_invalid_url4_not_a_recursion_error() -> None:
    # WHY: url4 recurses on nested source groups, so a short, hostile text (about 2,400
    # characters at 200 levels) would escape as `RecursionError`. The port contract says
    # `InvalidUrl4`, so a client sees 422 and the backfill reports the row instead of aborting.
    text = _nested(200)
    assert len(text) < 32_000

    with pytest.raises(InvalidUrl4) as info:
        Url4Fingerprinter().identify(text)

    assert info.value.code == "invalid_url4"
    assert isinstance(info.value.__cause__, RecursionError)
    assert "nested too deeply" in str(info.value)
    assert "openrouter" not in str(info.value)  # the input is never echoed


_RECIPE = "_sf_recipe"


@pytest.mark.parametrize(
    "system",
    [
        # weight 1.0
        f"(a:/m()!'x', {_RECIPE}:1.0:'{{}}')!'$a'",
        # a non-text value
        f"(a:/m()!'x', {_RECIPE}:0.0:/m()!'x')!'$a'",
        # a reference to the recipe source from inside the system
        f"(a:/m()!'x', {_RECIPE}:0.0:'{{}}')!'$a $_sf_recipe'",
    ],
    ids=["weight-1", "non-text", "referenced"],
)
def test_sr_e6_non_inert_sf_recipe_maps_to_invalid_url4(system: str) -> None:
    with pytest.raises(InvalidUrl4) as info:
        Url4Fingerprinter().identify(system)

    cause = info.value.__cause__
    assert isinstance(cause, ExcludedBindingError)
    assert cause.code == "malformed_source"


def test_sr_e6_a_binding_with_no_weight_is_not_a_source_and_stays_in_the_identity() -> None:
    # As built (URL4-fp): only a weighted Source can be excluded. A plain `_sf_recipe:'...'`
    # binding is a working part of the system, so it is neither dropped nor an error.
    identity = Url4Fingerprinter().identify(f"(a:/m()!'x', {_RECIPE}:'{{}}')!'$a'")

    assert "_sf_recipe" in identity.candidate_url4


def test_sr_e6_the_sdk_form_is_a_valid_identity() -> None:
    identity = Url4Fingerprinter().identify(f"(a:/m()!'x', {_RECIPE}:0.0:'{{}}')!'$a'")

    assert "_sf_recipe" not in identity.candidate_url4
