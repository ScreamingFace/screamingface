---
ticket: OME-1142
stack: screamingface-engine
status: in_progress
started: 2026-09-08
finished:
---

# OME-1142 — `max_ack_pending` as an explicit per-caller allowance

## Intent

The chart derives the worker's `max_ack_pending` from `replicas x workerSlots` on the premise
that it is a fleet-wide bound. Since the bucket split (OME-1091) the queue creates one durable
consumer per bucket and a caller occupies exactly one bucket, so the value is a per-caller
allowance. Deriving it from fleet size makes each caller's cap equal the whole pool, letting a
single caller saturate it at any replica count. Make the value settable, keep the derived
product as the fallback, and correct the comments that assert the old premise.

## Planned changes

- `apps/screamingface-engine/deploy/helm/values.yaml` — add `runnerPool.maxAckPending: null`;
  fix the `workerSlots` comment that calls it "the fleet's max_ack_pending".
- `apps/screamingface-engine/deploy/helm/values.schema.json` — register `maxAckPending`
  (`type: ["integer","null"]`, `minimum: 1`, not required). Mandatory: `runnerPool` is
  `additionalProperties: false`.
- `apps/screamingface-engine/deploy/helm/templates/deployment-runner.yaml` — render the key
  with `default (mul replicas workerSlots)`; rewrite the comment block.
- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` — correct the
  `DEFAULT_MAX_ACK_PENDING` comment. Value unchanged.
- `apps/screamingface-engine/tests/unit/test_chart_render_runner_pool.py` — two new tests.

## Test plan

- `test_an_explicit_max_ack_pending_overrides_the_derived_product` — `maxAckPending: 4` with
  `replicas: 2, workerSlots: 4` renders `"4"`. RED today twice over: the template ignores the
  key and the schema rejects it.
- `test_an_unset_max_ack_pending_still_derives_from_the_fleet` — no key, `replicas: 2,
  workerSlots: 4` renders `"8"`. Protects the backwards-compatible fallback.

## Acceptance

- An operator can pin the per-caller cap independently of pool sizing.
- Unset changes nothing about the rendered output for any existing values file.
- No comment in the chart or `runner_queue.py` still describes the value as a fleet bound.
- Stack gates green.

## Outcome

- **Actual files:** the five planned files, plus one unplanned comment repair. As planned:
  `deploy/helm/values.yaml` (`maxAckPending` + corrected `workerSlots` comment),
  `deploy/helm/values.schema.json` (key registered, `workerSlots` description corrected),
  `deploy/helm/templates/deployment-runner.yaml` (`default` fallback + rewritten comment),
  `src/screamingface_engine/runner_queue.py` (comment only; `DEFAULT_MAX_ACK_PENDING` value
  unchanged), `tests/unit/test_chart_render_runner_pool.py` (+3 tests). Unplanned: the comment
  inside the PRIOR test at lines 162-164 asserted the same false fleet-bound premise; corrected
  under the owner's explicit instruction (see Deviations). No schema, migration, or public
  Python contract changed — S1 does not apply.

- **Commits:** `feat(screamingface-engine): make the runner pool's max_ack_pending an explicit
  per-caller allowance` (the remote head is recorded by GitHub on the PR).

- **Gates:** `run_gates.py screamingface-engine --skip-append-only` reported ALL GATES GREEN:
  Ruff lint, Ruff format, Pyright, `check_layering.py`, and the full coverage suite
  (`--cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80`). 2636 tests collected
  in the stack; the touched file is 17 passing (14 prior + 3 new). RED was confirmed first: the
  explicit-value test failed because `runnerPool` is `additionalProperties: false` and the schema
  rejected the unknown key. The zero-boundary test now fails for the intended reason —
  `at '/runnerPool/maxAckPending': minimum: got 0, want 1` — where before the change it failed
  only because the key was unknown.

- **Deviations:** two.
  1. The append-only check was skipped under the owner's explicit approval, to correct the
     misleading comment inside the prior test `test_the_pool_renders_its_own_settings_into_the_worker_env`.
     Its behavioural assertion (`== "16"`) is byte-identical and still passes; only the
     explanatory comment changed, and it now carries an `AIDEV-NOTE` pointing at the new
     explicit-value test. The gate correctly refused this as a silent change first, and the skip
     is recorded here rather than passed over quietly.
  2. The plan did not include the `workerSlots` description in `values.schema.json`. It asserted
     "the queue's `max_ack_pending` is `QUEUE_REPLICAS × this`" — wrong twice over (the template
     uses `runnerPool.replicas`, not the queue's stream-replica count, and the value is
     per-bucket rather than fleet-wide), so it was corrected in the same pass.

- **Follow-up (not this unit):** live deployments keep the cap their durable consumers were
  created with. Re-capping `sf-fusion` means deleting the 16 `url4-runners-*` consumers while the
  queue is drained, then the infra-side change to `replicas: 2` + `maxAckPending: 4` + the
  `ns-ceiling` quota raise. Blocked on this chart reaching a release Kargo can pin.
