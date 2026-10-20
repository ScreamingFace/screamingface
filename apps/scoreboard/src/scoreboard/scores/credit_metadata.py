"""The shared rules for a score's `authors_metadata` and `paper_metadata` (OME-1596, spec §3).

FEATURE: OME-1596 — open metadata about the authors and the paper behind a score. Known keys carry
bounds; any other key is accepted, stored and returned, never displayed. One validator for submit,
same-owner resubmit and PATCH, so an edit can never accept what a submission refuses.

INVARIANT: pure. Nothing here reads the database or imports a schema; the request schemas call the
shape checks, and the store calls the matching rule under the row lock (it needs the credit line
the row will hold after the write).

WHY problems are COLLECTED and not raised one at a time: the spec asks for one 422 entry per
problem, each naming the field and the key, so a client fixes everything in one round trip.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Annotated, NamedTuple
from urllib.parse import urlsplit

from pydantic import Field, TypeAdapter, ValidationError

MAX_KEYS = 20
# The authors cap `authors` itself carries (`schemas.py` reads it from here), and the length an
# `AuthorEmail` may have: an `authors_metadata` key past either cannot match a credited author.
MAX_AUTHORS = 10
AUTHOR_KEY_MAX_CHARS = 255
# Syntax only: no DNS, deliverability, allowlist or address normalization. Shared with
# `authors` in the request schemas, including metadata matched against legacy submitted_by.
# The dotted domain lets public serializers apply the same local-part rule as submitted_by.
AuthorEmail = Annotated[
    str,
    Field(max_length=AUTHOR_KEY_MAX_CHARS, pattern=r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$"),
]
_AUTHOR_EMAIL = TypeAdapter(AuthorEmail)
# WHY 64 KiB per object (owner, 2026-10-19): every per-key bound at its limit, in four-byte
# characters, stored a 1.4 MB `authors_metadata` (review round 2). Measured as stored (see
# `stored_size`), like the `metadata` byte cap in `schemas.py`; `paper_metadata` counts its `url`.
METADATA_MAX_BYTES = 64 * 1024
KEY_MAX_CHARS = 64
UNKNOWN_TEXT_MAX_CHARS = 500
# Known keys that hold text, with their bound. `url` is known too, under the paper link rules.
KNOWN_TEXT_MAX_CHARS: Mapping[str, int] = {
    "full_name": 200,
    "institution": 200,
    "title": 300,
    "citation": 2000,
}
URL_KEY = "url"

PAPER_URL_MAX_CHARS = 2048
_PAPER_URL_SCHEMES = frozenset({"http", "https"})


class MetadataProblem(NamedTuple):
    """One refused part of a metadata object: where it is, and why.

    ``loc`` starts with the field name, then the key (and the inner key for an author entry).
    ``keys`` names every key involved when there is more than one (two spellings of one author).
    """

    loc: tuple[str, ...]
    message: str
    keys: tuple[str, ...] = ()


def _jsonb_float(token: str) -> int | float:
    """The Python number JSONB returns for this JSON float spelling."""
    number = Decimal(token)
    exponent = number.as_tuple().exponent
    # WHY preserve fractional scale: JSONB keeps `1.0` as a float, but expands `1e23`
    # to an integer. Converting both would undercount mixed objects after a round trip.
    if isinstance(exponent, int) and exponent >= 0:
        return int(number)
    return float(token)


def stored_size(value: object) -> int:
    """Bound both Tortoise's JSON encoding and its PostgreSQL round-trip encoding.

    WHY this encoding: it is Tortoise's own `JSON_DUMPS` (`json.dumps` with compact separators;
    no `orjson` is installed). Escaping makes it
    pure ASCII, so its length is its size: a four-byte character counts as its twelve-byte
    surrogate-pair escape, a control character as its six-byte escape.
    INVARIANT: JSONB expands whole-valued exponent notation to integers. Account for that
    before writing, or an accepted object can exceed the cap when read and sent back unchanged.
    Only the accounting changes; the submitted metadata is never rewritten.
    """
    encoded = json.dumps(value, separators=(",", ":"), default=str)
    expanded = json.loads(encoded, parse_float=_jsonb_float)
    return max(len(encoded), len(json.dumps(expanded, separators=(",", ":"))))


def _size_problem(field: str, value: object) -> list[MetadataProblem]:
    if stored_size(value) <= METADATA_MAX_BYTES:
        return []
    return [MetadataProblem((field,), f"must store in at most {METADATA_MAX_BYTES} bytes")]


def author_identity(author: str) -> str:
    """The one comparison identity for authors: matching, duplicates, masking and the cap."""
    return author.casefold()


def validate_paper_url(value: str) -> str:
    """Accept an absolute `http(s)` link with a host, and return it UNCHANGED.

    FEATURE: OME-1307 — this checks the SHAPE of the link, never that the paper exists or that the
    named authors wrote it (out of scope for E14).

    INVARIANT: the string is stored exactly as sent. That is why this is not pydantic's `HttpUrl`,
    which lower-cases the host and appends a slash: a link a researcher pasted must come back as
    they pasted it. The portal still runs every link through `httpUrlOrNull` on read (M21).

    AIDEV-NOTE (OME-1596): moved here from `schemas.py` unchanged, so `paper_metadata.url` and
    `paper_url` run the very same rules; `schemas.py` imports it back under its old name.
    """
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("paper_url must not contain control characters")
    # WHY any whitespace, anywhere: `urlsplit` quietly strips leading and trailing blanks, so a
    # link with one would validate, be stored as sent, and then not be the URL it looks like.
    if any(char.isspace() for char in value):
        raise ValueError("paper_url must not contain whitespace")
    parts = urlsplit(value)
    if parts.scheme.lower() not in _PAPER_URL_SCHEMES:
        raise ValueError("paper_url must use the http or https scheme")
    if not parts.hostname:
        raise ValueError("paper_url must name a host")
    # WHY refuse user info: a paper link is shown and followed by readers, and
    # `https://trusted.example@evil.test/` reads as the first host while going to the second.
    # `username` is "" (not None) for a bare `@`, so test for None.
    if parts.username is not None or parts.password is not None:
        raise ValueError("paper_url must not contain user info")
    return value


def _unstorable(text: str) -> str | None:
    """Why ``text`` cannot be stored as JSON on every backend, or None when it can.

    WHY exactly these two (review round 1, PR 1440): PostgreSQL JSONB refuses the NUL character
    (the write answered 503), and a lone surrogate is not UTF-8, so SQLite stored it and every
    later read failed to encode it (a 500 with the row already committed). Detected structurally,
    character by character and by the UTF-8 encoder itself. Deliberately NOT a general ban on
    control characters: anything the store can hold is the submitter's to send.
    """
    if any(ord(char) == 0 for char in text):
        return "must not contain the NUL character"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "must be valid Unicode (no lone surrogates)"
    return None


def shown_key(key: str) -> str:
    """``key`` as an error location can carry: a lone surrogate written out as `\\udXXX`.

    The 422 is itself UTF-8 JSON, so a location holding the raw surrogate would fail to encode.
    """
    return key.encode("utf-8", "backslashreplace").decode("utf-8")


def _url_problem(value: object) -> str | None:
    reason: str | None = None
    if not isinstance(value, str):
        reason = "must be a string"
    elif not 1 <= len(value) <= PAPER_URL_MAX_CHARS:
        reason = f"must be 1 to {PAPER_URL_MAX_CHARS} characters"
    elif _unstorable(value) is not None:
        reason = _unstorable(value)
    else:
        try:
            validate_paper_url(value)
        except ValueError as exc:
            reason = str(exc)
    return reason


def _text_problem(value: object, limit: int, *, text_only: bool) -> str | None:
    reason: str | None = None
    if isinstance(value, str):
        reason = f"must be at most {limit} characters" if len(value) > limit else _unstorable(value)
    elif text_only:
        reason = "must be a string"
    # WHY: bools and ints are always finite; casting a large int to float can overflow.
    elif isinstance(value, bool | int):
        pass
    elif isinstance(value, float):
        # Python's JSON parser accepts NaN and Infinity; neither is a number a reader can use.
        if not math.isfinite(value):
            reason = "must be a finite number"
    else:
        reason = "must be text, a finite number or a boolean"
    return reason


def _value_problem(key: str, value: object) -> str | None:
    if key == URL_KEY:
        return _url_problem(value)
    if key in KNOWN_TEXT_MAX_CHARS:
        return _text_problem(value, KNOWN_TEXT_MAX_CHARS[key], text_only=True)
    return _text_problem(value, UNKNOWN_TEXT_MAX_CHARS, text_only=False)


def _key_problem(key: object) -> str | None:
    if not isinstance(key, str) or not 1 <= len(key) <= KEY_MAX_CHARS:
        return f"keys must be 1 to {KEY_MAX_CHARS} characters long"
    unstorable = _unstorable(key)
    return None if unstorable is None else f"keys {unstorable}"


def _object_problems(path: tuple[str, ...], value: object) -> list[MetadataProblem]:
    """The problems of one flat object: `paper_metadata`, or one author's entry.

    INVARIANT (review round 2): the response stays proportional to the request. Messages carry the
    reason only (the location names the field and key), and an object over the key cap is one
    problem, its keys never inspected: a 104 KB request used to answer with a 90 MB 422.
    """
    if not isinstance(value, Mapping):
        return [MetadataProblem(path, "must be an object")]
    if len(value) > MAX_KEYS:
        return [MetadataProblem(path, f"must have at most {MAX_KEYS} keys")]
    problems: list[MetadataProblem] = []
    for key, item in value.items():
        key_reason = _key_problem(key)
        if key_reason is not None:
            problems.append(MetadataProblem((*path, shown_key(str(key))), key_reason))
            continue
        reason = _value_problem(key, item)
        if reason is not None:
            problems.append(MetadataProblem((*path, key), reason))
    return problems


def paper_metadata_problems(value: Mapping[str, object]) -> list[MetadataProblem]:
    # The byte cap first, so an oversized object costs one check and one problem.
    return _size_problem("paper_metadata", value) or _object_problems(("paper_metadata",), value)


def _author_key_problem(key: str) -> str | None:
    """Check bounds/storability before syntax so error paths remain safe to publish."""
    reason = None
    if len(key) > AUTHOR_KEY_MAX_CHARS:
        reason = f"keys must be at most {AUTHOR_KEY_MAX_CHARS} characters"
    elif (unstorable := _unstorable(key)) is not None:
        reason = f"keys {unstorable}"
    else:
        try:
            _AUTHOR_EMAIL.validate_python(key)
        except ValidationError:
            reason = "keys must be valid author email addresses"
    return reason


def authors_metadata_problems(value: Mapping[str, object]) -> list[MetadataProblem]:
    """Shape problems of `authors_metadata`: each entry, and two keys for one author.

    WHY two spellings of one author are refused (owner, 2026-10-15): matching and masking compare
    the casefolded address, so `Ana@x.org` and `ana@x.org` are one author, and the public JSON
    would publish both entries under one name, one silently replacing the other.
    """
    # The object-wide bounds first, each one problem, before any entry is inspected (round 2).
    oversized = _size_problem("authors_metadata", value)
    if oversized:
        return oversized
    if len(value) > MAX_AUTHORS:
        return [MetadataProblem(("authors_metadata",), f"must name at most {MAX_AUTHORS} authors")]
    problems: list[MetadataProblem] = []
    first_spelling: dict[str, str] = {}
    for key, entry in value.items():
        key_problem = _author_key_problem(key)
        if key_problem is not None:
            # The entry is not checked further: its path would carry the key it cannot hold.
            problems.append(MetadataProblem(("authors_metadata", shown_key(key)), key_problem))
            continue
        identity = author_identity(key)
        if identity in first_spelling:
            first = first_spelling[identity]
            problems.append(
                MetadataProblem(
                    ("authors_metadata", key),
                    f"names the same author as {first!r}",
                    keys=(first, key),
                )
            )
        else:
            first_spelling[identity] = key
        problems.extend(_object_problems(("authors_metadata", key), entry))
    return problems


def unmatched_author_keys(
    value: Mapping[str, object], credit_line: Sequence[str] | None
) -> list[MetadataProblem]:
    """Every `authors_metadata` key that is not an author in ``credit_line``.

    ``credit_line`` is the list the row will show: `authors`, or `[submitted_by]` when `authors`
    is null (owner, 2026-10-15). The comparison uses `author_identity`, as `authors` itself does.
    """
    credited = {author_identity(author) for author in credit_line or ()}
    return [
        MetadataProblem(("authors_metadata", key), "is not an email in authors")
        for key in value
        if author_identity(key) not in credited
    ]


def keep_matching_authors(
    value: Mapping[str, object], credit_line: Sequence[str] | None
) -> dict[str, object]:
    """``value`` without the entries of authors no longer in ``credit_line``, spellings kept.

    FEATURE: removing an author drops their metadata in the same edit (spec section 2).
    """
    credited = {author_identity(author) for author in credit_line or ()}
    return {key: entry for key, entry in value.items() if author_identity(key) in credited}


def split_paper_metadata(value: Mapping[str, object]) -> tuple[dict[str, object], str | None]:
    """The stored `paper_metadata` (every key but `url`) and the link for `paper_url`.

    INVARIANT (owner, 2026-10-15): the object is replaced WHOLE, link included, so an object
    without `url` clears `paper_url`, and an object holding only `url` is stored as `{}` (not
    NULL, which would read as "never sent").
    """
    url = value.get(URL_KEY)
    stored = {key: item for key, item in value.items() if key != URL_KEY}
    return stored, url if isinstance(url, str) else None
