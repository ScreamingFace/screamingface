---
ticket: OME-1102
stack: repo
status: done
started: 2026-09-14
finished: 2026-09-15
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

- **Actual files:** as planned, plus a diagram-first rework on owner feedback:
  `apps/screamingface-engine/docs/adding-a-benchmark.md` +
  `apps/screamingface-engine/docs/diagrams/` (5 diagrams, `.drawio` + PNG:
  authoring-seam, two-axes, grade-case-hourglass, failure-ladder-and-policy from this
  unit; benchmark-onboarding-steps added by the owner), plus this ledger + mirror.
- **Commits:** b58a866e — docs(screamingface-engine): write the adding-a-benchmark
  author guide; 5871e86f — docs(screamingface-engine): make the adding-a-benchmark guide
  diagram-first; f5abae23 — 8 steps diagram + pointers (owner); merged as PR #934
  (d0f16a6e).
- **Gates:** pre-push engine gates ALL GREEN both pushes (ruff check/format, pyright,
  layering, pytest cov≥80). Acceptance dry run: every step MedXpertQA's merged module
  needed is named in the doc; `grade_case` + `failure_policy` stated with worked
  examples; seam review recorded as a decision in the doc.
- **Deviations:** external-judge review ran against the epic's description of the
  in-enclave judge, not a contract doc from its owners (caveat recorded in the doc's
  Decision section). Stale `BenchmarkDeclaration` docstring (`single_shot` only) flagged
  in the PR, left out of this doc-only unit. Docs closed via this fallback PR instead of
  a last pre-merge commit — the owner merged before the flip.
