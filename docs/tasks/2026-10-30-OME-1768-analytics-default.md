---
id: OME-1768
linear_url: https://linear.app/openmined/issue/OME-1768
status: todo
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

Latest decision (2 November): headless, terminal and notebook environments all
default on. Notice visibility is not an enrollment gate. Saved declines,
process disable and DO_NOT_TRACK always win. The two-second Colab setup wait remains.
