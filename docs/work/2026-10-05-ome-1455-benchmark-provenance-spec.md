---
ticket: OME-1455
stack: repo
status: done
started: 2026-10-05
finished: 2026-10-05
---

# ome-1455-benchmark-provenance-spec — spec, plan and glossary for Benchmark Provenance (PR 1 of 4)

## Intent

Every Benchmark must say where it comes from (paper, authors, citation, contributors, website,
harness, dataset, licence), how big it is, whether its prompts need a content warning, how humans
and frontier models score on it, and how to run it, with the Engine deriving one saturation
verdict from the frontier headroom. This unit writes the design down so the code PRs can follow
it without re-deciding anything: the spec, the plan for the three code PRs, and the four
`CONTEXT.md` glossary entries (Benchmark Saturation, Frontier Score, Human Baseline, Benchmark
Provenance). Owner decision 2026-10-05: backend first, so new Benchmarks carry the fields before
the pages render them; the UI PR waits on product sign-off of the mockup.

## Planned changes

- `docs/spec/2026-10-05-OME-1455-benchmark-provenance.md` — the design: fields, saturation rule,
  the four-PR carve, the grandfather allowlist that makes the conformance test strict for new
  Benchmarks from the first code PR, failure modes, known limitations.
- `docs/plan/2026-10-05-OME-1455-benchmark-provenance.md` — ordered steps per code PR with the
  file and the verifying test for each.
- `CONTEXT.md` — four glossary entries, wording from the ticket's Tasks section.
- `docs/tasks/2026-10-05-OME-1455-benchmark-provenance.md` — the issue mirror (ticket filed
  2026-10-02; mirror owed since).
- This ledger.

## Test plan

- Docs-only unit: no code, no tests. Verification is a review pass: every symbol the spec names
  exists on `upstream/main` at the quoted path; every mermaid block renders through `mmdc`;
  the glossary entries follow the `**Term**: / _Avoid_:` shape.

## Acceptance

- Spec and plan committed; a dev can name the files each code PR opens from the plan alone.
- Spec states the four-PR carve and the allowlist rule; ticket's Scope section patched to match.
- `CONTEXT.md` carries the four entries.
- Mirror exists with the ticket's id, URL, labels and status.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: the spec, the plan, four `CONTEXT.md` entries, the mirror, this
  ledger. No code.
- **Commits:** `9281b2ab2` — docs(engine): spec, plan and glossary for Benchmark Provenance and saturation; PR [#1234](https://github.com/ScreamingFace/screamingface/pull/1234) (draft).
- **Gates:** `uv run .claude/scripts/run_gates.py repo` — ALL GATES GREEN (mirror-status gate
  included). The spec's mermaid block rendered through `mmdc` and read: two stacked lanes.
  Every symbol and path the spec and plan name was grepped on this branch.
- **Deviations:** three design choices the ticket did not fix, named in the spec for owner
  review: (1) four PRs, pages last, with a grandfather allowlist so the conformance test is
  strict from the backend PR (owner direction 2026-10-05); (2) the size cross-check runs in the
  conformance test, not at Engine boot (spec §3.1); (3) the Scoreboard copies the block as one
  JSON column plus a flat `saturation` column, not one column per key (spec §4.1). The ticket's
  Scope section is patched to the carve; (2) and (3) are stated there as deviations.
- **Owner-verify:** review the three choices above on the PR; patch the spec if any is reversed.
