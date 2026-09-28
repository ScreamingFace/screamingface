---
id: OME-1331
linear_url: https://linear.app/openmined/issue/OME-1331/reconcile-the-label-registry-and-add-component-blocked-epic
status: in_review
type: task
priority: 3
labels: [repo-dev-processes, agentic, autonomous]
created: 2026-09-24
closed:
---

# Reconcile the label registry and add component / blocked / epic-classification rules

Follow-on to the epic-first work (OME-1259/OME-1262). Reconciles `.claude/task-board.local.md` to a
live-Linear label snapshot and codifies three rules across the card, `task-management`,
`working-in-this-repo`, and `CLAUDE.md`: component/landing label mandatory on every issue;
epic-classification (the `epic` group's leaves) is the epic marker and only epics carry it; `blocked`
allowed only with a named blocker (label + blocked-by relation). Parent epic: OME-1259.
