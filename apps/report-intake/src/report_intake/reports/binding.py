"""`bind` — the first stage of spec §3's pipeline, and the only one that touches raw bytes.

    parse → structural caps → control-strip → truncate → validate

Order is load-bearing at three points:

- **Structural caps before anything walks the document.** Depth and key count are the two caps a
  client can use to make the service do unbounded work, so they are checked with an iterative
  walk before any recursive one runs.
- **Control-strip before truncate.** The stripped-but-untruncated mapping is `scanned`, which
  `OME-1007` classifies; a classifier that only ever saw the truncated text would treat
  truncation as a way to smuggle content past the check.
- **Truncate before validate.** Validation then runs on exactly the mapping that gets persisted,
  so `payload` is "validated" in the literal sense rather than in the hopeful one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ..core.pointers import escape_pointer
from ..core.problem_catalogue import malformed_body, schema_violation, unsupported_schema
from .caps import MAX_DEPTH, apply_caps, strip_control_characters, structural_violation
from .schema import SCHEMA_FAMILY, SUPPORTED_SCHEMA, BoundedReport, ReportDocument

_MAX_REPORTED_VIOLATIONS = 5


def bind(raw: bytes) -> BoundedReport:
    """Parse and bound a request body, or raise the catalogued problem that says why not."""
    document = _parse(raw)
    violation = structural_violation(document)
    if violation is not None:
        raise schema_violation(violation)
    _check_schema_major(document)
    scanned = strip_control_characters(document)
    payload, truncations = apply_caps(scanned)
    return BoundedReport(
        document=_validate(payload),
        payload=payload,
        truncations=truncations,
        scanned=scanned,
    )


def _parse(raw: bytes) -> Mapping[str, Any]:
    try:
        document = json.loads(raw)
    except RecursionError as exc:
        # json's own scanner gives up before this service gets a chance to measure the depth. The
        # verdict is the same one `structural_violation` would have reached, so give the client
        # that answer rather than an unhandled 500.
        raise schema_violation(f"report nests more than {MAX_DEPTH} levels deep") from exc
    except ValueError as exc:
        # `UnicodeDecodeError` is a `ValueError` too, so this covers a body that is not UTF-8.
        # Neither message quotes the body — both report a position — so echoing it leaks nothing.
        raise malformed_body(f"report body is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise schema_violation("report body must be a JSON object")
    return document


def _check_schema_major(document: Mapping[str, Any]) -> None:
    """400 for a report from a `schema` major this build does not implement (spec §2.3).

    Deliberately not 422: a major mismatch is not something the client can fix by correcting a
    field, and "unprocessable content" invites a retry loop over a body that will never be
    accepted here. A `schema` that is missing, non-string, or from another family is left to
    validation, which answers 422 — those are malformed reports, not future ones.
    """
    declared = document.get("schema")
    if not isinstance(declared, str) or declared == SUPPORTED_SCHEMA:
        return
    family, _, version = declared.rpartition("/")
    if family == SCHEMA_FAMILY and version.startswith("v"):
        raise unsupported_schema(declared, SUPPORTED_SCHEMA)


def _validate(payload: Mapping[str, Any]) -> ReportDocument:
    try:
        return ReportDocument.model_validate(payload)
    except ValidationError as exc:
        raise schema_violation(_describe(exc)) from exc


def _describe(exc: ValidationError) -> str:
    """Field pointers and pydantic's own reason, and nothing else.

    INVARIANT: `loc` and `msg` are read by name; the error object is never serialized wholesale.
    Its `input` and `ctx` members carry the offending *value*, which is exactly the free text this
    service refuses to echo — a 422 that quotes a prompt back over an unauthenticated response is
    the leak this endpoint exists to avoid.
    """
    reasons = [
        f"{_pointer(error['loc'])}: {error['msg']}"
        for error in exc.errors()[:_MAX_REPORTED_VIOLATIONS]
    ]
    remaining = len(exc.errors()) - len(reasons)
    if remaining > 0:
        reasons.append(f"and {remaining} more")
    return f"report does not match {SUPPORTED_SCHEMA} — {'; '.join(reasons)}"


def _pointer(location: tuple[int | str, ...]) -> str:
    """Pydantic's `loc` tuple as an RFC 6901 pointer, which is what the spec means by
    "field pointers"."""
    if not location:
        return "/"
    return "".join(f"/{escape_pointer(str(part))}" for part in location)
