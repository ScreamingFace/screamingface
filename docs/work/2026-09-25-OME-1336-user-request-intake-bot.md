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

## Backfill run — 2026-09-25

Ran the bot manually over the FULL history (owner requested "do for all existing calls and
messages"): 21 call folders (3 parallel extractors) + both Slack channels in full.

- **Filed 28 user-request tickets:** `OME-1341` … `OME-1368` — all Triage / `user-request` /
  assigned to Irina, each with a `source-fingerprint`.
- **Granularity:** per-person (one ticket per person×distinct-ask) — owner's explicit choice
  over theme-clustering.
- **Cross-source dedup:** Slack contributed zero net-new requesters (its feedback posts are
  forwarded summaries of the same calls) → collapsed into the call tickets.
- **Skipped:** Emily Casleton 07-10, Ravi Madduri, Olivera Kotevska, Marija Sakota (no
  user-originated ask); Peter Ide-Kostic Slack posts = internal-tester bugs already on GitHub
  (#735–740); one anonymous on-prem signal (no identifiable requester).
- **Flagged:** `OME-1360` name discrepancy (frontmatter "Roberto Medina" vs transcript "Diana
  Buzaglo") — verify.
- **Epic organization (owner requested):** all 28 reparented under existing epics + 2 new epics
  created (`OME-1373` observability/T&E, `OME-1374` tool-plugin integration, both Triage, Irina+Kevin
  tagged for scope approval). Posted a demand-summary comment on each of the 10 epics. Mapping:
  E2/`OME-1287` cost&cache ×7, E7/`OME-1296` private-benchmarks ×3, E13/`OME-1306` BYOM ×3,
  E4c/`OME-1291` routing ×3, E10a/`OME-1299` benchmarks ×3, E10c/`OME-1301` agentic ×2,
  E14/`OME-1307` reproducibility ×3, E4a/`OME-1289` methods ×2 (tentative), `OME-1373` ×1, `OME-1374` ×1.
- **Spec/prompt updated (D3+D10):** the daily bot now parents every ticket under a best-fit epic and
  rolls up a demand comment on that epic; proposes (never auto-creates) an epic when none fits.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — spec, runnable prompt, ledger, task mirror (PR #1067).
- **Commits:** `af7ff69a` spec + prompt; `0af3e23c` signal-filter attribution rule.
- **Gates:** n/a — docs/process unit; behavioural verification per spec §Verification (backfill
  run above is the live end-to-end proof: 28 tickets filed correctly).
- **Deviations:** (1) backfill executed inline in-session rather than by the scheduled routine —
  routine creation still pending owner go-live decision + remote MCP-connector validation.
  (2) `user-request` label already existed (no owner action needed). (3) `repo` landing label ID
  from the card has drifted; used `repo-dev-processes` alone.
