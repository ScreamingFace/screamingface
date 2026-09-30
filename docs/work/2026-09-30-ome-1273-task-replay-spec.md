---
ticket: OME-1273
stack: repo
status: done
started: 2026-09-30
finished: 2026-09-30
---

# ome-1273-task-replay-spec — the spec for importing Benchmarks whose Cases the importer can't see

## Intent

OME-1273's design was agreed in conversation on 2026-09-30 (decisions recorded on the ticket).
This unit writes it down as the reviewable spec in `docs/spec/`, and adds the two glossary
entries it introduces (Case Source, Case Digest) plus the Case Preparation amendment to
`CONTEXT.md`. Docs only; the code is the follow-up PR stack the spec defines.

## Planned changes

- `docs/spec/2026-09-30-OME-1273-task-replay-import.md` (new).
- `CONTEXT.md`: add Case Source and Case Digest; amend Case Preparation.
- `docs/work/2026-09-30-ome-1273-task-replay-spec.md` (this ledger).

## Test plan

- No code. Self-review for placeholders, contradictions, ambiguity and scope; every symbol the
  spec names is grepped against `upstream/main` (`d4685cae` or later).

## Acceptance

- The owner reviews and approves the written spec before any plan or code.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `docs/spec/2026-09-30-OME-1273-task-replay-import.md`, `CONTEXT.md`,
  `docs/diagrams/2026-09-30-OME-1273-{before-after,architecture}.{drawio,png}`,
  `docs/tasks/2026-09-23-OME-1273-task-replay-import.md` (the ticket had no mirror yet), this ledger.
- **Commits:** one docs commit on `OME-1273-task-replay-spec`.
- **Gates:** docs only, no code gates. Every symbol the spec names was checked against main
  `42baa988`: the four routed refusals (`importer.py` :190, :491, :508, :518), `CasesSpec`,
  `_template_attribute`, `SKIPPED_MARKER`, the published-revisions test (17 revisions), the
  `image` job in `screamingface-engine-tests.yml`, and the fetch primitives in inspect-ai 0.3.263
  and inspect-evals 0.20.0.
- **Deviations:** the ticket says three refusals route to Task replay; there are four (the
  task-local `record_to_sample` one also blocks chembench, DROP and pre_flight). The ticket's
  PR 3 is split, with scorer lookup in helper files moved to its own PR, to stay under the
  500-line cap. The owner approved all three on the PR (2026-09-30), plus the
  strict job's cost (every Engine PR fails while an upstream source is broken).
  Owner-verify: approve the spec before any plan or code.
