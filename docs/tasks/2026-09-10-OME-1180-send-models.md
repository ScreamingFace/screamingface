---
id: OME-1180
linear_url: https://linear.app/openmined/issue/OME-1180/send-the-declared-model-identities-on-a-leaderboard-submission
status: Blocked
type: task
priority: 2
labels: [py-screamingface, agentic, autonomous]
parent: OME-1179
created: 2026-09-10
closed:
---

# Send the declared model identities on a leaderboard submission

Client half of `OME-1179`. The submission payload gains a `models` array carrying
`CandidateResult.models` verbatim.

`_submission()` previously sent only `_providers(candidate_result.models)`, which keeps the
first path segment of each route, so `openrouter/deepseek/deepseek-v4-pro` left as
`"openrouter"`. Every live `draco-3pass` entry therefore stores
`ran_with_providers = ["openrouter"]`, and an entry named `best_open_source` is published as
closed.

`ran_with_providers` is unchanged: it is required on `ScoreSubmission`, the portal's Backends
column reads it, and the Scoreboard's `_content_hash` hashes the wire value.

## Blocked on deployment, not merge

`ScoreSubmission` is `extra="forbid"`, so a released Client sending `models` to an un-upgraded
Scoreboard returns **422 on every submission**. `OME-1181` must be deployed and confirmed live
first.

`packages/screamingface` is on release-please, so merging the branch opens a release PR and
merging *that* publishes to PyPI. PR #923 is held in draft with a `Status: Blocked` label for
that reason.

## Artifacts

- Spec: `docs/spec/2026-09-11-OME-1180-send-models.md`
- Plan: `docs/plan/2026-09-11-OME-1180-send-models.md`
- Ledger: `docs/work/2026-09-11-OME-1180-send-models.md`
- PR: #923 (draft, held)

## Confidence-Gate exception

Owner-approved 2026-09-11: `test_the_submission_payload_gains_only_the_cost_key` gains the
single string `"models"`. Recorded in the spec §5 and the ledger.

Related: `OME-1181` (the Scoreboard half, PR #922), `OME-1145` (the bug this chain serves),
`OME-772` (recorded the missing model field on 2026-08-11).
