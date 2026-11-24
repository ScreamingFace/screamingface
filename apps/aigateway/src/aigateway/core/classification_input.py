"""The two inputs a classification takes, the label rule, and `classifier-limits-v1` (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — `POST /v1/classifications` takes either a text or a
# `classification-choice-input-v1` object; a classifier declares which it accepts and the limits
# it holds, and the route refuses anything else before a key is read or a byte is sent upstream.
# INVARIANT: pure; no provider, no I/O. The route and every plugin read the same rules here, so
# the options a caller may send and the labels an answer may return obey one definition.
# INVARIANT: a refusal derived from these checks names a rule or a limit key, never a value.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

TEXT_INPUT = "text"
CHOICE_INPUT = "choice"
CHOICE_INPUT_CONTRACT = "classification-choice-input-v1"
LIMITS_CONTRACT = "classifier-limits-v1"
TEXT_LIMIT_KEYS = ("max_labels", "max_label_bytes", "max_text_chars")
CHOICE_LIMIT_KEYS = (
    *TEXT_LIMIT_KEYS,
    "max_options",
    "max_description_chars",
    "max_instructions_chars",
)
_CHOICE_KEYS = frozenset({"contract", "text", "instructions", "options"})
_OPTION_KEYS = frozenset({"label", "description"})


def is_label(value: object, *, max_bytes: int | None = None) -> bool:
    """A nonempty label of valid Unicode with no control character, within ``max_bytes``.

    # WHY the whole `C` category: the SDK refuses a label with any control, format, surrogate,
    # private-use or unassigned character (`recipe._checked_text`), so the Gateway admits no
    # label the SDK could not have written.
    """
    if not isinstance(value, str) or not value:
        return False
    if any(unicodedata.category(char).startswith("C") for char in value):
        return False
    # INVARIANT: the encode cannot fail here; a lone surrogate is category `Cs`, refused above.
    return max_bytes is None or len(value.encode("utf-8")) <= max_bytes


def parse_choice_input(value: object) -> dict[str, Any] | None:
    """The validated choice input, or None when the object breaks the contract's shape."""
    if not isinstance(value, dict) or value.keys() != _CHOICE_KEYS:
        return None
    if value["contract"] != CHOICE_INPUT_CONTRACT:
        return None
    text, instructions, options = value["text"], value["instructions"], value["options"]
    if not (_is_text(text) and _is_text(instructions) and instructions):
        return None
    if not isinstance(options, list) or not options or not all(map(_is_option, options)):
        return None
    labels = [option["label"] for option in options]
    if len(set(labels)) != len(labels):
        return None
    return value


def first_exceeded_limit(value: str | Mapping[str, Any], limits: Mapping[str, Any]) -> str | None:
    """The first limit key the input breaks, in the C7 order, or None when it fits.

    # INVARIANT: the order is `max_text_chars`, `max_options`, `max_label_bytes`,
    # `max_description_chars`, `max_instructions_chars`; a text input meets only the first.
    """
    if isinstance(value, str):
        return "max_text_chars" if len(value) > limits["max_text_chars"] else None
    options = value["options"]
    checks = (
        ("max_text_chars", len(value["text"])),
        ("max_options", len(options)),
        ("max_label_bytes", max(len(o["label"].encode("utf-8")) for o in options)),
        ("max_description_chars", max(len(o["description"]) for o in options)),
        ("max_instructions_chars", len(value["instructions"])),
    )
    return next((key for key, size in checks if size > limits[key]), None)


def _is_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_option(option: object) -> bool:
    return (
        isinstance(option, dict)
        and option.keys() == _OPTION_KEYS
        and is_label(option["label"])
        and _is_text(option["description"])
        and bool(option["description"])
    )
