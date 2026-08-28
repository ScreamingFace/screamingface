"""Spec §2.4's caps table, row by row.

The split the tests protect is the spec's: only the total body cap and *structural* violations
reject a report. Everything else is truncate-and-mark, because a truncated report is worth more
than no report — and the inverse mistake, rejecting a 300-byte `client.version`, is the one that
makes a client unable to file a bug at all.
"""

from __future__ import annotations

import json
from typing import Any

from report_intake.reports.caps import (
    CLIENT_CONTEXT_STRING_BYTES,
    ERROR_CAUSE_BYTES,
    ERROR_DETAILS_BYTES,
    ERROR_MESSAGE_BYTES,
    ERROR_NOTES_ITEMS,
    ERROR_TRACEBACK_BYTES,
    MAX_DEPTH,
    MAX_KEYS_PER_NODE,
    NOTE_BYTES,
    TRUNCATED_DETAILS_KEY,
    USER_AGENT_BYTES,
    apply_caps,
    strip_control_characters,
    structural_violation,
)


def _nested(depth: int) -> dict[str, Any]:
    node: dict[str, Any] = {"leaf": 1}
    for _ in range(depth - 1):
        node = {"down": node}
    return node


def test_a_report_within_every_cap_comes_back_untouched() -> None:
    """The truncator has to be a no-op on ordinary reports, or every field carries a marker
    nobody asked for."""
    document = {"note": "short", "error": {"message": "boom", "notes": ["a", "b"]}}

    capped, truncations = apply_caps(document)

    assert capped == document
    assert truncations == ()


def test_a_note_over_its_cap_is_truncated_and_marked() -> None:
    capped, truncations = apply_caps({"note": "n" * (NOTE_BYTES * 2)})

    assert len(capped["note"].encode("utf-8")) <= NOTE_BYTES
    assert "truncated" in capped["note"]
    assert truncations[0].pointer == "/note"
    assert truncations[0].original == NOTE_BYTES * 2


def test_an_error_message_over_its_cap_is_truncated_rather_than_rejected() -> None:
    """`error.message` is carried verbatim precisely because the close code and elapsed seconds
    live only inside it — so an oversized one is cut, never dropped."""
    capped, _ = apply_caps({"error": {"message": "m" * (ERROR_MESSAGE_BYTES + 10)}})

    message = capped["error"]["message"]
    assert message.startswith("mmm")
    assert len(message.encode("utf-8")) <= ERROR_MESSAGE_BYTES


def test_an_oversized_traceback_keeps_its_head_and_its_tail() -> None:
    """CPython renders the innermost frame last and V8's `Error.stack` renders it first, so a
    truncator that keeps one end has to know which runtime produced the string."""
    traceback = "HEAD" + ("f" * ERROR_TRACEBACK_BYTES) + "TAIL"

    capped, truncations = apply_caps({"error": {"traceback": traceback}})

    kept = capped["error"]["traceback"]
    assert kept.startswith("HEAD")
    assert kept.endswith("TAIL")
    assert len(kept.encode("utf-8")) <= ERROR_TRACEBACK_BYTES
    assert truncations[0].pointer == "/error/traceback"


def test_a_traceback_under_its_cap_keeps_every_frame() -> None:
    """The head-and-tail truncator has its own early exit, and a marker appearing in the middle
    of a 40-line traceback that fitted fine is a bug report about report-intake."""
    traceback = 'Traceback (most recent call last):\n  File "x.py", line 1\nBoom: gone'

    capped, truncations = apply_caps({"error": {"traceback": traceback}})

    assert capped["error"]["traceback"] == traceback
    assert truncations == ()


