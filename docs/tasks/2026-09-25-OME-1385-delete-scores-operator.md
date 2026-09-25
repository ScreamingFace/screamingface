---
id: OME-1385
linear_url: https://linear.app/openmined/issue/OME-1385/add-an-operator-command-that-deletes-named-scores-from-a-public-board
status: in_review
type: task
priority: high
labels: [scoreboard, agentic, autonomous]
parent: OME-1251
created: 2026-09-25
closed:
---

# Add an operator command that deletes named scores from a public board

The tool `OME-1384` needs: `python -m scoreboard.delete_scores`, run through firecall with
`kubectl exec deploy/scoreboard` the way `OME-986` ran `retire_benchmark`.

Ledger: `docs/work/2026-09-25-delete-scores-operator.md`.
Spec: `docs/spec/2026-09-25-delete-scores-operator.md`.
Plan: `docs/plan/2026-09-25-delete-scores-operator.md`.

- 2026-09-25: filed at the owner's request, built the same day.
