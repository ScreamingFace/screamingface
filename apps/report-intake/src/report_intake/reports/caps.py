"""Spec §2.4 as data, plus the truncator that enforces it.

The numbers are concrete rather than "bounded" because `OME-969` is what happens when they are
not. They live in one module so that the chart, the docs, and the tests all quote one source.

**The reject/truncate split is the spec's, and it is deliberate.** Only the total body cap and
*structural* violations (depth, keys per node) reject the report; an individual oversized string
is truncated and marked, because a truncated report is worth more than no report. Anything that
inverts that — rejecting a 300-byte `client.version`, say — is a bug against §2.4.

Marking is in-band wherever the value is a string, so the mark survives into the persisted
payload and onto the ticket a human eventually reads. :class:`Truncation` records the same events
out of band for callers that want the numbers; a dropped `notes[]` entry is recorded *only* there,
because the in-band alternative is a seventeenth item in a list whose cap is sixteen.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from ..core.pointers import escape_pointer

MAX_BODY_BYTES = 64 * 1024
"""Total request body. The only cap enforced pre-parse — see `core/body_limit.py`."""

MAX_DEPTH = 6
"""JSON nesting depth, counting containers only. The top-level object is depth 1, so
`client.runtime` sits at 3 and an extension point still has three levels of headroom."""

MAX_KEYS_PER_NODE = 64

NOTE_BYTES = 4 * 1024
ERROR_MESSAGE_BYTES = 8 * 1024
ERROR_TRACEBACK_BYTES = 32 * 1024
ERROR_DETAILS_BYTES = 8 * 1024
ERROR_CAUSE_BYTES = 8 * 1024
"""`error.cause`, capped exactly like its sibling `error.details`.

Spec §2.4's table has a row for `details` and none for `cause`, which left the one node in the
report that is arbitrary client-shaped JSON with no bound at all: a `cause` of fifty
marker-free string leaves is ~48 KiB inside a 64 KiB body, and all of it was committed to the
`payload` column. §2.1 describes the two nodes identically — machine-built server JSON — and
"bounded" without a number is how `OME-969` happened, so `cause` gets its sibling's number.
Truncate-and-mark, never reject: the reject/truncate split is §2.4's and this does not move it."""

ERROR_NOTES_ITEMS = 16
CLIENT_CONTEXT_STRING_BYTES = 256
USER_AGENT_BYTES = 1024

TRUNCATED_DETAILS_KEY = "report-intake:truncated"
"""Where an oversized `error.details` or `error.cause` object goes: its JSON serialization,
truncated as a string, under one key. Replacing the object with a marker would discard everything
a triager needs, and there is no way to cut a JSON *object* to a byte budget and have it still
parse."""

_MARK = "…[report-intake truncated {original} bytes to the {cap} byte cap]…"

_TRACEBACK_POINTER = "/error/traceback"
_EXACT_CAPS = {
    "/note": NOTE_BYTES,
    "/error/message": ERROR_MESSAGE_BYTES,
    "/client/user_agent": USER_AGENT_BYTES,
}
_PREFIX_CAPS = (
    ("/client/", CLIENT_CONTEXT_STRING_BYTES),
    ("/context/", CLIENT_CONTEXT_STRING_BYTES),
)

# Unicode category Cc is exactly U+0000–U+001F and U+007F–U+009F, so the table is exhaustive
# without a per-character `unicodedata` lookup over what may be 64 KiB of text. Tab and newline
# are kept because a traceback without them is unreadable; carriage return is not, which
# normalizes CRLF to LF as a side effect.
_CONTROL_CHARACTERS = {code: None for code in [*range(0x00, 0x20), *range(0x7F, 0xA0)]}
del _CONTROL_CHARACTERS[0x09]
del _CONTROL_CHARACTERS[0x0A]


