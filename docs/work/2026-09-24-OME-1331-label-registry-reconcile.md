---
ticket: OME-1331
stack: repo
status: done
started: 2026-09-24
finished: 2026-09-24
---

# OME-1331 — Reconcile the label registry and add component / blocked / epic-classification rules

## Intent

Bring the checked-in label registry back in lockstep with live Linear after a session of label
consolidation and renames, and codify three process rules the taxonomy now depends on.

## Planned changes

- `.claude/task-board.local.md` — reconcile `labels:` to a live snapshot; add rules.
- `.claude/skills/task-management/SKILL.md` — mandatory-component, epic-classification, blocked.
- `.claude/skills/working-in-this-repo/SKILL.md` — routing-table pkg renames.
- `CLAUDE.md` — epic-classification + blocked note.

## Rules added

- Component/landing label MANDATORY on every issue (no default; ≥2 components → epic split).
- Epic-classification (`tech-debt`/`product-feature`/`infra`) is the epic marker — `epic` is a
  single-select group whose leaves are the classifications; only epics carry it, non-epics carry
  a component.
- `blocked` allowed only with a named blocker → sets both the label and the blocked-by relation.

## Acceptance

- Card `labels:` matches a fresh `list_issue_labels team=Engineering` pull.
- No active stale label references; `check_loop_parity.py` green.

## Outcome

- **Actual files:** the four planned files (task-board.local.md, task-management, working-in-this-repo, CLAUDE.md).
- **Commits:** `dffaa9fe` reconcile + require component; `ef80ce8d` trim + blocked + epic-classification.
- **Gates:** `check_loop_parity.py` → LOOP PARITY OK; no residual coding-phase `ticket-id`; no conflict markers.
- **Deviations:** the Linear label mutations (merges, renames, `epic2` retirement) were owner-directed
  and done live during the session; this unit is the doc reconciliation. Ledger backfilled at PR-open.
