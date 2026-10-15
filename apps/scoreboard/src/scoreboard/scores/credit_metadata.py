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

import math
from collections.abc import Mapping, Sequence
from typing import NamedTuple
from urllib.parse import urlsplit

MAX_KEYS = 20
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


def _url_problem(value: object) -> str | None:
    reason: str | None = None
    if not isinstance(value, str):
        reason = "must be a string"
    elif not 1 <= len(value) <= PAPER_URL_MAX_CHARS:
        reason = f"must be 1 to {PAPER_URL_MAX_CHARS} characters"
    else:
        try:
            validate_paper_url(value)
        except ValueError as exc:
            reason = str(exc)
    return reason


def _text_problem(value: object, limit: int, *, text_only: bool) -> str | None:
    reason: str | None = None
    if isinstance(value, str):
        if len(value) > limit:
            reason = f"must be at most {limit} characters"
    elif text_only:
        reason = "must be a string"
    # WHY bool first: `True` is an `int` in Python, and a boolean is accepted as itself.
    elif isinstance(value, bool):
        pass
    elif isinstance(value, int | float):
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


def _object_problems(path: tuple[str, ...], value: object) -> list[MetadataProblem]:
    """The problems of one flat object: `paper_metadata`, or one author's entry."""
    if not isinstance(value, Mapping):
        return [MetadataProblem(path, f"{'.'.join(path)} must be an object")]
    problems: list[MetadataProblem] = []
    if len(value) > MAX_KEYS:
        problems.append(
            MetadataProblem(path, f"{'.'.join(path)} must have at most {MAX_KEYS} keys")
        )
    for key, item in value.items():
        if not isinstance(key, str) or not 1 <= len(key) <= KEY_MAX_CHARS:
            problems.append(
                MetadataProblem(
                    (*path, str(key)), f"keys must be 1 to {KEY_MAX_CHARS} characters long"
                )
            )
            continue
        reason = _value_problem(key, item)
        if reason is not None:
            problems.append(MetadataProblem((*path, key), f"{'.'.join(path)}.{key} {reason}"))
    return problems


def paper_metadata_problems(value: Mapping[str, object]) -> list[MetadataProblem]:
    return _object_problems(("paper_metadata",), value)


def authors_metadata_problems(value: Mapping[str, object]) -> list[MetadataProblem]:
    """Shape problems of `authors_metadata`: each entry, and two keys for one author.

    WHY two spellings of one author are refused (owner, 2026-10-15): matching and masking compare
    the casefolded address, so `Ana@x.org` and `ana@x.org` are one author, and the public JSON
    would publish both entries under one name, one silently replacing the other.
    """
    problems: list[MetadataProblem] = []
    first_spelling: dict[str, str] = {}
    for key, entry in value.items():
        identity = author_identity(key)
        if identity in first_spelling:
            first = first_spelling[identity]
            problems.append(
                MetadataProblem(
                    ("authors_metadata", key),
                    f"authors_metadata names one author twice: {first!r} and {key!r}",
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
        MetadataProblem(
            ("authors_metadata", key), f"authors_metadata key {key!r} is not an email in authors"
        )
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
