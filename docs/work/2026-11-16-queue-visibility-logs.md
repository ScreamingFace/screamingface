---
ticket: OME-1924
stack: screamingface-engine
status: in_progress
started: 2026-11-16
finished:
---

# queue-visibility-logs — name the owner, claim and finish of every queued run in the logs

## Intent

On 2026-11-15 all 8 prod runner slots held multi-hour runs (4 of them one HLE run) and three
outside users waited 3–4 h blind, then gave up. On-call could not say whose run held a slot or
when a queued run would start: the App and runner logs carry a run id but no owner, the runner
logs nothing when it claims or finishes a run, and the 300 s capacity notice says nothing about
the queue. This unit ships OME-1924's changes 1–3 (owner decision 2026-11-16: 1–3 first; the
admin queue view and wait-aware rotation follow in their own units). Identity is always the
sha256 owner key, never the email (owner decision 2026-11-16).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/…` (anchors from recon, see the spec):
  1. App: one `run accepted` log line at admission — topic, owner key, Benchmark, Case count,
     Candidate summary.
  2. Runner: `run claimed` (wait since accept) and `run finished` (outcome, duration) lines.
  3. The `unclaimed run warned` notice carries the waiting count and busy/total slots.
- Spec: `docs/spec/2026-11-16-OME-1924-queue-visibility-logs.md`; plan:
  `docs/plan/2026-11-16-OME-1924-queue-visibility-logs.md`.
- Mirror: `docs/tasks/…-OME-1924-queue-visibility-logs.md` (the issue exists; Khoa filed it).

## Test plan

- RED first: caplog tests for each new line (fields present, owner key is the hash, no email
  anywhere in the record), the waited-seconds arithmetic, the notice's new fields, and the
  healthy-stack silence (no notice under 300 s). Append-only; no prior test edited.

## Acceptance

- From the App and runner logs alone, on-call can name the owner key, Benchmark, accept time,
  claim time and outcome of every run; the notice says how many wait and how many slots are busy.
- No email appears in any log record; gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `rest/runs.py` (`run created` + `_loggable`), `rest/routes.py` (`run scheduled`
  owner/run/candidate, `_dash`), `rest/runs_start.py` (`StartBinding.run_id/candidate`),
  `worker/supervisor.py` (`run claimed`, `run finished`, `_endings`, `_waited_s`, `_seconds`),
  `unclaimed.py` (`demand` reader, counts in the line and `run.queue_waiting`), `app.py` (late-bound
  demand wiring); tests `test_run_visibility_lines.py` (10), `test_supervisor_visibility_lines.py`
  (4), `test_unclaimed_run_warner_counts.py` (5); spec, plan, this ledger, mirror
  `docs/tasks/2026-11-16-OME-1924-queue-visibility-logs.md`.
- **Commits:** 2dfae5961 spec · 4492e9c17 plan · 34171cf1a run created · 1131cea0d run scheduled ·
  ec7285000 + 8f471cc31 (control/Unicode escaping, folded with the runner lines) · bba5dce80 notice
  counts · the test-typing fix + mirror · 286b27e6a merge of origin/main.
- **Gates (base `origin/main` after #1588):** `run_gates.py screamingface-engine` ALL GATES GREEN;
  `run_gates.py repo` ALL GATES GREEN. Append-only: no prior test touched.
- **Deviations:** (1) identity rides only the routes' `run scheduled` line; `run_evidence.log_scheduled`
  keeps topic↔trace↔job (the spec named both). (2) Security review (2 rounds) added `_loggable`:
  every Unicode C* and Zl/Zp character in `benchmark` becomes `?` — not in the spec. (3) The
  outcome holder is `_endings` (the supervisor already had `_outcomes`). (4) Owner key stays in logs
  as decided; the reviewer's HMAC-pseudonym suggestion is declined (it breaks the join on-call needs).

- Review round 1 (2026-11-17, HupBaHa on #1840):
  1. `run created` logged the caller's Benchmark text, so spaces/`=` forged fields on the same
     line and an `@` could log an email. Now `_benchmark_token`: the name itself when it is plain
     (`[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}`), else `sha256:<16 hex>`. The branch's own control-
     character tests now expect the token; new field-injection and email-shaped regressions.
  2. The 300 s notice read `queue_snapshot()`, which admission refreshes before publishing, so
     it could say `waiting=0` for the warned run. `QueueJobRunner.unclaimed_now()` reads the queue
     now; the warner prefers it and falls back to the snapshot on a failed read. New regression
     schedules one run through the real runner and expects `waiting=1`.
  All three regressions RED on 0c7154ace, GREEN after. Main merged; engine and repo gates green.
- Review round 2 (2026-11-17, HupBaHa): a failed fresh read still fell back to the pre-publish
  snapshot, so it could report the stale `waiting=0`. Now a runner with `unclaimed_now()` never
  uses the snapshot; a failed read logs `waiting=-` and omits `run.queue_waiting`. New regression:
  schedule one run, snapshot (0, None), fresh read raises → `waiting=-`. RED before, GREEN after;
  main merged; engine and repo gates green.
