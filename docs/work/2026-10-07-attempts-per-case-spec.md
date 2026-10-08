---
ticket: OME-1458
stack: repo
status: done
started: 2026-10-07
finished: 2026-10-07
---

# attempts-per-case-spec — decide how a Benchmark with several Attempts per Case is scored (PR 1 of 7)

## Intent

Write the decision OME-1458 asks for: how a Benchmark that allows several Attempts per question
(ARC-AGI-2's two Attempts, ZeroBench's pass@5) is declared, run, graded and reported, so its
score is the number its authors publish. The decision is the spec, the plan says how; the build
is PRs 3 to 7 on the same ticket.

## Planned changes

- `docs/plan/2026-10-08-OME-1458-attempts-per-case.md` — the plan for PRs 3 to 7.
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
- PR 2 of 7 (the importer refuses `epochs` > 1) follows; the build is PRs 3 to 7 on the same
  ticket, and PR 7 closes OME-1458.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** 379749d08 docs(screamingface-engine): spec several Attempts per Case, any-match per Check · 893995cc6 docs(screamingface-engine): explain the cache trap and the per-Check fold with examples · d1a235710 docs(screamingface-engine): name the build tickets OME-1515 and OME-1516 in the spec · c25175c97 docs(screamingface-engine): give each unseeded Attempt its own cache entry so a rerun replays every Attempt · 18e354ffc docs(screamingface-engine): carry the build on OME-1458 as one six-PR stack · 8e760d5ff docs(screamingface-engine): plan the Attempts build as PRs 3 to 7 and amend the spec where the code disagreed (PR #1294)
- **Gates:** docs only; three mermaid diagrams rendered and read.
- **Deviations:** two owner-approved decisions were revised after reading the code, both marked
  in the spec's §1. D5: "one seed per Attempt" would refuse every Anthropic model, so an unseeded
  run uses the gateway's cache opt-out for Attempt 2 and later. D7: "best Attempt per Case"
  undercounts ARC-AGI-2's multi-grid tasks, so the fold is per Check. D5 extended 2026-10-08 (owner): an unseeded Attempt i ≥ 2 carries its Attempt number in the gateway's cache control instead of opting out, so a rerun replays every Attempt (the gateway change, PR 4). D14 changed 2026-10-08 (owner): the build rides OME-1458 as PRs 3 to 6, not separate tickets. The plan (2026-10-08) made it PRs 3 to 7: the code put the fold in the shared marking room, pinned the failure code on both lists, and was too large for one Engine PR.
