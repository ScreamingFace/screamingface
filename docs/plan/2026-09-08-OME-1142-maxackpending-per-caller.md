# OME-1142 — Implementation plan

## Frame

Make the runner pool's `max_ack_pending` settable, keep the derived value as the fallback, and
correct the comments that assert it is a fleet bound. Chart plus one code comment; no runtime
logic changes.

## Changes

1. `deploy/helm/values.yaml` — add `runnerPool.maxAckPending: null` with a comment stating it
   is a PER-CALLER allowance (one bucket consumer each), that unset derives
   `replicas x workerSlots`, and that the value binds at consumer creation. Correct the
   `workerSlots` comment above it, which currently calls it "the fleet's `max_ack_pending`".

2. `deploy/helm/values.schema.json` — register `maxAckPending` under `runnerPool.properties` as
   `type: ["integer", "null"], minimum: 1`. Leave it out of `required` so unset stays legal.
   Mandatory because the object is `additionalProperties: false`.

3. `deploy/helm/templates/deployment-runner.yaml` — render
   `{{ .Values.runnerPool.maxAckPending | default (mul .Values.runnerPool.replicas .Values.runnerPool.workerSlots) | quote }}`
   and rewrite the comment block above it per D1.

4. `src/screamingface_engine/runner_queue.py` — correct the `DEFAULT_MAX_ACK_PENDING` comment
   (currently "a WHOLE-CONSUMER bound ... across EVERY puller in the fleet"). State that it is
   applied per bucket consumer, so the effective fleet ceiling is `bucket_count x` this value.
   Constant value unchanged.

5. `tests/unit/test_chart_render_runner_pool.py` — extend with two tests: an explicit
   `maxAckPending` is rendered verbatim, and an unset one still renders `replicas x workerSlots`.

## Test plan (RED first)

- `test_an_explicit_max_ack_pending_overrides_the_derived_product` — set
  `runnerPool.maxAckPending: 4` with `replicas: 2, workerSlots: 4`; assert the env var is `"4"`,
  not `"8"`. Fails today: the template ignores the key, and the schema rejects it outright.
- `test_an_unset_max_ack_pending_still_derives_from_the_fleet` — no key; assert `"8"` for
  `replicas: 2, workerSlots: 4`. Guards D3 against a future edit that drops the fallback.

## Gates

`uv run python .claude/scripts/run_gates.py --stack screamingface-engine` (ruff, ruff format,
pyright, pytest with the stack's coverage floor).

## Wisdom check

- The schema is the trap, not the template. `additionalProperties: false` means a values file
  using the new key fails the render until the schema admits it — exactly how the stale `rbac`
  key broke the infra render on 2026-09-08.
- `default` in Helm treats `null` as empty, which is what makes the optional key work. It also
  treats `0` as empty, so `minimum: 1` in the schema keeps a meaningless `0` from silently
  falling back instead of failing.
- This change does not alter any live deployment. Existing consumers keep the cap they were
  created with until they are deleted and rebuilt.
