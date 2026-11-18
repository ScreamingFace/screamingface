"""The helpers that the chat records share: the refusal names and the JSON reader."""

from __future__ import annotations

import pytest

from screamingface_engine.chat._codec import json_object, shown


class _Error(ValueError):
    """A stand-in for a record error."""


def test_shown_quotes_a_name_and_names_other_values_by_type() -> None:
    assert shown("screamingface.chat-input.v2") == "'screamingface.chat-input.v2'"
    assert shown(None) == "<NoneType>"
    assert shown("x" * 65) == "<str>"
    assert shown({"a": 1}) == "<dict>"


def test_json_object_returns_the_object() -> None:
    assert json_object(b'{"a": 1}', ValueError, "the record") == {"a": 1}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\xff", "the record is not UTF-8 JSON"),
        (b"[1]", "the record is not a JSON object"),
        (b"nope", "the record is not UTF-8 JSON"),
    ],
)
def test_json_object_refuses_what_is_not_a_json_object(data: bytes, message: str) -> None:
    with pytest.raises(_Error) as info:
        json_object(data, _Error, "the record")
    assert str(info.value) == message
