"""The RDS input document and its ``?q=`` code-pointer target — one codec, one owner.

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a group's sources reach a code pointer as one JSON
# document, so the pointer receives each input exactly as its source resolved.
#
# INVARIANT: a target built by :func:`encode_rds_target` decodes back to the same
# document under both wire conventions — the raw one :mod:`url4.wire.subrequest`
# writes and the fully-encoded one a standard HTTP client sends.

A code-pointer call is a GET whose ``q`` parameter is the document, with no
``!`` tail. :func:`encode_rds_document` builds the JSON text,
:func:`encode_rds_target` puts it on the wire, and :func:`decode_q_payload` and
:func:`decode_rds_document` undo both on the receiving node.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.parse import quote, unquote, unquote_plus

RdsValue = str | list[object] | dict[str, object]
RDS_VERSION = 1

# INVARIANT: `+` is not in the safe set, so it is escaped too. A fully-encoded
# decode reads a raw `+` as a space.
_DOCUMENT_SAFE = "!$*,;:@/?="


def encode_rds_document(inputs: Mapping[str, RdsValue]) -> str:
    """The v1 input document ``{"v":1,"inputs":{...}}`` as compact JSON text."""
    # WHY: ensure_ascii=False keeps non-ASCII raw, and the separators leave no
    # whitespace to be escaped later. Key order is the source order (`inputs` is a
    # dict, and json.dumps keeps insertion order).
    return json.dumps(
        {"v": RDS_VERSION, "inputs": dict(inputs)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_rds_document(text: str) -> dict[str, RdsValue] | None:
    """The ``inputs`` of a valid v1 document, else None. Never raises."""
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        # WHY: RecursionError is the parser's answer to nesting too deep to read.
        # The text is attacker-controlled over HTTP, so it is a bad document, not
        # a crash.
        return None
    if not _is_v1_document(doc):
        return None
    return doc["inputs"]


def _is_v1_document(doc: object) -> bool:
    # WHY: `type(...) is int` rejects a JSON `true`, which `== 1` would accept.
    return (
        isinstance(doc, dict)
        and type(doc.get("v")) is int
        and doc["v"] == RDS_VERSION
        and isinstance(doc.get("inputs"), dict)
    )


def encode_rds_target(path: str, query: str, document: str) -> str:
    """The C2 target ``<path>?<query>&q=(<escaped>)``, or ``<path>?q=(<escaped>)``.

    ``path`` and ``query`` are the author's bytes and are not re-encoded. Only
    the document is escaped.
    """
    tail = f"q=({quote(document, safe=_DOCUMENT_SAFE)})"
    if query:
        return f"{path}?{query}&{tail}"
    return f"{path}?{tail}"


def decode_q_payload(raw_q: str) -> str | None:
    """The unescaped body of a ``(body)`` payload with no ``!`` tail, else None.

    Two conventions, told apart by a raw ``(``: url4's own writer keeps the
    structural parens raw, and a standard HTTP client escapes them all.
    """
    if "(" in raw_q:
        return _decode_raw_q(raw_q)
    if "%" in raw_q:
        return _decode_encoded_q(raw_q)
    return None


def _decode_raw_q(raw_q: str) -> str | None:
    # WHY: the body is cut at the outer parens, not by a balanced-paren scan. A
    # JSON string may hold unbalanced parens, so a scan would misread a document
    # that is valid. The body must hold no raw paren, because the writer escapes
    # every paren in the document. A raw `)` followed by `!` is an LLM call and
    # fails the end check.
    if not (raw_q.startswith("(") and raw_q.endswith(")")):
        return None
    body = raw_q[1:-1]
    if "(" in body or ")" in body:
        return None
    return unquote(body)


def _decode_encoded_q(raw_q: str) -> str | None:
    # WHY: one full decode restores the document's text, so the outer parens are
    # cut from the decoded text, not from the escaped one.
    text = unquote_plus(raw_q)
    if not (text.startswith("(") and text.endswith(")")):
        return None
    return text[1:-1]


__all__ = [
    "RDS_VERSION",
    "RdsValue",
    "decode_q_payload",
    "decode_rds_document",
    "encode_rds_document",
    "encode_rds_target",
]
