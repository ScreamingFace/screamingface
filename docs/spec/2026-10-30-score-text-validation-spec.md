# Score text validation — OME-1658

Approved scope: ticket acceptance, authorized by Filip on 2026-10-30.

Authors, paper URLs and nested free-form metadata must contain storable Unicode:
no NUL or lone surrogates. Reuse the existing credit-metadata definition. Reject
before persistence with a 422 naming the field. Apply identical author/URL rules
to submit and PATCH; free-form metadata is submitted only and remains unsupported
by PATCH. Preserve allowed control characters in metadata, normal Unicode, and
existing author/URL rules.

A RequestValidationError may echo invalid Unicode anywhere in its error body,
even when a field has the wrong type. Preserve FastAPI's usual response for normal
input; fall back to ASCII-escaped JSON only if UTF-8 encoding fails. Do not rewrite
valid stored data, change authentication, or add metadata size/depth limits.

No database model or migration changes. Test actual HTTP responses and persistence
on SQLite and PostgreSQL, including failed edits and same-owner resubmission.

Review follow-up: verify rejected input structurally after strict UTF-8 decoding.
An invalid Unicode field name is reported by Pydantic at the body root with the
name itself as input; invalid values in score/unknown fields echo the supplied
object. A matching escape elsewhere in the response is insufficient evidence.
