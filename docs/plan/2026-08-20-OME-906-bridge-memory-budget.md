# OME-906 — Plan: bound the event bridge by memory, not by event count

- **Spec:** `docs/spec/2026-08-20-OME-906-bridge-memory-budget.md`
- **Base:** stacked on `OME-906-pipelined-frame-publishing` (PR #667). The spec's §3.2
  adds the drained counter beside the high-water mark, which PR #667 introduces. Basing
  this branch on `origin/main` would duplicate that feature and guarantee a conflict.
  After PR #667 merges, retarget this PR to `main`.
- **Stack:** `screamingface-engine` only. `url4` is not touched.

## Steps (RED first)

### Step 1 — RED: a wide DAG completes

`tests/unit/test_url4_executor.py`: a node with 9 000 `TextNode` dependencies runs through
the real `Url4Executor.execute` and the real drain loop, and completes. Today the
`NodeStarted` burst (about 3 events per node, emitted before any await) exceeds 8 192 and
raises `BridgeOverflowError`. This is the defect: a legitimate DAG fails.

### Step 2 — RED: the bound is a budget, and the message says what happened

`tests/unit/test_url4_executor.py`, against `_Bridge` directly:

1. A producer that never stops fails at `budget // 512` events, not at 8 192. A small
   budget (for example 10 240 bytes → 20 events) makes the bound observable.
2. The same overflow after the drain made progress says the backlog exceeded the memory
   budget, names the budget and the peak, and does not blame the consumer.
3. An overflow with a drain count of zero says the consumer never drained — the one case
   where the old message was the right accusation.
4. `Log` stays the only event kind ever dropped (existing tests hold; no new code).

### Step 3 — GREEN: the budget plumbing

- `job_env.py`: `BRIDGE_MEMORY_BUDGET_BYTES = "URL4_CLOUD_BRIDGE_MEMORY_BUDGET_BYTES"` and
  `DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES = 64 MiB`, beside the result caps, in `DEPLOY_TIME`
  and `__all__`.
- `runner/executor.py`:
  - `EVENT_SIZE_ESTIMATE_BYTES = 512` (module constant; the estimate is deliberate —
    about double the measured 278 B, so the real ceiling stays under budget).
  - `_Bridge.__init__(maxsize, *, memory_budget)`; `hard_cap = max(1, budget // 512)`.
    `_HARD_CAP_MULTIPLIER` is removed.
  - `drain()` counts every event it yields (`drained`).
  - `on_event` raises with one of two messages, keyed on `drained`: progress made → burst
    over budget; zero → consumer never drained.
  - `Url4Executor.__init__(..., memory_budget=job_env.DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES)`
    forwarded to `_Bridge`.
- `runner/main.py`: `build_executor` reads the name with `_int_from_env` and passes it on,
  exactly as the result caps travel.

### Step 4 — contracts and gates

- `test_job_env_contract.py` iterates the sets; the new member must stay out of
  `WRITTEN_BY_APP`. No test change expected.
- Run the full `screamingface-engine` gate set. No other stack is touched.

### Step 5 — close the unit

- Spec status → implemented; ledger outcome filled; `docs/tasks/` mirror added.
- Commits: conventional, `Refs: OME-906`; PR stacked on PR #667 with a retarget note.

## Risks

- **A budget below the soft cap (1024 events ≈ 512 KiB)** makes the hard cap bind before
  soft-cap eviction can run. That is what the operator asked for; the policy stays
  correct (the hard check raises after the eviction attempt). Documented, not clamped.
- **The estimate is not a measurement.** Accepted in the spec: order of magnitude is
  enough, and the default is double the largest measured event.
