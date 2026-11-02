# Score submission metadata limits — OME-969

Reuse the existing `_validate_bounded_metadata` policy for ScoreSubmission:
4096 bytes using the existing ASCII-escaped JSON serialization, maximum depth 4
using the existing baseline depth definition. Rejections identify body.metadata.
Null, omitted, empty, ordinary and exact-boundary metadata remain accepted.
Do not change baseline behavior, add a new dependency or modify stored rows.

## Review follow-up — 2 November 2026

Reject excessively nested metadata without recursion errors, and bound the expanded numeric JSON representation on public submissions while preserving existing baseline budgets. Keep both metadata validators when combined with OME-1658 by using separate insertion points. Verify raw HTTP nesting, positive/negative exponents, exact boundaries, and database persistence on SQLite/PostgreSQL.


The public submission budget also counts expansion of exponent numbers into fixed decimal JSON. Non-finite metadata numbers are rejected. Depth validation stops at level five; depth/non-finite validation errors omit the unsafe input while retaining the field location. Unparseable JSON remains HTTP 400. PostgreSQL regressions are named explicitly in CI. No migration or baseline storage-policy change.
