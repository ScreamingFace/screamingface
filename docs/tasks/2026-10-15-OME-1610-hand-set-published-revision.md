---
id: OME-1610
linear_url: https://linear.app/openmined/issue/OME-1610/change-a-benchmarks-published-version-only-on-purpose-never-as-a-side
status: done
type: task
priority: high
labels: [screamingface-engine, agentic, design-session]
parent: OME-1299
created: 2026-10-15
closed: 2026-10-22
---

# Change a Benchmark's published version only on purpose, never as a side effect of a code change

Every Benchmark publishes a version ID (its revision); submissions and the leaderboard group
results by it. Before this ticket most Benchmarks published an ID computed from their
definition, source code included, so a code move with an unchanged exam emptied draco-3pass's
leaderboard (OME-1527).

This change makes every Benchmark hand-set its published ID at today's value, so none moves;
pins each Benchmark's computed fingerprint in a test as the alarm; adds
`just engine benchmark-bump <key>`, which prints the WARNING and the lines to edit; and writes the
version policy in the Engine's Benchmark guide ("Changing a Benchmark's published revision"):
what moves an ID (a changed Case set or a new Benchmark), who approves (the owner), and how a
move is announced (a CHANGELOG line and a team post). Every local Task README, the code notes and
the test messages point to it. How the leaderboard shows an old and a new version side by side is
left to product; it gets its own ticket if they want it.

- 2026-10-16: owner decisions: medxpert in scope; bump = script + just recipe; loud written rule.
- 2026-10-22: owner decisions: stack on OME-1701; enforce with a catalogue test (the field stays
  optional for test stand-ins); the rule uses the frozen-revisions bar (move only on a changed
  Case set or a new Benchmark); 7 prior identity tests read the fingerprint instead of the
  published id; the guide's section is the version policy, so this ticket closes with the PR.
- Ledger: `docs/work/2026-10-16-hand-set-published-revision.md`.
