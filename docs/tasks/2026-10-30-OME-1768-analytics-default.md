---
id: OME-1768
linear_url: https://linear.app/openmined/issue/OME-1768
status: in_progress
type: task
priority: 1
labels: [analytics, agentic, deferred]
created: 2026-10-29
closed:
---

# Make SDK analytics on by default in all environments

Linear remains the status authority. Local implementation was authorized by Filip
before the recorded Irina/Kevin sign-off. On 2 November he confirmed proceeding
with the PR and chose to post the decision himself. Spec, plan and ledger:
`2026-10-30-analytics-default.md` in their respective
directories. OME-1793 tracks failure visibility separately.

On 3 November Filip confirmed that Irina approved in that day's sync. Kevin's
co-sign has not been recorded here. PR #1633 also addresses late existing-ID reads
and automatic enrollment responses after explicit reaccept; see the work ledger
for regression tests and validation. Deployed Colab smoke remains outstanding.

Decision on 2 November: headless, terminal and notebook environments all
default on. Notice visibility is not an enrollment gate. Saved declines,
process disable and DO_NOT_TRACK always win. The two-second Colab setup wait remains.

Merged [PR #1633](https://github.com/ScreamingFace/screamingface/pull/1633)
on 2026-11-04, commit `52d9492aa8b51b34dd9d4ceea6dae1eed0a750ba`.
Rollout checks remain: deployed Colab smoke, and the analytics service upgraded
before the SDK release that contains this change.

Reopened to In Progress in Linear at Filip's request on 2026-11-06. Production
PostHog received real Colab SDK events after a manual setup retry, but tracking
later became unknown/disabled again. Local fault injection reproduces setup and
delivery failures with no automatic recovery. PR #1703 first published failing
regressions and now implements recovery with safe local diagnostics; see the spec, plan and ledger named
`2026-11-06-colab-analytics-recovery-tests.md`. The initial browser failure cause
remains unconfirmed. Filip authorized five seconds for both consent setup and
background delivery on 6 November, superseding the original two-second setup
budget. Recovery rechecks browser consent on a later evaluation, preserves all
opt-outs, and never replays missed events. Deployed Colab verification is still needed.
