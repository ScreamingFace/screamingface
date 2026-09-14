---
ticket: OME-1102
stack: repo
status: in_progress
started: 2026-09-14
finished:
---

# OME-1102 — Write the adding-a-benchmark guide and review the grade_case hook as a public seam

## Intent

The epic (`OME-1024`) claims a new benchmark is one author module (~50–150 lines) plus a
dataset mapping and tests, with zero edits to existing benchmarks or shared tests. That
claim is only verifiable as a written procedure a stranger can follow. This unit writes
that procedure (`apps/screamingface-engine/docs/adding-a-benchmark.md`) now that both
grading modes are live on the spine (draco `OME-1100`, ifeval `OME-1101`, MedX `OME-1149`),
and reviews the `grade_case` signature against an external in-enclave judge shape so the
seam is a reviewed contract, not an accident of extraction.

## Planned changes

- Create `apps/screamingface-engine/docs/adding-a-benchmark.md` — the author walk-through:
  two-axis choice (interaction × grading mode), case-row shape + envelope kinds,
  `grade_case` per grading mode with a worked example, declaration record
  (`failure_policy`, `interaction`), registry entry, prepared assets, e2e onboarding
  (link the existing e2e README).
- Record the `grade_case`-vs-external-judge review as a decision section in the doc.
  Any behavior-touching signature fix spins out to its own ticket/PR.
- Mirror `docs/tasks/2026-09-14-OME-1102-adding-a-benchmark-guide.md` (created this unit —
  none existed).

## Test plan

- Doc-only unit: the acceptance test is a dry run of MedXpertQA's actual row mapping
  (merged in `OME-1149`) against the doc — every step the module needed must be named.
- Existing engine test suite stays untouched and green (no code changes planned).

## Acceptance

- The doc exists; the MedXpertQA dry run needs no step the doc does not name.
- `grade_case` signature and `failure_policy` values stated in the doc with a worked example.
- The external-judge review pass is recorded as a decision in the doc.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
