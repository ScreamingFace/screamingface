"""E5 P1 spec D6: the owner key never merges two different people.

FEATURE: first-class Runs (OME-1785). INVARIANT: the key is the only check on every Run read and
write. It lowercases as aigateway's account key does, never case-folds: folding would give
distinct addresses one owner.
"""

from __future__ import annotations

import pytest

from screamingface_engine.runs.records import owner_key


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("finance@corp.org", "ﬁnance@corp.org"),  # the "fi" ligature
        ("strasse@corp.org", "straße@corp.org"),
        ("sam@corp.org", "ſam@corp.org"),  # the long s
        ("victim@strasse.de", "victim@straße.de"),  # two registrable IDN domains
    ],
)
def test_addresses_that_unicode_folding_merges_are_two_owners(one: str, other: str) -> None:
    assert owner_key(one) != owner_key(other)


def test_ascii_case_and_surrounding_space_are_one_owner() -> None:
    assert owner_key(" Alice@Example.ORG\n") == owner_key("alice@example.org")


def test_a_non_ascii_letter_lowercases_too() -> None:
    assert owner_key("Ärzte@x.org") == owner_key("ärzte@x.org")


def test_the_kelvin_sign_lowercases_to_k_only_as_text() -> None:
    """WHY: `str.lower()` maps the Kelvin sign to "k", as in aigateway's account key. Over HTTP
    the edge's UTF-8 bytes arrive as Latin-1 text, which lowercases to no ASCII letter, so a
    request never reaches this merge (the `/runs` route test pins that)."""
    assert owner_key("\u212aim@corp.org") == owner_key("kim@corp.org")
