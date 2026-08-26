---
id: OME-924
linear_url: https://linear.app/openmined/issue/OME-924/preserve-upstream-grading-errors-in-model-graded-benchmarks
status: in_progress
type: fix
priority: high
labels: [screamingface-engine, url4, agentic]
created: 2026-08-20
closed:
---

# Preserve upstream grading errors in model-graded benchmarks

Fix for GitHub #740 / OME-993: a judge failure inside a model-graded benchmark was masked
as "invalid Criterion envelope" (`draco_grading_failed`) because url4's default
`on_error="collect"` turned the failed judge branch into an error-shaped item in the
criterion/rubric fan-out, which the case-evaluation route then decoded as a typed grading
record. The original upstream error (e.g. OpenRouter 429 → `rate_limited`) never reached
the report.

## Fix

- Inner fan-outs now fail fast: DRACO criteria iteration and HealthBench rubric-item
  iteration declare `on_error="fail"`, so the original error propagates to the shared
  `preserve_candidate_outcome()` boundary (which still collects per Case).
- url4 `_error_payload` keeps the exception's `code` and `retryable` (from `permanent`)
  beside `kind`/`message`, so `public_error` renders the upstream failure instead of the
  benchmark default.

## Acceptance

- Simulated judge 429 in DRACO reports `rate_limited`, original message, `retryable=true`,
  never "invalid Criterion envelope".
- HealthBench equivalent; candidate answer retained; affected case unscored.
- Permanent judge failures keep `retryable=false`.
- Successful grading unchanged (protocol hashes updated deliberately; DRACO revision
  fingerprint untouched).

Ledger: `docs/work/2026-08-26-OME-924-preserve-grading-errors.md`
