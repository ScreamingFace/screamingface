# Metadata limits implementation — OME-969

1. Add schema and HTTP boundary regressions; observe the current missing checks.
2. Attach the existing validator to ScoreSubmission.
3. Run request and baseline tests, then full scoreboard gates.
4. Record results, review, commit and open a linked PR.

## Review follow-up — 2 November 2026

Reject excessively nested metadata without recursion errors, and bound the expanded numeric JSON representation on public submissions while preserving existing baseline budgets. Keep both metadata validators when combined with OME-1658 by using separate insertion points. Verify raw HTTP nesting, positive/negative exponents, exact boundaries, and database persistence on SQLite/PostgreSQL.


The public submission budget also counts expansion of exponent numbers into fixed decimal JSON. Non-finite metadata numbers are rejected. Depth validation stops at level five; depth/non-finite validation errors omit the unsafe input while retaining the field location. Unparseable JSON remains HTTP 400. PostgreSQL regressions are named explicitly in CI. No migration or baseline storage-policy change.

## Second review follow-up — 2 November 2026

Sanitize every validation error located at body.metadata, including wrong-type and size failures, by omitting only its input. Keep error type, location, context and messages, and preserve unrelated inputs. Reproduce oversized and wrong-type metadata containing NaN/Infinity and test both databases.
