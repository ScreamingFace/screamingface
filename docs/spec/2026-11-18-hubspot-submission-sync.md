---
status: draft
date: 2026-11-18
ledger: docs/work/2026-11-18-hubspot-submission-sync.md
epic: OME-1504
---

# HubSpot submission sync

## Problem

The program team tracks people working toward a leaderboard result on the 😱 SOTA deal
pipeline in HubSpot. Today someone moves those cards by hand, and only for grantees. Anyone
else who submits is invisible to them. The scoreboard already knows each submitter's verified
email, which boards they submitted to, and whether a result is on the Pareto frontier.

## Goal

Within minutes of a new submission from an outside submitter, HubSpot shows that person as a
contact with a card on the 😱 SOTA pipeline, in the stage that matches how far they have got.
A HubSpot outage delays this and never fails or slows a submission.

## Non-goals

- Imports from other leaderboards (deferred to next quarter's planning).
- Co-authors and lab principal investigators: one card per submitter.
- Private boards (decision 5): left out until Irina decides.
- Moving a card backwards when a result is later beaten.
- Cards in Dropped out (Filip, 2026-11-18): the job neither moves them nor writes their
  fields, even when the person submits again. Moving a card into or out of Dropped out is the
  team's call.
- Sending email to anyone.

## Facts this design rests on

- In production `submitted_by` is the `X-User-Email` Envoy stamps after verifying a
  Cloudflare Access JWT (`auth_mode: cloudflare_headers`, infra `values/prod.yaml`). The client
  cannot name itself.
- Prod on 2026-11-18: 11 identities, all emails; 3 on `openmined.org`; 8 external with 52
  (board, recipe) pairs; nothing on a private board (ledger, Evidence).
- Frontier membership is `compute_pareto_frontier_ids` over `leaderboard_pareto_inputs` at the
  board's registered revision; a board without a registered revision has no frontier
  (`routes/leaderboard.py`, the D12 gate).
- Re-grades (#1896, OME-1909) add rows that link to their source with `regraded_from_id`.
- The scoreboard namespace denies egress by default; each allowed destination is a
  NetworkPolicy in the infra repo (`kubernetes/apps/sf-scoreboard/base/netpol.yaml`).
- Secrets reach pods from Azure Key Vault through ExternalSecrets (`base/secrets.yaml`).
- HubSpot, read with the sync key on 2026-11-18 (schema and counts only): scopes
  `crm.objects.{contacts,deals}.{read,write}`, `crm.schemas.{contacts,deals}.read`. The key sees
  48,764 contacts and 587 deals, 35 of them on 😱 SOTA (pipeline `941434182`). Stages by
  display order: Onboarding `1450673809` (0), Engaged `1489861179` (1), Submission 1
  `1450673810` (2), Submission 2 `1450673811` (3), Submission 3 `1450673812` (4), SOTA
  `1450673813` (5), Dropped out `1450673814` (6). Deal fields: 😱 Leaderboard entry =
  `sf_leaderboard_url` (string, text); 😱 Submissions = `sf_submission_count` (number). Other
  fields the meeting touched: deal `sf_last_heard_date` (date), contact `sf_last_active_date`
  (date).

## Behaviour

### Which scores are eligible

A score is sent when all of these hold:

1. Its board is public.
2. It is not a re-grade (`regraded_from_id` is null, once that column exists).
3. `submitted_by` is an email: one `@`, a non-empty local part and a non-empty domain,
   split with `str.rpartition`, no regular expression.
4. The domain is not `openmined.org`, and the full address is not on the configured
   internal list (`SCOREBOARD_HUBSPOT_INTERNAL_EMAILS`).

Every other score gets a sync row marked `skipped` with the reason, so it is never
re-examined and the reason is auditable.

### What the card shows

For one submitter:

- **Submission count** = the number of distinct (board, `spec_id`) pairs among their eligible
  scores. A rerun of the same recipe on the same board adds nothing.
- **Target stage:** SOTA if any of their pairs is on its board's Pareto frontier when the job
  processes it; otherwise Submission 1, 2 or 3 for a count of 1, 2, or 3 and more.
- **Forward only:** the card moves only if the target stage is later than its current stage in
  the pipeline's stage order. A card a person moved further by hand stays where it is.
- **😱 Leaderboard entry:** the public page of the newest eligible submission,
  `https://leaderboard.screamingface.ai/spec.html?benchmark=<id>&spec=<spec_id>`.
- **😱 Submissions:** the submission count (type to confirm, Open questions).

### Matching in HubSpot (Bennett's rules)

1. **Contact:** look up by email (`idProperty=email`). Create it only if none exists, with
   `email` and the name "Unknown" (decision of 2026-11-18; Stephen's identity provider will
   replace it later).
2. **Card:** read the contact's associated deals and keep those in the SOTA pipeline.
   - none: create one in the stage computed above and associate it with the contact;
   - one in Dropped out: change nothing; the rows are `skipped` with reason `dropped_out`;
   - one in any other stage: update it;
   - more than one: change nothing and mark the row `failed` with reason `ambiguous_card`, so
     a person picks the right card.
3. **Never overwrite a hand-typed value.** Before writing a property, read its history. Write
   only when the property is empty or its latest value came from this integration (its
   history entry's source is this app's integration). Otherwise leave it and log
   `kept_manual_value`.
4. The job writes only the 😱 Leaderboard entry and 😱 Submissions properties and the deal
   stage. Pipeline and stage are configured by HubSpot id, never matched by label.

## Design

### Sync table

New model `HubSpotSyncRecord` (table `hubspot_sync`), one row per score:

| Field | Meaning |
|---|---|
| `score` | FK to `scores`, unique, `ON DELETE CASCADE` |
| `status` | `pending`, `sent`, `skipped`, `failed` |
| `reason` | skip or failure reason, bounded text |
| `on_frontier` | frontier membership recorded the first time the job processes the score |
| `attempts`, `next_attempt_at` | retry with exponential backoff, capped |
| `created_at`, `updated_at` | audit |

It stores no email: the address stays on `scores`, so a purge of a score removes the sync row
with it. Recording `on_frontier` once makes a retry send the same stage a first attempt
would have.

Delete paths that count deleted rows (`delete_scores`, `retire_benchmark`,
`purge_private_benchmark`) must keep their exact counts. On SQLite a cascade counts toward
the delete (found in OME-1708), so they delete sync rows first in the same transaction. Each
gets a test.

### The job

`python -m scoreboard.hubspot_sync`, a Kubernetes CronJob every 5 minutes,
`concurrencyPolicy: Forbid`:

1. Insert a `pending` row for every score that has none (`scores` left join `hubspot_sync`),
   applying the eligibility rules; ineligible scores become `skipped` at once.
2. Group due `pending` and `failed` rows by submitter, so one person is one HubSpot update per
   run, however many new scores they have.
3. Per submitter: compute count, stage and entry URL from all their eligible scores, apply the
   matching rules, mark that submitter's due rows `sent`. On a HubSpot error, mark them
   `failed` with the next attempt time and move to the next submitter.
4. Stop early on HubSpot's 429 and leave the rest for the next run.

WHY a CronJob and not a task in the web server: the HubSpot key then exists only in the job's
pod, never in the pod that serves public traffic, and a stuck HubSpot call cannot hold a web
worker. The table is the queue, so the submit path does not change at all.

### Ports and adapters

- `scoreboard/crm/port.py`: a `CrmSink` protocol with `find_contact`, `create_contact`,
  `sota_cards`, `create_card`, `update_card`, and property history reads.
- `scoreboard/crm/hubspot.py`: the HubSpot adapter over `httpx` (CRM v3 objects, v4
  associations).
- `scoreboard/crm/dry_run.py`: logs each decision and writes nothing; used when no key is set.
- The job takes the sink from a factory chosen by settings; the core logic never imports the
  adapter.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `SCOREBOARD_HUBSPOT_TOKEN` | unset | private app token; unset means dry run |
| `SCOREBOARD_HUBSPOT_PIPELINE_ID` | unset | the 😱 SOTA pipeline |
| `SCOREBOARD_HUBSPOT_STAGE_IDS` | unset | ordered stage ids: Submission 1, 2, 3, SOTA |
| `SCOREBOARD_HUBSPOT_INTERNAL_EMAILS` | empty | extra addresses to skip |
| `SCOREBOARD_PUBLIC_BASE_URL` | `https://leaderboard.screamingface.ai` | for the entry URL |

The token is a secret and is never logged; the settings repr masks it.

### Infra (OpenMined/infrastructure, separate PR)

1. Key Vault record `sf-scoreboard-prod-hubspot-token` in `kv-openmined-prod-eastus`, the
   vault the prod `azure-kv` ClusterSecretStore reads. Nobody holds standing write access;
   the owner writes it with `scripts/ops/write-vault-record.sh kv-openmined-prod-eastus
   sf-scoreboard-prod-hubspot-token` (hidden prompt, break-glass grant, write, revoke;
   `docs/runbooks/secret-rotation.md`). The value comes from 1Password (screamingface-infra,
   "HubSpot: ScreamingFace Leaderboard sync"), so it never passes through a chat or a repo.
2. An ExternalSecret `scoreboard-hubspot` in `kubernetes/apps/sf-scoreboard`.
3. A NetworkPolicy allowing the job's pods egress on TCP 443 to HubSpot's API.
4. The chart's new CronJob enabled in `values/prod.yaml`, with the pipeline and stage ids.

Dev and staging run without a token, so they stay dry.

## History

The first run would see every existing score. Recommendation: send the 8 external
submitters' history once, with frontier membership as it is on that day (the submit-time value
is not recoverable), after a dry run whose decisions Irina or Bennett check.

## Test plan

Unit, against a fake `CrmSink`:

- eligibility: public board, re-grade, non-email, `openmined.org`, configured internal address,
  mixed case domain;
- count: reruns on one board count once; the same recipe on two boards counts twice;
- stage: 1, 2, 3, 4 pairs; a frontier pair gives SOTA; never moves a card backwards;
- matching: no contact, contact with no card, one card, two cards (`ambiguous_card`);
- hand-typed value kept; integration-written value updated;
- a HubSpot error marks rows `failed` with backoff; a retry sends the recorded stage; 429
  stops the run;
- dry run writes nothing to HubSpot and leaves rows `pending`.

Adapter, against `httpx.MockTransport`: request shapes for lookup, create, associate, update,
history; token never in logs.

Storage: migration test for `hubspot_sync`; `delete_scores`, `retire_benchmark` and
`purge_private_benchmark` keep exact counts with sync rows present.

Manual, before enabling prod: one run against a dummy contact and card, checked in HubSpot and
deleted after (Bennett's rule).

## Acceptance

- A new external submission appears in HubSpot within one CronJob period after the job is on.
- An internal submission, a rerun and a re-grade change nothing in HubSpot.
- With HubSpot unreachable, submissions succeed and the job catches up when it returns.
- No hand-typed property value is changed.

## Open questions

1. **HubSpot names and ids:** answered (Facts).
1a. **One system-owned date (proposal, needs Bennett):** set the contact's
   `sf_last_active_date` (😱 Last Active Date) to the newest eligible submission time, and
   never write any other date. On 2026-11-18 it is empty on all 48,764 contacts, so nobody
   fills it by hand and the job would own it outright. It is outside Bennett's three fields,
   and the key cannot create a dedicated property (no `crm.schemas.*.write` scope), so either
   Bennett agrees to this field or he creates a dedicated one.
2. **Name "Unknown":** decided (Filip, 2026-11-18): `firstname` = "Unknown", `lastname` empty,
   only on create. Names need not be unique in HubSpot; no contact was named "Unknown" before.
3. **New card name:** the 35 existing SOTA cards are named after the person (`<first> <last>`
   on 32). Decided (Filip, 2026-11-19): consistent with them, a new card takes the contact's
   `<first> <last>`, or the email when the contact has no name.
4. **History:** decided (Filip, 2026-11-18): send it once after a dry run. A read-only dry
   run on 2026-11-19 (8 people, 52 pairs) would create 1 contact and 2 cards and move 6 cards
   that all sit in Submission 1 today; none had the sync's fields filled.
4a. **What qualifies for SOTA (asked Irina, 2026-11-19):** on the Pareto frontier rule, 7 of 8
   people reach SOTA, mostly through the cheapest run or the only entry on a board; only one
   holds a top score against other submitters. Proposed instead: the top score at processing
   time, on a board with at least one other submitter. The CSV sent to Irina is not kept in
   the repo (it lists emails).
5. **Integration source check:** confirm HubSpot's property history marks writes by this
   private app distinctly from UI edits, on the dummy record.
