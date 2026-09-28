---
id: OME-1179
linear_url: https://linear.app/openmined/issue/OME-1179/epic-compute-pareto-frontier-openness-from-submitted-model-identities
status: Backlog
type: decision
priority: 2
labels: [scoreboard, human, design-session]
created: 2026-09-10
closed:
---

# EPIC: Compute Pareto-frontier openness from submitted model identities

Cross-landing epic. The Scoreboard has no structured candidate-model field, so it cannot tell
an open-weights model from the reseller that carried it. Blocks `OME-1145`.

One sub-issue per landing, per the cross-cutting rule:

| sub-issue | landing | state |
| -- | -- | -- |
| `OME-1181` | `scoreboard` | built, PR #922, ships and **deploys** first |
| `OME-1180` | `py-screamingface` | built, PR #923 held in draft, ships second |

## Contract

> Of the entries on the full-board cost/score Pareto frontier, report how many are open. An
> entry is open when every declared model route it names has downloadable, locally runnable
> weights. Any closed model — or any model the registry does not recognise — makes the whole
> entry closed.

## Decisions taken

| # | outcome |
| -- | -- |
| D1 | Any-closed-wins, per **entry**. The unit is the submission, not the model. |
| D2, D3 | Moot under D1 — neither counts models. |
| D4 | Unrecognised fails closed, and the miss must be made visible. Exposure belongs to `OME-1145`. |
| D5 | Superseded. `openness_override` has no application write path and loses its consumers. |
| Q1 | "Open" means weights you can download and run, whatever the licence says about commercial use. |
| Q2 | `models` stays off `LeaderboardEntry`. **Corrected**: `ScoreSchema` is itself public, so the field carries `exclude_if`. |
| Q3 | A same-owner replay may **fill** a null value. **Corrected**: never replace a populated one. |

Q2 and Q3 were both corrected after review of PR #922 — see the ledger for the evidence.

## Artifacts

- Review that drove this epic: `docs/work/2026-09-10-OME-1145-openness-metric-review.md`
  and its companion feedback document
- Sub-issue artifacts live with their own mirrors

Related: `OME-1145` (the bug), `OME-772` (recorded the gap on 2026-08-11), `OME-323` (built the
statistic).