def _serialized_size(node: object) -> int:
    """What the capped node actually costs once it is JSON again — which is the only measurement
    `ERROR_DETAILS_BYTES` is stated in, and the one the truncator has to hit."""
    return len(json.dumps(node, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_an_oversized_details_object_is_kept_as_a_truncated_serialization() -> None:
    """There is no way to cut a JSON *object* to a byte budget and have it still parse, and
    replacing it with a bare marker would discard everything a triager needs."""
    details = {f"key_{index}": "v" * 200 for index in range(MAX_KEYS_PER_NODE)}

    capped, truncations = apply_caps({"error": {"details": details}})

    assert set(capped["error"]["details"]) == {TRUNCATED_DETAILS_KEY}
    assert capped["error"]["details"][TRUNCATED_DETAILS_KEY].startswith('{"key_0"')
    assert truncations[0].pointer == "/error/details"
    assert _serialized_size(capped["error"]["details"]) <= ERROR_DETAILS_BYTES


def test_a_details_object_of_escapes_still_lands_under_its_cap() -> None:
    """The whole reason the truncator budgets against the WRAPPER. What is kept becomes a JSON
    string under one key, so every `"` and `\\` in it re-escapes to two bytes on the way back
    out — budgeting against the input left this object 2.6 KiB over an 8 KiB cap, which is the
    one thing §2.4's row is about."""
    details = {f"key_{index}": 'v"\\' * 70 for index in range(MAX_KEYS_PER_NODE)}

    capped, _ = apply_caps({"error": {"details": details}})

    assert _serialized_size(capped["error"]["details"]) <= ERROR_DETAILS_BYTES


def test_a_details_object_under_its_cap_keeps_its_structure() -> None:
    capped, truncations = apply_caps({"error": {"details": {"code": 1011, "reason": "gone"}}})

    assert capped["error"]["details"] == {"code": 1011, "reason": "gone"}
    assert truncations == ()


def test_details_smaller_than_its_cap_is_measured_by_its_serialization() -> None:
    """The cap is on the JSON, not on a key count: a single 9 KiB value is over it."""
    capped, _ = apply_caps({"error": {"details": {"body": "b" * (ERROR_DETAILS_BYTES + 1)}}})

    assert set(capped["error"]["details"]) == {TRUNCATED_DETAILS_KEY}
    assert _serialized_size(capped["error"]["details"]) <= ERROR_DETAILS_BYTES


def test_an_error_cause_is_bounded_like_its_sibling_details() -> None:
    """§2.4's table gives `details` a row and `cause` none, which left the other arbitrary-JSON
    node in the report with no bound at all: fifty marker-free string leaves is ~48 KiB inside a
    64 KiB body, and every byte of it was committed to the `payload` column."""
    cause = {f"k{index}": "marker free diagnostic prose " * 33 for index in range(50)}

    capped, truncations = apply_caps({"error": {"cause": cause}})

    assert set(capped["error"]["cause"]) == {TRUNCATED_DETAILS_KEY}
    assert _serialized_size(capped["error"]["cause"]) <= ERROR_CAUSE_BYTES
    assert truncations[0].pointer == "/error/cause"


def test_the_documented_cause_shape_is_kept_exactly_as_it_arrived() -> None:
    """Spec §2.1's own example: `{"type": "ws", "rcvd": {"code": 1011, "reason": ...}}`. Bounding
    `cause` must not reshape the shape the spec documents when it fits."""
    cause = {"type": "ws", "rcvd": {"code": 1011, "reason": "going away"}}

    capped, truncations = apply_caps({"error": {"cause": cause}})

    assert capped["error"]["cause"] == cause
    assert truncations == ()


def test_excess_notes_are_dropped_and_the_drop_is_recorded() -> None:
    """The mark is out of band here, not in the list: a seventeenth item carrying "and 4 more"
    would break the very cap that produced it."""
    capped, truncations = apply_caps({"error": {"notes": [str(n) for n in range(20)]}})

    assert capped["error"]["notes"] == [str(n) for n in range(ERROR_NOTES_ITEMS)]
    assert truncations[0].pointer == "/error/notes"
    assert (truncations[0].kept, truncations[0].original, truncations[0].unit) == (16, 20, "items")


def test_a_client_string_over_256_bytes_is_truncated_not_rejected() -> None:
    """Directly the §2.4 row that a classification-shaped rule would get wrong: an oversized
    `client.version` is triage metadata, not a reason to refuse the report."""
    capped, truncations = apply_caps({"client": {"version": "v" * 900}})

    assert len(capped["client"]["version"].encode("utf-8")) <= CLIENT_CONTEXT_STRING_BYTES
    assert truncations[0].pointer == "/client/version"


def test_an_unknown_client_key_is_capped_like_any_other_client_string() -> None:
    """`client` is an extension point, so its unknown keys are preserved — but preserved is not
    unbounded."""
    capped, _ = apply_caps({"client": {"electron_version": "e" * 900}})

    assert len(capped["client"]["electron_version"].encode("utf-8")) <= CLIENT_CONTEXT_STRING_BYTES


def test_the_user_agent_gets_its_own_larger_cap() -> None:
    """A real user agent is longer than 256 bytes, so the general `client` cap would mangle
    every browser report."""
    capped, _ = apply_caps({"client": {"user_agent": "u" * (USER_AGENT_BYTES * 2)}})

    kept = len(capped["client"]["user_agent"].encode("utf-8"))
    assert CLIENT_CONTEXT_STRING_BYTES < kept <= USER_AGENT_BYTES


def test_strings_nested_inside_context_are_capped_too() -> None:
    capped, truncations = apply_caps({"context": {"candidate": {"models": ["m" * 900]}}})

    assert len(capped["context"]["candidate"]["models"][0].encode("utf-8")) <= 256
    assert truncations[0].pointer == "/context/candidate/models/0"


def test_notes_entries_are_not_capped_as_client_strings() -> None:
    """`/error/notes/0` starts with neither `/client/` nor `/context/`; the caps table gives it
    no per-item byte limit, and inventing one here would be spec drift."""
    capped, truncations = apply_caps({"error": {"notes": ["n" * 900]}})

    assert capped["error"]["notes"] == ["n" * 900]
    assert truncations == ()


def test_a_multibyte_string_is_cut_on_a_character_boundary() -> None:
    """Slicing encoded bytes can land mid-character; the partial one is dropped rather than
    replaced, so no U+FFFD appears in text nobody sent."""
    capped, _ = apply_caps({"client": {"version": "é" * 400}})

    assert "�" not in capped["client"]["version"]


def test_a_pointer_never_forges_a_segment_from_a_client_key() -> None:
    """A `client` key containing a slash is escaped RFC 6901 style, so `/client/a~1b` cannot be
    confused with a real two-level pointer."""
    _, truncations = apply_caps({"client": {"a/b": "x" * 900}})

    assert truncations[0].pointer == "/client/a~1b"


def test_control_characters_are_stripped_but_tab_and_newline_survive() -> None:
    stripped = strip_control_characters({"note": "a\x00b\x07c\td\ne"})

    assert stripped["note"] == "abc\td\ne"


def test_a_carriage_return_is_stripped_with_the_other_control_characters() -> None:
    """§2.4 keeps tab and newline and nothing else, which normalizes CRLF to LF as a side
    effect."""
    assert strip_control_characters({"note": "a\r\nb"})["note"] == "a\nb"


def test_stripping_reaches_strings_nested_anywhere() -> None:
    stripped = strip_control_characters({"error": {"notes": ["a\x01b"], "cause": {"r": "c\x02d"}}})

    assert stripped["error"]["notes"] == ["ab"]
    assert stripped["error"]["cause"]["r"] == "cd"


def test_stripping_leaves_non_string_leaves_alone() -> None:
    stripped = strip_control_characters({"error": {"status": 1011, "retryable": True, "x": None}})

    assert stripped["error"] == {"status": 1011, "retryable": True, "x": None}


def test_a_document_within_the_structural_caps_has_no_violation() -> None:
    assert structural_violation(_nested(MAX_DEPTH)) is None


def test_a_document_nested_past_the_depth_cap_is_a_violation_that_names_the_cap() -> None:
    violation = structural_violation(_nested(MAX_DEPTH + 1))

    assert violation is not None
    assert str(MAX_DEPTH) in violation


def test_depth_is_counted_through_lists_as_well_as_objects() -> None:
    """A list is a level. Counting only objects would let `[[[[[[[…]]]]]]]` past the cap that
    exists to bound the walk."""
    document: Any = {"context": [[[[[["deep"]]]]]]}

    assert structural_violation(document) is not None


def test_an_object_with_more_keys_than_the_cap_is_a_violation() -> None:
    violation = structural_violation({str(index): index for index in range(MAX_KEYS_PER_NODE + 1)})

    assert violation is not None
    assert str(MAX_KEYS_PER_NODE) in violation


def test_the_key_cap_applies_to_a_nested_object_too() -> None:
    """The cap is per node; a client that puts its unbounded map one level down has still put an
    unbounded map in the report."""
    inner = {str(index): index for index in range(MAX_KEYS_PER_NODE + 1)}

    assert structural_violation({"error": {"details": inner}}) is not None
