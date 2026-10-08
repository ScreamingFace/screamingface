---
ticket: OME-1458
stack: repo
status: in_progress
started: 2026-10-07
finished:
---

# attempts-per-case-spec — decide how a Benchmark with several Attempts per Case is scored (PR 1 of 6)

## Intent

Write the decision OME-1458 asks for: how a Benchmark that allows several Attempts per question
(ARC-AGI-2's two Attempts, ZeroBench's pass@5) is declared, run, graded and reported, so its
score is the number its authors publish. The decision is the spec; the build is PRs 3 to 6 on
the same ticket.

## Planned changes

- `docs/spec/2026-10-07-OME-1458-attempts-per-case.md` — the spec (D1–D14, design, Data Flow,
  Failure modes, Architecture, limitations, acceptance, delivery).
- `CONTEXT.md` — the `Attempt` glossary entry.
- `docs/tasks/2026-10-02-OME-1458-attempts-per-question.md` — the mirror.
- This ledger.

## Test plan

- Docs only. Every mermaid block rendered with `mmdc` and read before commit.
- Every code claim in the spec checked against `upstream/main` (`f3e3c6f5d`) and the pinned
  `inspect_ai` 0.3.263; every external claim against a pinned commit or the paper.

## Acceptance

- The owner approves the spec in plain words.
- PR 2 of 6 (the importer refuses `epochs` > 1) follows; the build is PRs 3 to 6 on the same
  ticket, and PR 6 closes OME-1458.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** <sha — message>
- **Gates:** docs only; three mermaid diagrams rendered and read.
- **Deviations:** two owner-approved decisions were revised after reading the code, both marked
  in the spec's §1. D5: "one seed per Attempt" would refuse every Anthropic model, so an unseeded
  run uses the gateway's cache opt-out for Attempt 2 and later. D7: "best Attempt per Case"
  undercounts ARC-AGI-2's multi-grid tasks, so the fold is per Check.
