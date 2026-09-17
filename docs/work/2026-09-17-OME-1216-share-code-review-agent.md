---
ticket: OME-1216
stack: repo
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1216 — Share the code-review agent guide with the team

## Intent

The repo's code-review agent guide (seven review lanes, context recipe, severity
triage, noise list — mined from ledger + PR history) lived in a personal untracked
directory, so only one person's sessions could use it. Move it into tracked
`.claude/agents/` so every teammate and agent session reviews with the same playbook.

## Planned changes

- Create `.claude/agents/sf-code-review.md` — copy of the personal doc with three
  shareability edits: date-stamped history counts, four-beat format declared as the
  required output shape, codify-loop ownership rules (changes land via PR, cited
  evidence, never single-session appends).
- This ledger + mirror `docs/tasks/2026-09-17-share-code-review-agent.md`.

## Test plan

- Docs-only change; no code paths. Verify: no personal names/paths in the doc
  (grep), file anchors it cites exist in the repo.

## Acceptance

- Doc present in `.claude/agents/`, PR open, no `.dk`/personal references inside.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned
- **Commits:** 9c103204 — docs(repo): share the code-review agent guide in .claude/agents (+ the close-docs commit)
- **Gates:** docs-only; pre-commit hooks passed; grep verified no personal names/paths in the shared doc
- **Deviations:** none
