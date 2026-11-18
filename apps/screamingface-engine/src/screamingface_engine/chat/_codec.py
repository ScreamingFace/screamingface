"""The helpers that the chat records share: how a refusal names a value, and the JSON reader."""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["json_object", "shown"]

# INVARIANT: the same name rule as `_SHOWN_NAME_RE` of benchmarks/candidate_input.py: a refusal
# repeats a value only when it looks like a name, so a Case-sized string never reaches a log.
_SHOWN_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def shown(value: object) -> str:
    """How a refusal names a value: quoted if it looks like a name, else its type only."""

    if isinstance(value, str) and _SHOWN_NAME_RE.fullmatch(value):
        return repr(value)
    return f"<{type(value).__name__}>"


def json_object(data: bytes, error: type[ValueError], record: str) -> dict[str, Any]:
    """The bytes as a JSON object; else `error`, whose message starts with `record`."""

    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise error(f"{record} is not UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise error(f"{record} is not a JSON object")
    return value
