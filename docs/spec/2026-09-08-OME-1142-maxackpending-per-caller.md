# OME-1142 — `max_ack_pending` is a per-caller allowance

## Problem

The chart renders the worker's queue cap from fleet sizing
(`deploy/helm/templates/deployment-runner.yaml:154-155`):

```
- name: URL4_CLOUD_RUN_QUEUE_MAX_ACK_PENDING
  value: {{ mul .Values.runnerPool.replicas .Values.runnerPool.workerSlots | quote }}
```

The comment above it justifies the product by calling `max_ack_pending` "a WHOLE-CONSUMER
bound — the fleet's total unacked runs". That was true before the bucket split (OME-1091),
when the queue had one durable consumer. It is false now.

`RunQueue._bound_subscription` (`src/screamingface_engine/runner_queue.py:651-659`) creates one
durable consumer **per bucket subject** and hands each the same `max_ack_pending`.
`bucket_subject` (`runner_queue.py:394-401`) hashes a caller's identity into exactly one
bucket. So the value is applied once per bucket, and a caller occupies one bucket.

Measured live on dev 2026-09-08: 16 consumers `url4-runners-00`..`0f` on `url4-runq`, each at
`max_ack_pending=4`, with `ack_pending=4` concentrated on a single bucket while
`worker_slots_busy=4` of `4`.

## Decisions

### D1 — The cap is per-caller, and the contract says so

`max_ack_pending` bounds one bucket's unacked runs, therefore one caller's in-flight runs. The
fleet-wide ceiling is an emergent `bucket_count x max_ack_pending`, which nothing enforces as a
single number. Execution is bounded by the worker's slot count, not by this value. Every
comment describing it as a fleet bound is wrong and gets corrected.

### D2 — A per-caller allowance must not be derived from fleet size

Deriving it from `replicas x workerSlots` makes each caller's personal allowance equal to the
whole fleet's slot count. One caller can then saturate the pool at any replica count, which
negates the fairness the bucket rotation exists to provide. Scaling the pool for *more callers*
must not simultaneously widen *each* caller's share.

### D3 — Unset keeps today's behaviour

The key is optional. Unset renders the existing derived product, so an upgrade changes no
running deployment and no operator is forced to pick a number. Choosing a value stays a
deployment decision, made in the values file that owns the rest of the pool's sizing.

### D4 — The schema must admit the key explicitly

`runnerPool` is declared `additionalProperties: false`. A values file setting an unregistered
key fails the render closed. The schema entry is therefore part of the change, not a follow-up.

### D5 — Both render paths are pinned by tests

A default-only test would pass while an explicit value silently did nothing, and an
explicit-only test would let the fallback rot. The render test asserts the explicit value is
honoured **and** that the derived product still appears when the key is unset.

## Non-goals

- Changing the default value, `DEFAULT_MAX_ACK_PENDING`, or the bucket count.
- Introducing a real fleet-wide admission ceiling. That is a separate design question; this
  change only makes the existing per-caller cap expressible.
- Touching the App-side per-caller admission cap (`DEFAULT_CALLER_INFLIGHT_CAP`), which is a
  different gate at a different layer.
- Recreating live durable consumers. The value binds at consumer creation, so an existing
  deployment keeps its current cap until its consumers are rebuilt — an operational step, not
  a code change.

## Invariant this protects

Raising the pool's replica count increases how many callers can run concurrently. It must not
increase how many runs any single caller may hold.
