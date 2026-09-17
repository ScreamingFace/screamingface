---
id: OME-865
linear_url: https://linear.app/openmined/issue/OME-865/rename-the-scoreboard-verification-field-to-verified-by-screamingface
status: In Review
type: task
priority: P1
labels: [scoreboard, agentic, autonomous, task]
created: 2026-08-17
closed:
---

# Rename the Scoreboard verification field to verified_by_screamingface

`OME-858` (#622) renamed this field in the ScreamingFace Client and made its decoder strict.
Scoreboard still emitted `verified_by_openmined`, so the two contracts disagreed and every
leaderboard read failed:

```
sf.leaderboards.get('draco')
→ LeaderboardError: Leaderboard entry verified_by_screamingface must be a boolean
```

Reproduced against `origin/main` before starting. This blocked `OME-402` (the leaderboard
notebook, the path testers submit through) and any Client ↔ Scoreboard end-to-end run.

Renames the field across the model, response schemas, routes, store projections, portal JS and
tests, and adds migration `0005` using `RenameField` so existing rows keep their values.
`0001_initial.py` is left untouched — it records applied history.

Semantics are deliberately unchanged: no badge, filter, ranking rule or reproduction claim is
introduced, and the field stays server-owned. Defining a trustworthy signal remains `OME-821`.

Ledger: `docs/work/2026-08-17-OME-865-rename-verified-field.md`
