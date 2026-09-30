"""System-name rules: SR-13 (suggestion half), SR-16, SR-17.

FEATURE: OME-1307 (E14) — erd.md §2.3.1.
"""

from __future__ import annotations

import pytest

from scoreboard.core.registry import InvalidSystemName, normalize_system_name, suggest_name

FINGERPRINT = "ab12" + "0" * 60


def test_sr13_suggestion_shape() -> None:
    assert suggest_name("opus-5.5", FINGERPRINT) == "opus-5.5-ab12"


def test_sr13_suggestion_of_a_64_char_name_is_a_valid_name_of_at_most_64_chars() -> None:
    name = "a" * 64

    suggestion = suggest_name(name, FINGERPRINT)

    assert len(suggestion) <= 64
    assert suggestion.endswith("-ab12")
    assert normalize_system_name(suggestion) == suggestion


def test_sr13_suggestion_drops_a_trailing_separator_before_the_suffix() -> None:
    # 58 letters, then '.', '_' and '-' at positions 59..61 would leave 'x.-ab12' forms.
    name = "a" * 58 + "._-" + "b"

    suggestion = suggest_name(name, FINGERPRINT)

    assert normalize_system_name(suggestion) == suggestion
    assert ".-ab12" not in suggestion and "_-ab12" not in suggestion and "--ab12" not in suggestion


@pytest.mark.parametrize(
    ("raw", "rule"),
    [
        ("", "empty"),
        ("a/b", "slash"),
        ("a" * 65, "length"),
        ("-abc", "pattern"),
        ("abc-", "pattern"),
        ("a..b.", "pattern"),
        (" opus", "pattern"),
        ("a b", "pattern"),
    ],
)
def test_sr16_name_rules_boundaries_reject(raw: str, rule: str) -> None:
    with pytest.raises(InvalidSystemName) as info:
        normalize_system_name(raw)

    assert info.value.rule == rule
    assert info.value.code == "invalid_system_name"
    assert info.value.message


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a", "a"),
        ("a" * 64, "a" * 64),
        ("Opus-5.5", "opus-5.5"),
        ("kevins-best", "kevins-best"),
        ("a.b_c-d", "a.b_c-d"),
        ("0", "0"),
    ],
)
def test_sr16_name_rules_boundaries_accept(raw: str, expected: str) -> None:
    assert normalize_system_name(raw) == expected


def test_sr16_the_empty_rule_wins_over_every_other_rule() -> None:
    with pytest.raises(InvalidSystemName) as info:
        normalize_system_name("")

    assert info.value.rule == "empty"


def test_sr16_the_length_rule_runs_before_the_slash_rule() -> None:
    with pytest.raises(InvalidSystemName) as info:
        normalize_system_name("a/" * 40)

    assert info.value.rule == "length"


@pytest.mark.parametrize(
    "raw",
    [
        "opus-5.5\u00e9",
        "\u043epus",  # Cyrillic o
        "\u212aevins-best",  # KELVIN SIGN: lower() would turn it into ASCII 'k'
    ],
)
def test_sr17_non_ascii_name_rejected(raw: str) -> None:
    with pytest.raises(InvalidSystemName) as info:
        normalize_system_name(raw)

    assert info.value.rule == "ascii"
