"""The workbench's one redactor (e2e workbench spec §3.3; review finding 1).

Every sink a workbench verdict reaches imports this module: the evidence bundle
(``bundle.py``), failure reasons (``result_check.py``, ``verdict.py``), and the lane's report
hook (``conftest.py``), which scrubs the terminal / JUnit text of every report.

INVARIANT: redaction runs on values, never on serialised JSON. ``bearer\\s+\\S+`` applied to a
JSON document would swallow the closing quote of the string it sits in and corrupt the file.

SHAPES. Token-shaped secrets are masked whole (``sk-…``, JWTs, ``Bearer``/``Basic`` credentials,
GitHub ``ghp_…``/``github_pat_…``, GitLab ``glpat-…``, Google ``AIza…``, Hugging Face ``hf_…``,
AWS ``AKIA…``, Slack ``xox?-…``, PEM private keys). Opaque secrets are found by the NAME they are
bound to and only the value is masked, so the reader still sees what was there: URL userinfo
passwords, query parameters (``?api_key=…&token=…``), ``Authorization`` with any scheme, and
assignments / headers / mapping entries whose name ends in key, token, secret, password,
credential(s), auth or sig (``OPENROUTER_API_KEY=…``, ``x-api-key: …``, ``api_key=b'…'``,
``"client_secret": "…"``, also in escaped JSON and reprs). See the pattern comments for what
is deliberately left readable.

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
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    # A PEM private key, header to footer; a truncated one (no footer) to the end of the text.
    re.compile(r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),
)
# The name must END in the secret word: `max_tokens` (a count) is not a token. Names may hold
# `-` so HTTP headers (`x-api-key`, `X-Goog-Api-Key`) match like identifiers.
_SECRET_NAME: Final = r"(?:key|token|secret|password|passwd|pwd|credentials?|auth|sig|signature)"
# WHY bare `key` is excluded from assignments (but not from `?key=` queries, Google's API-key
# parameter): the gateway logs `key=<cache key>` on every cache hit, and masking it would blur
# the evidence. A compound name (`api_key`, `SECRET_KEY`, `apikey`, `x-api-key`) still matches.
#
# WHY the secret word is tested as a SUFFIX by lookbehinds after one greedy `[\w-]+`, with no
# length cap: a capped prefix (`[\w-]{0,64}token`) let a 65-char name walk past the redactor
# (re-review finding 1). The run is consumed once; the separator can never match a `[\w-]`
# char, so backtracking only gives back chars of that same run — linear in its length. Each
# lookbehind is fixed-width (`re` needs that); `[\w-]key` keeps bare `key` out.
_ASSIGNED_NAME: Final = (
    r"[\w-]+(?:"
    + "|".join(
        f"(?<={word})"
        for word in (
            "token",
            "secret",
            "password",
            "passwd",
            "pwd",
            "credential",
            "credentials",
            "auth",
            "sig",
            "signature",
            r"[\w-]key",
        )
    )
    + ")"
)
_NOT_MASKED: Final = rf"(?!{re.escape(MASK)})"
# `"name": `, `name=`, `\"name\": ` (JSON inside a JSON string), `'name': ` (a repr).
_SEPARATOR: Final = r"((?:\\*['\"])?\s*[=:]\s*)"
# A quoted value, masked whole: an optional bytes/str prefix, then the opening quote with any
# backslashes before it (`\"v\"` in escaped JSON, `\'v\'` in a repr), up to the same quote.
_QUOTED: Final = r"[bBrRuUfF]{0,2}(?P<q>\\*['\"])(?:(?!(?P=q))[^\n])*(?P=q)?"
# Code in a notebook's source, not a secret, so left readable: a call with no arguments or a
# quoted first argument, or a subscript by a quoted key (`load_key()`, `os.getenv("K")`,
# `os.environ["K"]`). Any other value shaped like a call (`opaque(len)`) is masked.
_CODE: Final = r"[A-Za-z_][\w.]*[(\[](?:\)|\\*['\"])"
# scheme://user:<password>@host — the password runs to the LAST `@` of the authority, so a
# password holding `@` is masked whole.
_USERINFO: Final = re.compile(rf"(://[^/\s:@]+:){_NOT_MASKED}[^/\s?#]*@")
# ?api_key=…&token=… — the value runs to the next URL delimiter or quote.
_QUERY: Final = re.compile(rf"(?i)([?&][\w.-]*{_SECRET_NAME}=){_NOT_MASKED}[^&#\s'\"]+")
# `Authorization: <scheme> <credential>` with any scheme (Token, ApiKey, Key, Digest, …): a
# quoted value is masked whole; an unquoted one to the end of the line, because a Digest
# credential is a comma-separated list. Bearer/Basic are already masked by _TOKENS.
_AUTHORIZATION: Final = re.compile(
    rf"(?i)\b((?:proxy-)?authorization){_SEPARATOR}{_NOT_MASKED}(?:{_QUOTED}|\S[^\r\n]*)"
)
# WHY `(?<![\w-])` instead of `\b`: `\b` restarts the name at every `-` boundary of a long
# `[\w-]` run (urlsafe base64), which made matching quadratic (16 KB took ~7 s).
# NAME=value, NAME: value, 'name': 'value', "name": "value", name='value', name=b"value".
_ASSIGNMENT: Final = re.compile(
    rf"(?i)(?<![\w-])({_ASSIGNED_NAME}){_SEPARATOR}{_NOT_MASKED}"
    rf"(?:{_QUOTED}|(?!{_CODE})[^\s'\",;&)}}\]]+)"
)


def redact(text: str) -> str:
    """``text`` with every recognised secret replaced by ``MASK``. Idempotent."""
    for pattern in _TOKENS:
        text = pattern.sub(MASK, text)
    text = _USERINFO.sub(rf"\g<1>{MASK}@", text)
    text = _QUERY.sub(rf"\g<1>{MASK}", text)
    text = _AUTHORIZATION.sub(rf"\g<1>\g<2>{MASK}", text)
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
