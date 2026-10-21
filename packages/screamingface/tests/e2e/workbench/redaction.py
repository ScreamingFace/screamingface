"""The workbench's one redactor (e2e workbench spec §3.3; review finding 1).

Every sink a workbench verdict reaches imports this module: the evidence bundle
(``bundle.py``), failure reasons (``result_check.py``, ``verdict.py``), and the lane's report
hook (``conftest.py``), which scrubs the terminal / JUnit text of every report.

INVARIANT: redaction runs on values, never on serialised JSON. ``bearer\\s+\\S+`` applied to a
JSON document would swallow the closing quote of the string it sits in and corrupt the file.

SHAPES. Token-shaped secrets are masked whole (``sk-…``, JWTs, ``Bearer``/``Basic`` credentials,
GitHub ``ghp_…``/``github_pat_…``, Google ``AIza…``, Hugging Face ``hf_…``, AWS ``AKIA…``,
Slack ``xox?-…``). Opaque secrets are found by the NAME they are bound to and only the value is
masked, so the reader still sees what was there: URL userinfo passwords, query parameters
(``?api_key=…&token=…``), and assignments / mapping entries whose name ends in key, token,
secret, password, credential(s), auth or sig (``OPENROUTER_API_KEY=…``, ``api_key='…'``,
``"client_secret": "…"``). See the pattern comments for what is deliberately left readable.

WHY fail closed on names: a false positive costs one masked word in a failure message; a
false negative publishes a key in CI output.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

MASK: Final = "[REDACTED]"

_TOKENS: Final = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"\bBasic\s+[A-Za-z0-9+/]{8,}={0,2}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
)
# The name must END in the secret word: `max_tokens` (a count) is not a token.
_SECRET_NAME: Final = r"(?:key|token|secret|password|passwd|pwd|credentials?|auth|sig|signature)"
# WHY bare `key` is excluded from assignments (but not from `?key=` queries, Google's API-key
# parameter): the gateway logs `key=<cache key>` on every cache hit, and masking it would blur
# the evidence. A compound name (`api_key`, `SECRET_KEY`, `apikey`) still matches.
_ASSIGNED_NAME: Final = (
    r"(?:\w*(?:token|secret|password|passwd|pwd|credentials?|auth|sig|signature)|\w+key)"
)
_NOT_MASKED: Final = rf"(?!{re.escape(MASK)})"
# scheme://user:<password>@host
_USERINFO: Final = re.compile(rf"(://[^/\s:@]+:){_NOT_MASKED}[^/\s@]+@")
# ?api_key=…&token=… — the value runs to the next URL delimiter or quote.
_QUERY: Final = re.compile(rf"(?i)([?&][\w.-]*{_SECRET_NAME}=){_NOT_MASKED}[^&#\s'\"]+")
# NAME=value, NAME: value, 'name': 'value', "name": "value", name='value'. An unquoted value
# that is a Python call or subscript (`api_key=os.environ["K"]`, `load_key()`) is code in a
# notebook's source, not a secret, and is left readable.
_ASSIGNMENT: Final = re.compile(
    rf"(?i)\b({_ASSIGNED_NAME})(['\"]?\s*[=:]\s*){_NOT_MASKED}"
    r"(?:'[^'\n]*'?|\"[^\"\n]*\"?|(?![\w.]*[(\[])[^\s'\",;&)}\]]+)"
)


def redact(text: str) -> str:
    """``text`` with every recognised secret replaced by ``MASK``. Idempotent."""
    for pattern in _TOKENS:
        text = pattern.sub(MASK, text)
    text = _USERINFO.sub(rf"\g<1>{MASK}@", text)
    text = _QUERY.sub(rf"\g<1>{MASK}", text)
    return _ASSIGNMENT.sub(rf"\g<1>\g<2>{MASK}", text)


def redact_tree(value: Any) -> Any:
    """Redact every string in a JSON-like tree (dicts, lists, NotebookNodes), keys included."""
    match value:
        case str():
            out: Any = redact(value)
        case dict():
            items: dict[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
            out = {redact_tree(k): redact_tree(v) for k, v in items.items()}
        case list() | tuple():
            seq: Sequence[Any] = value  # pyright: ignore[reportUnknownVariableType]
            out = [redact_tree(v) for v in seq]
        case _:
            out = value
    return out
