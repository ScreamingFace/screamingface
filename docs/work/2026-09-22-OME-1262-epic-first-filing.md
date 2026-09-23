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

## Test plan

- `uv run .claude/scripts/check_loop_parity.py` — the sdlc shared loop is untouched.
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
