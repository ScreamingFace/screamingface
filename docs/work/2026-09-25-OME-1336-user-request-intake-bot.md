---
ticket: OME-1336
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-25
finished:
---

# OME-1336 — Set up daily user-request intake bot (calls repo + Slack → Linear triage)

## Intent

Requests users and prospects make on recorded calls (`OpenMined/screamingface-calls`) and in
two Slack channels are currently captured by hand and frequently lost or duplicated. This unit
sets up a **daily autonomous Claude agent** that reads both sources, extracts each distinct
request into a fixed template (requester, org/site, HubSpot link, full name, features, exact
quote), dedups against what is already tracked, and **auto-files a regular Linear ticket in
Triage** carrying the `user-request` label — parented to an existing epic when one clearly
applies, and always assigned to Irina for review.

## Planned changes

- `docs/spec/2026-09-25-OME-1336-user-request-intake.md` — the operating spec (sources,
  extraction, dedup, routing, config, signal filter, ticket template).
- `.claude/agents/user-request-intake.md` — the runnable autonomous prompt (canonical text
  pasted into the claude.ai routine), kept in sync with the spec.
- `docs/tasks/2026-09-25-OME-1336-user-request-intake-bot.md` — Linear mirror.
- (Runtime, not a repo change) the `user-request` label — already exists in Linear.
- (Runtime, not a repo change) the daily claude.ai routine — created via `RemoteTrigger`.

## Test plan

Process/automation unit — no code, so no pytest. Verification is behavioural (see spec §Verification):
- Dry run over 2–3 recent call folders → proposed ticket bodies only; check field + quote fidelity.
- Dedup re-run over the same folders → files nothing (fingerprint match).
- One live file → Triage + `user-request` + assigned/subscribed Irina + fingerprint marker + epic parent when applicable.
- Slack path over one channel-day → author/org resolved, non-requests ignored.
- Routine fires on demand (`RemoteTrigger run`) with the MCP connectors it needs.

## Acceptance

- Spec + runnable prompt committed and internally consistent (config, template, dedup rules).
- `user-request` label confirmed present.
- Routine created + a successful on-demand run that files at least one correct ticket.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <n/a — docs/process unit; behavioural verification per spec §Verification>
- **Deviations:** <anything that differed from the plan, or "none">
