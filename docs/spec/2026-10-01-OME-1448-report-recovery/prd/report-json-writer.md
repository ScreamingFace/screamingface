# PRD: Streaming report.json writer (component)

**Source:** prompt (OME-1448 option D) / ans:Q1, Q9 · **Priority:** P0
**Lifecycle:** existing (characterize + delta) · **Owner:** @ionesio

## 1. Summary and flows served

One writer emits `report.json` one Candidate at a time, and keeps the bytes identical to today's
`Report.to_json()`. It serves:
- `prd/export-report.md`: `Report.export()` writes through it (option D). `[stated ans:Q1]`
- `prd/recover-evaluation.md`: recover-to-file writes through it without building a `Report`.
  `[stated ans:Q9]`

It has its own invariant (byte identity) that neither flow owns alone, so it gets its own PRD.

## 2. Background and constraints

- "`report.json` written by `Report.export()` stays byte-identical for runs that fit in memory.
  The golden tests pin it." `[stated prompt]`
- "⑥ builds the whole JSON as one string, then writes it … a second 2 GB copy before a byte lands
  on disk." `[stated prompt]`

### 2.1 Current behavior

- `Report.to_dict()` returns the keys `schema`, `started_at`, `completed_at`, `benchmark`,
  `candidates`, `usage`, in that order.
  `[existing packages/screamingface/src/screamingface/report.py:454]`
- `Report.to_json()` is `json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))`.
  `[existing packages/screamingface/src/screamingface/report.py:464]`
- `Report.usage` is `_combined_usage(tuple(c.usage for c in candidates))`.
  `[existing packages/screamingface/src/screamingface/report.py:439]`
  `_combined_usage` sums a field only when every Candidate reported it.
  `[existing packages/screamingface/src/screamingface/report.py:686]`
- `started_at` is the earliest Candidate start, and `completed_at` is the latest Candidate end
  (`Report` properties). `[existing packages/screamingface/src/screamingface/report.py:393]`

**Delta:** add `write_report_json(fp, *, started_at, completed_at, benchmark, case_count,
candidates: Iterable[CandidateResult])`. It writes the same bytes as `to_json()` while it holds
only one `CandidateResult.to_dict()` at a time. `to_json()` stays, and returns the writer's
output for small Reports. `[proposed]`

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**RW-H1. Byte identity.** `[stated prompt]`
Given any valid `Report`,
When the writer writes it to a binary file,
Then the file bytes equal `report.to_json().encode("utf-8")`.

**RW-H2. One Candidate in memory.** `[stated ans:Q9]`
Given an iterable that yields Candidates one at a time,
When the writer runs,
Then it builds at most one `CandidateResult.to_dict()` at a time, and it computes `usage` from
the Candidates' `usage` values as it goes.

### 3.2 Error paths

**RW-E1. The iterable raises mid-way.** `[implied]`
Given an iterable that raises on Candidate 3 of 11,
When the writer runs,
Then the exception reaches the caller unchanged, and the writer has written no closing bracket.
The caller owns the atomic replace (see EX-D1 and RC-D5).

### 3.3 Derived scenarios (risk order)

**RW-D1. Non-ASCII and escape-heavy text.** `[proposed — gap §per-flow/boundary]` · H × M
Given case text with emoji, RTL text, `"`, `\`, control characters, and lone surrogates that
`json.dumps` escapes,
When the writer writes,
Then the bytes still equal `to_json()`.

**RW-D2. Usage parity.** `[implied]` · H × M
Given Candidates where one has no `cost_usd`,
When the writer computes `usage`,
Then it equals `Report.usage.to_dict()` (the field is null, not a partial sum).

**RW-D3. One Candidate and many Candidates.** `[proposed — gap §per-flow/boundary]` · M × M
Given 1 Candidate, and given 11 Candidates,
Then the separators between Candidates match `json.dumps` exactly (no trailing comma).

**RW-D4. Report-level validation in file mode.** `[implied]` · H × L
Given Candidates that `Report.__init__` would refuse (two equal names, or a different benchmark),
When the writer receives them,
Then it raises the same error type and message that `Report.__init__` raises
(`report.py:400`). It checks the unique names before the first byte (the caller passes them up
front, from the manifest). It checks the benchmark and the Case count of each Candidate before it
writes that Candidate. The caller's atomic write (K8) keeps the target untouched in both cases.

## 4. Non-functional requirements

- Peak extra memory: at most one Candidate's `to_dict()` plus a 1 MiB write buffer. `[proposed]`
- Throughput: within 20 % of `to_json()` + `write_text()` for a 50 MB Report. `[proposed]`

## 5. Out of scope

- The inspect `.eval` export. `[implied]`
- Streaming the decode of a single Candidate (option B). `[stated ans:Q1]`

## 6. Open questions

None.

## 7. TDD plan

Build core-out. Characterization tests come first and pass on today's code.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| RW-0 | CHAR `existing_export_golden_bytes_are_pinned` (the existing tests `test_report.py:183`, `:470` stay green unchanged) | unit | §2.1 | — | none: passes today |
| RW-1 | `streaming_writer_bytes_equal_to_json` (property: hypothesis Report strategy, 1–11 Candidates) | unit | RW-H1, RW-D3 | H×H | write header, then `json.dumps(c.to_dict(), …)` joined with `,`, then usage |
| RW-2 | `escape_heavy_and_non_ascii_text_stays_identical` | unit | RW-D1 | H×M | same `json.dumps` flags per fragment |
| RW-3 | `usage_is_combined_like_report_usage_when_a_field_is_missing` | unit | RW-D2 | H×M | call `_combined_usage` on the collected `Usage` values |
| RW-4 | `writer_holds_one_candidate_dict_at_a_time` (tracemalloc peak < 1.5 × largest Candidate) | unit | RW-H2 | H×M | consume the iterator lazily |
| RW-5 | `report_init_rules_are_enforced_with_the_same_errors` (equal names before the first byte; wrong benchmark or Case count before that Candidate) | unit | RW-D4 | H×L | share one validator with `Report.__init__` |
| RW-6 | `iterator_error_propagates_without_closing_the_document` | unit | RW-E1 | M×L | no `finally` that closes the JSON |

Refactor on green: make `Report.to_json()` call the writer on an in-memory buffer, so there is
one encoder in the codebase. RW-0 and RW-1 must stay green.
