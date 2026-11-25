---
ticket: OME-1991   # leaf under OME-1504
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

Spec `docs/spec/2026-11-18-hubspot-submission-sync.md`; plan
`docs/plan/2026-11-18-hubspot-submission-sync.md` (files table there). Schema change: table
`hubspot_sync`, migration `0025_hubspot_sync.py` in the same iteration (S1).

## Test plan

Spec "Test plan" and plan "Order": rules without DB or network; the adapter against
`httpx.MockTransport`; the job against SQLite with a fake sink; the migration; both delete
paths with sync rows present.

## Acceptance

Written in the spec.

## Outcome (fill at the end — required before COMMIT)

- **Actual files (scoreboard PR):**
  - Model `scores/models/hubspot_sync.py` and migration `0025_hubspot_sync.py` (table only).
  - `crm/decisions.py` (rules), `crm/port.py`, `crm/hubspot.py` (adapter), `crm/dry_run.py`,
    `crm/settings.py` (`SCOREBOARD_HUBSPOT_*`, separate from the web `Settings`).
  - Job `hubspot_sync.py` (`python -m scoreboard.hubspot_sync [--dry-run]`).
  - Chart `templates/cronjob-hubspot-sync.yaml` and the `hubspotSync` values block (off by
    default; the SOTA pipeline and stage ids as defaults).
  - Tests: `tests/unit/crm/` (rules, adapter, settings and entry point),
    `tests/unit/test_hubspot_sync_job.py`, `tests/unit/test_migration_0025_hubspot_sync.py`:
    96 tests.
- **Commits:** the scoreboard commit on branch `hubspot-submission-sync`.
- **Gates:** `run_gates.py scoreboard` all green: append-only check, ruff, ruff format, pyright,
  the full pytest suite (2,339 collected) with coverage 92.75%, every portal Node suite. The 94
  rules, adapter and job tests also pass on a local Postgres 15. `helm template` renders the
  chart with the CronJob off, on with a Secret, and on without one (no token variable then).
  No prior test was edited.
- **Deviations:**
  - No token now means "count only", and `--dry-run` (with a token) reads HubSpot and logs the
    writes inside a rolled-back transaction. The spec had "runs dry without a key"; a dry run
    without reads cannot say what it would change.
  - A Dropped out card's rows are marked `sent` with reason `dropped_out`, not `skipped`, so they
    still count if the team brings the card back.
  - The one-to-one link to `scores` has no reverse relation (`related_name=False`): a prior test
    asserts every `Score` field reaches a read DTO, and the sync's bookkeeping must not change
    `Score`.
  - Settings errors hide their input (`hide_input_in_errors`): pydantic otherwise prints every
    value, the token included, into a crash log. Found by a test.
  - The delete paths needed no change: `delete_scores` and `purge_private_benchmark` already
    count what is left of the scores, and a test proves a delete with sync rows present.
  - Re-grade rows (#1896) are not excluded yet: `regraded_from_id` is not on `main`.

### Review of #1981 (Dmitry, 2026-11-20)

- Rebased on `main`, which took migration 0025 (`score_regraded_from`); the sync's migration is
  now `0026_hubspot_sync`.
- Visibility is checked again right before each person's HubSpot write: due rows on a board that
  went private become `skipped`/`private_board`, and only scores on boards public now count.
- Re-grades (`regraded_from_id` set) are skipped (`regrade`) and never counted.
- A filled card field is writable only when its newest history entry, by timestamp, is this
  private app's own write (`INTEGRATION`, `sourceId` = app id 62476090, read from HubSpot's
  token info). Every other source is kept; without an app id nothing filled is overwritten.
- Email shape: exactly one `@` and no whitespace.
- CronJob: the chart's pod and container security contexts, no service-account token.
- Not done as asked: an extra unique HubSpot deal property for idempotent creates. Every attempt
  re-reads the person's SOTA cards before creating, and a card is created together with its
  contact association, so a committed create whose response was lost is found and updated on
  the retry. A test pins it. Residual risk: HubSpot's association read lagging the create by
  more than the 5-minute backoff.
- Tests edited inside this PR (none on `main`): the adapter test's history entries now carry
  `sourceId` and `timestamp` (the old one encoded the looser rule), the migration test moved to
  0026, and the fake sink gained a lost-response mode.

### Second review of #1981 (Dmitry, 2026-11-20) and decision (Filip, 2026-11-23)

- Dmitry: (1) a stale association read can still create a second card; (2) the visibility
  re-check is not atomic with the HubSpot writes.
- Decision: accept both risks, recorded in the spec's "Accepted risks". Reply posted on #1981
  (issuecomment-7100137255). Added a warning against manual runs while the CronJob is on
  (`0f3b31a4a`).
- Checked before replying: the duplicate is caught on the next run (`_apply` refuses at two
  cards, tested); every run honours `next_attempt_at`, so no retry comes sooner than 5 minutes.
  Not verifiable: HubSpot's association read-after-write timing (no official guarantee; forum
  reports only).

### Merge (2026-11-23)

- Dmitry approved #1981 on `18d754e8e`, accepting both risks as v1 limitations, and corrected
  one claim: a duplicate card is not reliably caught on the next run (a successful retry marks
  the rows `sent`; it surfaces on the person's next submission or in an audit). Spec and plan
  corrected in a follow-up docs PR; duplicates are to be watched operationally.
- Merged as `de16e8e94` with one unrelated red check (Rust CodeQL, GitHub default setup: SARIF
  upload rate limit; GitHub does not allow re-running that run). Filip chose to merge.
- Infra handed to Stephen as OME-2002 (blocks OME-1991). Khoa's #2001 also adds a `0026`
  migration and must renumber.
