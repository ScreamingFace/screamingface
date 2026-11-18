---
ticket: unfiled   # leaf under OME-1504; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: in_progress
started: 2026-11-18
finished:
---

# hubspot-submission-sync — record each leaderboard submitter on the HubSpot SOTA pipeline

## Intent

The partnerships, outreach and business development team needs to see who is active on the
leaderboard, so they can support people, amplify results and offer compute credits (Irina,
meeting 2026-11-18). Every new submission from an outside submitter should reach HubSpot
without anyone moving cards by hand: find or create the contact by email, find or create the
person's card on the 😱 SOTA pipeline, and move it through Submission 1/2/3, or to SOTA when
the result is on the Pareto frontier. Epic: OME-1504.

## Inputs

- Meeting Irina and Filip, 2026-11-18 (Gemini notes): contact by email, name "Unknown" when
  not known, one card per submitter, a Leaderboard entry URL on the card. Imports from other
  leaderboards are deferred to next quarter. Stephen's identity provider will later replace
  "Unknown" names.
- Bennett's rules (group DM, 2026-11-18 14:04): match contacts on email and create only if
  none exists; update the person's existing SOTA card rather than create one (Admissions
  creates cards for grantees); write only to 😱 Leaderboard entry, 😱 Submissions and the
  Submission 1/2/3 → SOTA stages; never overwrite a hand-typed value; test on a dummy record
  and delete it after. The API key ("HubSpot: ScreamingFace Leaderboard sync", contacts and
  deals read/write) is in 1Password under screamingface-infra.

## Decisions (Filip, 2026-11-18)

1. **Outage tolerance:** a durable sync table and a polling job with retry and backoff. The
   submit path never calls HubSpot, so a HubSpot outage never fails a submission.
2. **What counts:** each distinct (board, recipe) is one submission. Reruns of the same recipe
   on the same board do not count.
3. **Frontier:** checked when the submission is processed. Stages only move forward; a card
   is never moved back when a result is later beaten.
4. **Who is skipped:** every `@openmined.org` identity, anything that is not an email, and an
   explicit list for internal people on other domains.
5. **Private boards:** left out of v1 (agreed with Claude's pushback: they exist to keep
   results unpublished, and sending them to HubSpot moves that data to a third party).
   Irina decides before the first private board gets a submission.
6. **Credentials:** the key goes to Azure Key Vault and reaches the pod through an
   ExternalSecret, like `scoreboard-db` (infra repo, `kubernetes/apps/sf-scoreboard`). Without
   a key the job runs dry.

## Evidence (prod, read-only, 2026-11-18)

Read-only transaction in `deploy/leaderboard` (`sf-scoreboard`) through firecall, aggregates
only: 448 score rows, 11 identities, all emails, none null. `openmined.org`: 3 identities, 359
rows, 320 (board, recipe) pairs. External: 8 identities on 7 domains, 89 rows, 52 pairs. No
row on a non-public board. One external submitter has 57 rows over 20 pairs, so counting rows
instead of pairs would move cards on reruns.

## Planned changes

Phase 1: spec (`docs/spec/2026-11-18-hubspot-submission-sync.md`), then plan, then code.

## Test plan

Written in the spec.

## Acceptance

Written in the spec.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
