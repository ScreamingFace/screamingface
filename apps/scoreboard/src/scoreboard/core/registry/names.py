"""System-name rules (erd.md §2.3.1).

FEATURE: OME-1307 (E14). INVARIANT: a system name is ASCII, at most 64 characters, lowercase, and
starts and ends with a letter or digit. One function decides it, so every caller sees one rule.
"""

from __future__ import annotations

import re

from .errors import InvalidSystemName

SYSTEM_NAME_MAX = 64
_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")  # erd.md §2.3.1
_SUFFIX_FINGERPRINT_CHARS = 4
# WHY 59: "-" plus four fingerprint characters is five characters, and 59 + 5 is the 64 maximum.
_SUGGESTION_BASE_MAX = SYSTEM_NAME_MAX - 1 - _SUFFIX_FINGERPRINT_CHARS


def normalize_system_name(raw: str) -> str:
    """The normalized system name, or `InvalidSystemName` naming the first rule that fails.

    Rules run in a fixed order: empty, ascii, length, slash, pattern. Whitespace is never
    stripped: a space fails the pattern rule.
    """
    if raw == "":
        raise InvalidSystemName("empty", "a system name must not be empty")
    # WHY the ASCII check runs before `lower()`: "K" (KELVIN SIGN) lowercases to the ASCII "k".
    # Lowercasing first would let a non-ASCII input become a valid ASCII name (SR-D9).
    if not raw.isascii():
        raise InvalidSystemName(
            "ascii", "a system name must use only ASCII letters, digits, '.', '_' and '-'"
        )
    if len(raw) > SYSTEM_NAME_MAX:
        raise InvalidSystemName("length", "a system name must be at most 64 characters")
    if "/" in raw:
        raise InvalidSystemName("slash", "a system name must not contain '/'")
    name = raw.lower()
    if not _NAME_RE.fullmatch(name):
        raise InvalidSystemName(
            "pattern",
            "a system name must start and end with a letter or digit, "
            "and use only a-z, 0-9, '.', '_' and '-'",
        )
    return name


def suggest_name(name: str, fingerprint: str) -> str:
    """A free-looking alternative for a taken `name`: the name plus four fingerprint characters.

    Does not check that the suggestion is free (OD-R4). The result always matches the name
    pattern and is at most 64 characters.
    """
    base = name[:_SUGGESTION_BASE_MAX].rstrip("._-")
    return f"{base}-{fingerprint[:_SUFFIX_FINGERPRINT_CHARS]}"