@dataclass(frozen=True, slots=True)
class Truncation:
    """One capping event, for logs and for whoever renders the ticket."""

    pointer: str
    """RFC 6901 JSON pointer to the capped value, e.g. `/error/traceback`."""
    kept: int
    original: int
    unit: str
    """`bytes` for a string, `items` for a list."""


def structural_violation(document: Any) -> str | None:
    """The first structural cap ``document`` breaks, phrased for a client, or None.

    Iterative rather than recursive on purpose: this runs on input a client controls, and a
    recursive walk over a deeply nested body raises `RecursionError` — a 500 — at exactly the
    depth this function exists to reject with a 422.
    """
    pending: list[tuple[Any, int]] = [(document, 1)]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_DEPTH:
            return f"report nests more than {MAX_DEPTH} levels deep"
        if isinstance(node, Mapping) and len(node) > MAX_KEYS_PER_NODE:
            return (
                f"an object in the report carries {len(node)} keys; "
                f"the limit is {MAX_KEYS_PER_NODE} per object"
            )
        pending.extend(
            (child, depth + 1) for child in _children(node) if isinstance(child, Mapping | list)
        )
    return None


def strip_control_characters(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Every string value with control characters other than tab and newline removed (§2.4).

    Keys are left verbatim: unknown keys inside `client` and `context` are preserved rather than
    interpreted, and rewriting one would change what a client sent back to itself.
    """
    return cast(Mapping[str, Any], _walk_strings(document, "", lambda value, _: _strip(value)))


def apply_caps(document: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[Truncation, ...]]:
    """``document`` with every §2.4 truncating row applied, and the record of what was cut."""
    marks: list[Truncation] = []
    capped = _cap_error_containers(document, marks)
    walked = _walk_strings(capped, "", lambda value, pointer: _cap_string(value, pointer, marks))
    return cast(dict[str, Any], walked), tuple(marks)


def _children(node: Any) -> Iterable[Any]:
    return node.values() if isinstance(node, Mapping) else node


def _strip(value: str) -> str:
    return value.translate(_CONTROL_CHARACTERS)


def _walk_strings(node: Any, pointer: str, leaf: Callable[[str, str], str]) -> Any:
    """Rebuild ``node``, replacing each string with ``leaf(value, pointer_to_it)``.

    Recursion is safe here: every caller runs after :func:`structural_violation` has bounded the
    depth at :data:`MAX_DEPTH`.
    """
    if isinstance(node, Mapping):
        walked: Any = {
            key: _walk_strings(value, f"{pointer}/{escape_pointer(str(key))}", leaf)
            for key, value in node.items()
        }
    elif isinstance(node, list):
        walked = [
            _walk_strings(item, f"{pointer}/{index}", leaf) for index, item in enumerate(node)
        ]
    elif isinstance(node, str):
        walked = leaf(node, pointer)
    else:
        walked = node
    return walked


def _cap_string(value: str, pointer: str, marks: list[Truncation]) -> str:
    if pointer == _TRACEBACK_POINTER:
        return _truncate_ends(value, ERROR_TRACEBACK_BYTES, pointer, marks)
    cap = _cap_for(pointer)
    if cap is None:
        return value
    return _truncate_head(value, cap, pointer, marks)


def _cap_for(pointer: str) -> int | None:
    if pointer in _EXACT_CAPS:
        return _EXACT_CAPS[pointer]
    matched = [cap for prefix, cap in _PREFIX_CAPS if pointer.startswith(prefix)]
    return matched[0] if matched else None


def _truncate_head(value: str, cap: int, pointer: str, marks: list[Truncation]) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= cap:
        return value
    mark = _MARK.format(original=len(raw), cap=cap)
    budget = max(cap - len(mark.encode("utf-8")), 0)
    head = _decode(raw[:budget])
    marks.append(Truncation(pointer, len(head.encode("utf-8")), len(raw), "bytes"))
    return head + mark


def _truncate_ends(value: str, cap: int, pointer: str, marks: list[Truncation]) -> str:
    """Keep both ends (§2.4): CPython renders the innermost frame last, V8's `Error.stack` renders
    it first, so a truncator that keeps one end has to know which runtime produced the string.
    Keeping both means it does not."""
    raw = value.encode("utf-8")
    if len(raw) <= cap:
        return value
    mark = _MARK.format(original=len(raw), cap=cap)
    budget = max(cap - len(mark.encode("utf-8")), 0)
    head, tail = _decode(raw[: budget // 2]), _decode(raw[len(raw) - (budget - budget // 2) :])
    kept = len(head.encode("utf-8")) + len(tail.encode("utf-8"))
    marks.append(Truncation(pointer, kept, len(raw), "bytes"))
    return head + mark + tail


def _decode(raw: bytes) -> str:
    """A byte slice may start or end mid-character; the partial one is dropped rather than
    replaced, so no U+FFFD appears in text nobody sent."""
    return raw.decode("utf-8", errors="ignore")


def _cap_error_containers(document: Mapping[str, Any], marks: list[Truncation]) -> dict[str, Any]:
    """`error.details`, `error.cause` and `error.notes` — the rows whose cap is not on a string."""
    error = document.get("error")
    if not isinstance(error, Mapping):
        return dict(document)
    capped = dict(error)
    for key, cap in (("details", ERROR_DETAILS_BYTES), ("cause", ERROR_CAUSE_BYTES)):
        node = capped.get(key)
        if isinstance(node, Mapping):
            capped[key] = _cap_object(node, cap, f"/error/{key}", marks)
    notes = capped.get("notes")
    if isinstance(notes, list):
        capped["notes"] = _cap_notes(notes, marks)
    return {**document, "error": capped}


def _cap_object(
    node: Mapping[str, Any], cap: int, pointer: str, marks: list[Truncation]
) -> Mapping[str, Any]:
    """An arbitrary-JSON node, cut so that ITS OWN SERIALIZATION fits ``cap``.

    The budget is measured against the WRAPPER rather than against the serialization that went
    in, and that is the whole subtlety. What is kept becomes a JSON *string* under one key, so
    every `"` and `\\` in it re-escapes to two bytes on the way back out. Budgeting against the
    input left a details object of escape-heavy keys 2.6 KiB over an 8 KiB cap — not the "few
    bytes" an earlier note claimed, and not a number this cap is stated in. One corrective pass
    is enough in principle (shortening the head by *k* bytes shortens the wrapper by at least
    *k*), and the loop re-checks anyway because a cut can land mid-character.

    The in-band mark always names the REAL cap, never the working budget: it is read by a human
    looking at the ticket, and "the 7 931 byte cap" would be a number nothing in the spec has.
    """
    serialized = _serialized(node)
    raw = serialized.encode("utf-8")
    if len(raw) <= cap:
        return node
    mark = _MARK.format(original=len(raw), cap=cap)
    budget = max(cap - len(mark.encode("utf-8")), 0)
    while True:
        head = _decode(raw[:budget])
        wrapped = {TRUNCATED_DETAILS_KEY: head + mark}
        overshoot = len(_serialized(wrapped).encode("utf-8")) - cap
        if overshoot <= 0 or budget == 0:
            break
        budget = max(budget - overshoot, 0)
    marks.append(Truncation(pointer, len(head.encode("utf-8")), len(raw), "bytes"))
    return wrapped


def _serialized(node: Mapping[str, Any]) -> str:
    return json.dumps(node, ensure_ascii=False, separators=(",", ":"), default=str)


def _cap_notes(notes: list[Any], marks: list[Truncation]) -> list[Any]:
    if len(notes) <= ERROR_NOTES_ITEMS:
        return notes
    marks.append(Truncation("/error/notes", ERROR_NOTES_ITEMS, len(notes), "items"))
    return notes[:ERROR_NOTES_ITEMS]
