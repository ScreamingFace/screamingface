---
ticket: OME-1404
stack: screamingface-engine
status: in_progress
started: 2026-09-29
finished:
---

# glossary-renames — rename the engine's benchmark code to the `CONTEXT.md` glossary

## Intent

A newcomer to the engine's benchmark code has to learn a private dialect first ("board", "exam",
"bake", "spine", "row", "verdict", …). Several of those words mean something else in the
project glossary (`CONTEXT.md`): "board" is its avoid word for Leaderboard, "row" for Case.
This unit renames the internal Python names to glossary words and adds glossary entries for the
words that stay. It's a pure rename: no behaviour, revision or wire string changes.

The spec is the Linear issue itself (three rename tables, eight glossary drafts, two owner
decisions: one PR, and "bake" goes). This ledger does not copy the tables.

## Planned changes

One PR, one commit per rename group, each passing the gates on its own:

1. `CONTEXT.md`: the Recipe fix and the eight new entries.
2. The inspect plugin's own names (first table, minus board / exam / bake).
3. "board" → benchmark across core and plugin.
4. "exam" → variant, and "row" → case grade.
5. `spine/` → `shared_grading/`, `ScoredPath`, stage → phase, `bind_*`, DRACO tasks, smaller names.
6. The wire-contract Python names (draft feedback, case grade, loop outcome, graded answer,
   judge evidence), keeping every wire string.
7. "bake" → "prepare" in code, living engine docs, Dockerfiles and CI comments.

Tooling: a token-aware renamer (NAME tokens renamed exactly; comments and docstrings get the
prose pass; wire strings masked), so string literals a client reads can't change by accident.

## Test plan

- A rename adds no behaviour, so no new tests. The proof is that nothing observable moved:
  - a fingerprint of all 35 registered boards (revision, rendered URL4 protocol, catalogue
    fields, asset bundle id), taken on `main` before the first commit and diffed after each
    group: it must stay byte-identical;
  - ruff, ruff format, pyright, the layering check, the full engine suite and the inspect lane
    after each group.

## Acceptance

- Each "Today" name in the ticket's three tables greps to 0 in the engine, apart from the wire
  strings each row keeps.
- The fingerprint of all 35 boards stays byte-identical to `main`.
- Full engine suite + inspect lane pass with the same failures as `main` (see Deviations).
- `CONTEXT.md` has the Recipe fix and the eight entries.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
