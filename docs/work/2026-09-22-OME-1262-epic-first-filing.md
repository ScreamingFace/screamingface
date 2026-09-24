---
ticket: OME-1262
stack: repo
status: in_progress
started: 2026-09-22
finished:
---

# OME-1262 — Write epic-first filing into the SDLC skills and docs

## Intent

Session-triggered filing was creating orphan tickets under sprint milestones the team no longer works to. This unit writes the epic-first rule into the skills and docs so a new session cannot file a leaf that has no parent epic. Parent epic: `OME-1259`.

## Planned changes

- `.claude/skills/task-management/SKILL.md`
- `.claude/task-board.local.md`
- `CLAUDE.md`
- `.claude/README.md`
- `.claude/agents/ticket-filer.md`
- `.claude/agents/sdlc-unit-executor.md`
- `docs/spec/2026-07-08-ai-sdlc-adoption-spec.md` (superseding block only)
- `docs/plan/2026-09-22-OME-1262-epic-first-filing.md`
- `docs/tasks/` mirrors for `OME-1259`, `OME-1260`, `OME-1261`, `OME-1262`

### Added scope (2026-09-24) — ledger/ticket reconciliation (Option A)

PR-time filing left `sdlc-python`/`sdlc-electron` (SHARED-LOOP), card D8, the ledger TEMPLATE,
and `CLAUDE.md` rule 2 still demanding a ticket id during coding. Folded the fix in here (per
the fold-into-active-ticket preference) rather than a new sub-issue:

- `docs/spec/2026-09-24-ledger-slug-pr-time-filing-reconciliation.md` (this decision)
- `.claude/skills/sdlc-python/SKILL.md` + `.claude/skills/sdlc-electron/SKILL.md` — rule 1,
  step 1, step 11 (SHARED-LOOP, edited **verbatim in both**; parity must stay green)
- `.claude/sdlc.local.md` — D8 ledger naming (slug, `ticket: unfiled`)
- `docs/work/TEMPLATE.md` — `ticket: unfiled`
- `CLAUDE.md` — rule 2 ledger name (missed by the original OME-1262 edit)

Applied 2026-09-24: all six edits above + a mechanical `task-management` fix ("in-progress at
ledger creation" → "…when the issue is filed at PR-open"). `check_loop_parity.py` → LOOP
PARITY OK; no residual coding-phase `ticket-id` refs. Three further contradictions found (spec's "Contradiction scan"):
- **Fork A — RESOLVED (rename at PR-open):** branch is `<slug>` at work start, renamed to
  `OME-N-<desc>` at PR-open. Edited `CLAUDE.md` rules 5 & 6 + `working-in-this-repo` §6.
- **Fork B — RESOLVED (universal; dispatch = confirmation):** reworked
  `.claude/agents/sdlc-unit-executor.md` — input is unit + epic, files at PR-open, renames
  branch, backfills ledger; pre-filing STOPs return `blocked` in the return value.
- **Fork C — RESOLVED (repurpose):** rewrote `.claude/agents/ticket-filer.md` as the
  mechanical single-leaf PR-open filer (one implemented leaf → file under its epic,
  self-assigned; caller backfills ledger + mirror). Bug path preserved.
- Decision log completed: added **D23–D26** (ledger-slug, branch rename, universal/executor,
  ticket-filer) to `docs/spec/2026-07-08-ai-sdlc-adoption-spec.md`, pointing at the new spec.

## Test plan

- `uv run .claude/scripts/check_loop_parity.py` — the sdlc shared loop stays byte-identical
  across both skills (edits mirrored).
- `grep -n "ticket-id" .claude/skills/sdlc-*/SKILL.md .claude/sdlc.local.md CLAUDE.md` — no
  coding-phase hits remain.
- Search the process docs for "sprints are milestones" and confirm it is gone.

## Acceptance

- An agent-filed leaf requires `parentId`.
- No fitting epic is a hard stop: the agent proposes an epic and does not file.
- Milestones are described as optional.
- The product reviewer handle is marked pending, not invented.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the planned set, all on `OME-1262-epic-first-filing`. Not committed yet.
- **Commits:** none yet.
- **Gates:** `uv run .claude/scripts/check_loop_parity.py` → `LOOP PARITY OK`. Search for "Sprints are milestones" / "Sprints = the project's milestones" in the edited process docs → no hits.
- **Deviations:** the product reviewer handle is recorded as pending rather than guessed. The no-epic park state is Triage. `OME-1261` triage and `OME-1260` owner UI are filed and not executed in this unit.
