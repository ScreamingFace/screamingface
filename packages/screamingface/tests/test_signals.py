"""sf.signal: a named number on a member Answer (OME-1289 gap, SG#4 and BU#8)."""

from __future__ import annotations

from typing import Any

import pytest

import screamingface as sf
from screamingface._signals import is_signal_key


@pytest.mark.parametrize(
    "key",
    ["cost_usd", "score:judge", "field:a.b[0]"],
)
def test_signal_key_in_the_e4a_set_is_accepted(key: str) -> None:
    value = sf.signal(key)

    assert value.key == key
    assert is_signal_key(key)
    assert repr(value) == f"signal({key!r})"


def test_signal_key_outside_e4a_set_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="E4b") as declared:
        sf.signal("logprob_mean")
    assert "cost_usd" in str(declared.value)
    with pytest.raises(ValueError, match="JSON path"):
        sf.signal("field:a..b")
    with pytest.raises(ValueError, match="JSON path"):
        sf.signal("field:")
    for bad in ("", "Cost_usd"):
        with pytest.raises(ValueError, match="E4b"):
            sf.signal(bad)
    for not_text in (3, None, b"cost_usd"):
        with pytest.raises(TypeError):
            sf.signal(not_text)  # type: ignore[arg-type]


def test_signal_value_equality_hash_and_python_round_trip() -> None:
    value = sf.signal("field:a.b")

    assert value == sf.signal("field:a.b")
    assert value != sf.signal("field:a")
    assert hash(value) == hash(sf.signal("field:a.b"))
    assert eval(value._python(), {"sf": sf}) == value  # noqa: S307
    assert value._python() == "sf.signal('field:a.b')"


def test_budget_remaining_is_not_an_answer_signal() -> None:
    with pytest.raises(ValueError, match="E4c"):
        sf.signal("budget.remaining")


def test_a_signal_is_not_a_plain_string_key() -> None:
    value: Any = sf.signal("cost_usd")

    with pytest.raises(AttributeError):
        value.key = "tokens_in"
