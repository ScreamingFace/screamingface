---
status: approved   # Filip, 2026-11-20: "implement the feature and do everything else"
date: 2026-11-20
spec: docs/spec/2026-11-18-hubspot-submission-sync.md
ledger: docs/work/2026-11-18-hubspot-submission-sync.md
---

# Plan: HubSpot submission sync

One scoreboard PR (code, migration, chart), then one infra PR in `OpenMined/infrastructure`
after it merges. The SOTA flag ships with rule B; the prod `candidate_kind` coverage check runs
before the job is switched on, not before the code.

## Files (scoreboard PR)

| File | What |
|---|---|
| `src/scoreboard/scores/models/hubspot_sync.py` | `BaseHubSpotSyncRecord` + `HubSpotSyncRecord` (table `hubspot_sync`, one-to-one with `scores`, cascade) |
| `src/scoreboard/scores/models/__init__.py` | export both |
| `src/scoreboard/scores/migrations/0025_hubspot_sync.py` | `CreateModel`, no data |
| `src/scoreboard/crm/__init__.py` | package |
| `src/scoreboard/crm/port.py` | `CrmSink` protocol and its value types (`Contact`, `Card`, `CardChanges`, errors) |
| `src/scoreboard/crm/decisions.py` | pure rules: eligibility, submission count, stage, which fields to write |
| `src/scoreboard/crm/hubspot.py` | `HubSpotSink`, the HTTP adapter over `httpx.AsyncClient` |
| `src/scoreboard/crm/settings.py` | `HubSpotSyncSettings` (`SCOREBOARD_HUBSPOT_*`), token as `SecretStr` |
| `src/scoreboard/hubspot_sync.py` | the job: queue new scores, group by submitter, apply, record status; `main()` with `--dry-run` |
| `charts/scoreboard/templates/cronjob-hubspot-sync.yaml` | CronJob, off by default, `concurrencyPolicy: Forbid` |
| `charts/scoreboard/values.yaml` | `hubspotSync:` block |
| `tests/unit/crm/test_decisions.py` | the rules, no DB, no network |
| `tests/unit/crm/test_hubspot_sink.py` | request shapes against `httpx.MockTransport` |
| `tests/unit/test_hubspot_sync_job.py` | the job against SQLite and a fake sink |
| `tests/unit/test_migration_0025_hubspot_sync.py` | the migration applies |

## Decisions taken in the plan

1. **No token = nothing sent.** Without `SCOREBOARD_HUBSPOT_TOKEN` the job logs how many scores
   are waiting and exits 0 without touching a row (dev and staging). `--dry-run` with a token
   does every HubSpot read and logs each write instead of sending it, and changes no row: that
   is the history check before switching prod on. (The spec said "runs dry" without a key; a
   dry run without reads cannot say what it would change, so the two are split.)
2. **Hand-typed check:** a property is left alone when its latest history entry came from a
   person (`sourceType` `CRM_UI`, `MOBILE_IOS`, `MOBILE_ANDROID`). Confirmed on the dummy
   record before going live (spec question 5).
3. **Rule B inputs:** the board rows are `ScoreStore.leaderboard(benchmark_id, None)` at the
   registered revision, the same rows the public board ranks; solo references are those rows
   whose stored `metadata.candidate_kind` is `model`, plus the board's imported baselines. The
   result is recorded on the sync row when the score is first queued.
4. **Re-grades:** `regraded_from_id` is not on `main` yet (#1896). The eligibility rule gains
   that check when it lands; until then a re-grade of an existing pair adds no submission.
5. **Delete paths need no change:** `delete_scores` and `purge_private_benchmark` already count
   what is left rather than trusting the delete count, and `retire_benchmark` refuses a
   benchmark with scores. New tests prove both delete with sync rows present.

## Order (TDD, one commit per green step)

1. Model + migration + migration test.
2. `decisions.py` + its tests.
3. `port.py` + `hubspot.py` + adapter tests.
4. `hubspot_sync.py` + job tests (queueing, grouping, statuses, backoff, 429, auth failure,
   dry run, delete paths).
5. Chart CronJob + values; `helm template` renders with defaults and with it enabled.
6. Gates: `uv run .claude/scripts/run_gates.py scoreboard`.

## After the scoreboard PR

- Infra PR: ExternalSecret `scoreboard-hubspot` → `sf-scoreboard-prod-hubspot-token`, egress
  NetworkPolicy (TCP 443, pods labelled `app.kubernetes.io/component: hubspot-sync`), and
  `hubspotSync` values in prod with the pipeline and stage ids.
- Before enabling: the `candidate_kind` count on prod (debug Firecall), a `--dry-run` reviewed
  by Irina or Bennett, and one real run against a dummy contact, deleted after.
