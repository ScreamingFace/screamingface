---
ticket: OME-1108
stack: screamingface-engine
status: in_progress
started: 2026-09-03
finished:
---

# OME-1108 — release in-flight reservations when a run actually finishes

## Intent

A caller is permanently locked out of the runner by runs that finished long ago. Observed live
twice on the kind rig: at 15:52 an evaluation of 7 candidates had **1 accepted (202) and 7
refused (503 "the runner is at capacity")** while `url4-runq` held **0 messages**, every
consumer sat at `pending=0/ack_pending=0`, and the worker reported `slots_busy 0` of 4 with
`pull_failures_total 0`. The App pod had not restarted since `15:23:36Z`, so it still held the
8 reservations admitted during the 15:29 evaluation — runs that finished ~23 minutes earlier.

The client symptom is worse than a refusal: the refused candidates still attach their
WebSockets (101) to topics whose runs were never created, so no frame ever arrives and nothing
ends them. They never execute and never fail.

## Root cause

`QueueJobRunner` reserves a per-caller slot at admission and releases it only via:

- `_forget_in_flight` from `status()` on a terminal frame — but `status()` has exactly ONE
  caller, `exists()`, reached only from the pre-schedule 409 check and the reaper's
  `_still_armed`. The WebSocket path the SDK actually uses never calls it.
- `_release_reservation` from `schedule()`'s publish-failure path.
- `_prune()` at `capability_lifetime_s` = 58,800s ≈ **16.3 hours**.

The reaper is the only background release path, it is **disabled here**
(`URL4_CLOUD_ORPHAN_GRACE_S=0`, and `app.py` then creates no task and logs nothing), and even
enabled it sweeps only topics armed by `audience_left` past a full grace window — release would
be an accident of orphan reaping, not a designed path. The module's own comment names the gap:
"the runner cannot observe a finish any other way".

## Design

`status()` already releases correctly, including `_forget_in_flight`'s stale-frame guard for a
re-scheduled topic. Nothing new is needed except **making the runner do that observation
itself, at the one moment it matters**.

In `_admit_or_raise`, when a caller is found at its cap: re-read the terminal frames of that
caller's in-flight topics, release the finished ones, recount, and only then refuse. Plus a
bounded reservation lease so a slot cannot outlive its run by 16 hours when the broker is
unreadable.

**WHY at the cap and not on a timer:** it costs nothing on the happy path (a caller below its
cap does no extra broker reads at all), it needs no background task and no lifecycle to get
wrong in tests or at shutdown, it widens no port on `_Publisher`, and it runs exactly when a
stale reservation would otherwise produce a wrong answer. A caller that stops submitting keeps
stale entries harmlessly — nobody is being refused — and the lease bounds them regardless.

Rejected: a per-topic terminal-frame subscriber (needs a `subscribe` on `_Publisher`, a task
per run, and reconnect handling) and a periodic sweep task (a lifecycle to leak, and it pays
broker reads when nothing is wrong).

## Planned changes

- `src/screamingface_engine/adapters/queue_runner.py`
  - `DEFAULT_RESERVATION_LEASE_S` + a `reservation_lease_s` constructor knob.
  - `_release_finished_for(caller)` — observe terminal frames for that caller's in-flight
    topics and release them, via the existing `_read_tail` + `_forget_in_flight`.
  - `_admit_or_raise`: sweep-then-recount before the cap refusal.
  - `_expire_leases()` called from `_prune()`.
- `tests/unit/test_queue_admission_release.py` — NEW file (tests are append-only).

## Test plan

- A caller at its cap whose runs have ALL finished is admitted, not refused — the incident.
- A caller at its cap whose runs are genuinely live is still refused (the cap must keep working).
- A partially finished caller is admitted and the count reflects only the live runs.
- A stale terminal frame from a PRIOR run of a re-scheduled topic does NOT release the live
  run's slot (the `_forget_in_flight` guard, exercised through the new path).
- An unreadable tail never releases — unknown is not terminal.
- Below the cap, admission performs NO extra broker reads (the zero-cost property).
- A reservation older than the lease is released even when the tail is unreadable.

## Acceptance

- The 15:52 scenario admits instead of refusing.
- `run_gates.py screamingface-engine` green.

## Outcome

- **Actual files:** as planned, plus the constant's home.
  - `src/screamingface_engine/runner_queue.py` — `DEFAULT_RESERVATION_LEASE_S = 3600.0`,
    placed beside `DEFAULT_CALLER_INFLIGHT_CAP` where the other admission defaults live.
  - `src/screamingface_engine/adapters/queue_runner.py` — `reservation_lease_s` knob;
    `_in_flight_count`; `_release_finished_for`; `_expire_leases`; the sweep-then-recount in
    `_admit_or_raise`; `_expire_leases()` called from `_prune`; `timedelta` import.
  - `tests/unit/test_queue_admission_release.py` — NEW, 9 tests.
- **Commits:** `fix(engine): release in-flight reservations when a run actually finishes`
- **Gates:** `run_gates.py screamingface-engine --skip-append-only`. RED observed first: 6 of
  9 new tests failed on the missing behaviour, while 3 passed from the start — deliberately,
  since they pin properties that were ALREADY correct (the cap still refuses live runs, an
  unreadable tail never frees a slot, a caller below its cap does no broker reads). Related
  suites re-run clean: 48 passed across admission, fairness, status, cancel and factory.
- **Deviations:**
  1. **The approved design was "terminal-frame watcher + short lease"; this ships
     "observe-at-the-cap + short lease".** A per-topic watcher needs a `subscribe` on the
     `_Publisher` port, one task per run, and reconnect handling — core-widening for a fix
     whose whole job is to answer one question at one moment. `status()` already contains the
     correct release, including the stale-frame guard; the defect is only that nothing calls
     it for in-flight topics. Calling it exactly where the wrong answer would otherwise be
     given is smaller, has no lifecycle to leak, and costs nothing below the cap. The lease
     half of the approved design is implemented as specified.
  2. **`reservation_lease_s` is not templated in the chart.** Neither are
     `caller_inflight_cap` nor `capability_lifetime_s` — an operator cannot tune any of the
     three. Out of scope here; noted below.
  3. **Branched off `OME-1092-chart-cutover`, not `origin/main`.** `queue_runner.py` does not
     exist on main — it arrives with #819 — so this fix is unbuildable there. It stacks as a
     sixth PR on the existing series rather than reopening the green #821.

## Follow-ups surfaced (not in this unit)

- **This state is invisible in `/metrics`.** There is no caller-in-flight gauge and no
  admission-refusal counter, so a spurious 503 against an idle pool looks like a lie from the
  outside. That absence is why the leak survived two incidents.
- `URL4_CLOUD_ORPHAN_GRACE_S=0` disables the reaper **silently** — `app.py` returns without
  creating the task and without logging. Disabling a background release path should say so.
- `caller_inflight_cap`, `capability_lifetime_s` and now `reservation_lease_s` are all
  untunable from the chart.
