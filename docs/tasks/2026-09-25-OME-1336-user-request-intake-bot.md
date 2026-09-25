---
id: OME-1336
linear_url: https://linear.app/openmined/issue/OME-1336/set-up-daily-user-request-intake-bot-calls-repo-slack-linear-triage
status: in_progress
type: task
priority: 3
labels: [repo-dev-processes, agentic, autonomous, task]
created: 2026-09-25
closed:
---

# Set up daily user-request intake bot (calls repo + Slack → Linear triage)

A daily autonomous Claude agent that reads user/prospect requests from `OpenMined/screamingface-calls`
(call `notes.md`/`transcript.md`) and the Slack channels `#scream-q3-get-100-mau-in-sept` +
`#scream-updates`, extracts each distinct request into a fixed template (requester, org/site,
HubSpot link, full name, features, exact quote), dedups against tracked `user-request` issues,
and auto-files a regular Triage ticket with the `user-request` label — parented to an existing
epic when one applies, always assigned to Irina.

Execution model is a scheduled claude.ai routine (`RemoteTrigger`), NOT a deployed service
(repo law: Linear via MCP only). Spec: `docs/spec/2026-09-25-OME-1336-user-request-intake.md`.
Runnable prompt: `.claude/agents/user-request-intake.md`. Ledger:
`docs/work/2026-09-25-OME-1336-user-request-intake-bot.md`. The `docs/tasks/` mirror + ledger
for the tickets the bot itself files are deferred until a human promotes them out of Triage.
