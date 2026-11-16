---
ticket: OME-1924
stack: screamingface-engine
status: planned
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
