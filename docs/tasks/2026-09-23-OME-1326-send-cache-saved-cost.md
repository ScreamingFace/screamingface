---
id: OME-1326
linear_url: https://linear.app/openmined/issue/OME-1326/send-the-cache-saved-cost-on-a-leaderboard-submission
status: in_review
type: task
priority: high
labels: [client-sf, agentic, deferred]
parent: OME-1251
created: 2026-09-23
closed:
---

# Send the cache saved cost on a leaderboard submission

Client half of decision D5 on epic `OME-1251`. The Scoreboard half is `OME-1325` (PR #1055,
merged as `494a5fa3`).

Ledger: `docs/work/2026-09-25-OME-1326-send-cache-saved-cost.md`.
Spec: `docs/spec/2026-09-25-OME-1326-send-cache-saved-cost.md`.
Plan: `docs/plan/2026-09-25-OME-1326-send-cache-saved-cost.md`.

**Ships second.** `ScoreSubmission` is `extra="forbid"`. The field was confirmed live and optional
on the dev board's `/openapi.json` on 2026-09-25, about 10 minutes after #1055 merged.

- 2026-09-23: filed under `OME-1251`, gated on `OME-1325` being deployed.
- 2026-09-25: built. The saving is carried onto `CandidateResult`, exported by `to_dict()`, and
  sent only when present. The reported sum only; the archive sum is never carried (D3).
