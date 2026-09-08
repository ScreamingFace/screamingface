---
ticket: OME-1089
stack: screamingface-engine
status: in_progress
started: 2026-09-03
finished:
---

# OME-1089 — the worker's composition root passes the queue's replica count

## Intent

`worker_composition` builds the `RunQueue` the worker pool pulls from, and it omitted
`replicas` — so the worker declared the stream with the code default no matter what the
deployment configured. OME-1088 turned that count into `Settings.run_queue_replicas`; this
unit connects the worker half to it.

Both halves must agree. The App and the worker declare the SAME singleton stream, and
`ensure_stream` deliberately refuses a declaration whose properties diverge from an existing
stream — so a worker that declares with a different replica count than the App is not a
cosmetic mismatch, it is a startup failure on whichever side loses the race. Wiring one half
without the other would trade a fixed bug for an intermittent one.

Found by manual e2e deployment of the OME-1086 stack on a single-node kind cluster
(2026-09-03 findings, B2).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/worker/loop.py` — pass
  `replicas=settings.run_queue_replicas` in `worker_composition`.
- `apps/screamingface-engine/tests/unit/test_worker_composition_replicas.py` — NEW file
  (tests are append-only; no prior test is touched).

## Test plan

- The worker's queue carries the CONFIGURED replica count, not the code default — asserted
  with a non-default value, so an ignored setting fails the test.
- The worker's queue and the App's agree for any `Settings`: the invariant that a divergent
  declaration would break.
- The default path still yields the single-node-safe count.

## Acceptance

- `worker_composition(settings)` produces a `RunQueue` whose replica count is
  `settings.run_queue_replicas`.
- `run_gates.py screamingface-engine` green.

## Outcome

- **Actual files:** as planned, plus an unplanned repair to a prior test file (see Deviations).
  - `src/screamingface_engine/worker/loop.py` — `run_worker` passes
    `replicas=settings.run_queue_replicas`, with the divergence invariant anchored.
  - `tests/unit/test_worker_composition_replicas.py` — NEW.
  - `tests/unit/test_worker_claim.py` — EDITED, typing only (approved; see Deviations).
- **Commits:**
  1. `fix(engine): satisfy pyright in the worker claim tests`
  2. `fix(engine): the worker declares the queue with its configured replica count`
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — see the run for this
  branch. RED was observed first and for the right reason: `KeyError: 'replicas'` on all three
  new tests before the one-line wiring.
- **Deviations:**
  1. **This branch was ALREADY RED before any work of mine, and that is a finding.** PR #818's
     CI fails at tip `898b4832` with 5 pyright errors in `tests/unit/test_worker_claim.py` —
     verified both locally against the pristine branch and in the CI log for job
     100493190276. The 2026-09-03 deployment findings record #818 as "verified working e2e"
     and say nothing about a red pipeline, so this was previously unnoticed. Gates are
     absolute, so the branch could not carry the replicas fix until this was repaired.
  2. **A prior test file was edited, with owner approval.** The repair is typing-only and
     changes no assertion, no fake and no behavior: `import nats.errors` added (the file did
     `import nats` and used `nats.errors.Error`, which resolves at runtime only because
     another import happens to populate the attribute); the `_FakePublisher` bound to a local
     name instead of being reached through `worker._publisher`, which is typed to the
     `_Publisher` Protocol; and one `cast(_FakeProcess, proc)` where `_children` is typed to
     the `_ChildProcess` Protocol. Landed as its own commit so it can be reviewed — or
     reverted — independently of the replicas change. Gates ran with `--skip-append-only`; no
     gate was weakened.
  3. **Gates were run once over the union of both commits**, not separately per commit. The
     first commit is a strict subset that only removes type errors, so it is green on its own
     by construction, but it was not gated in isolation.
