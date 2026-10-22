---
id: OME-1610
linear_url: https://linear.app/openmined/issue/OME-1610/change-a-benchmarks-published-version-only-on-purpose-never-as-a-side
status: in_progress
type: task
priority: high
labels: [screamingface-engine, agentic, design-session]
parent: OME-1299
created: 2026-10-15
closed:
---

# Change a Benchmark's published version only on purpose, never as a side effect of a code change

Every Benchmark publishes a version ID (its revision); submissions and the leaderboard group
results by it. Before this ticket most Benchmarks published an ID computed from their
definition, source code included, so a code move with an unchanged exam emptied draco-3pass's
leaderboard (OME-1527).

- **PR 1 (this branch, stacked on OME-1701):** every Benchmark hand-sets its published ID at
  today's value, so none moves; each Benchmark's computed fingerprint is pinned in a test as the
  alarm; `just engine benchmark-bump <key>` prints the WARNING and the lines to edit; the rule is
  written in the Engine's Benchmark guide, the code notes, the test messages and every local Task
  README.
- **Then:** a written version policy (what counts as an exam change, how a move is announced and
  shown on the leaderboard, who approves), reviewed by product.

- 2026-10-16: owner decisions: medxpert in scope; bump = script + just recipe; loud written rule.
- 2026-10-22: owner decisions: stack on OME-1701; enforce with a catalogue test (the field stays
  optional for test stand-ins); the rule uses the frozen-revisions bar (move only on a changed
  Case set or a new Benchmark); 7 prior identity tests read the fingerprint instead of the
  published id.
- Ledger: `docs/work/2026-10-16-hand-set-published-revision.md`.
