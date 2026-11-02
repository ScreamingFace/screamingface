# OME-1648 — A per-run memory budget that fits ContractEval's case load

Status: draft, 2026-10-19. Parent: OME-1607. Related: OME-1606.

## Problem

The runner stops every ContractEval run with `memory_budget_exceeded`, even a 3-case sample. The
default per-run resident budget is 1,024 MiB (`runnerPool.perRunCharge.memoryLimitMi`).

Measured on the local kind cluster (2026-10-19, OME-1648 comment):

- `/opt/benchmarks/contracteval/cases.json` is 192 MiB and has 4,182 rows. Each row holds a full
  CUAD contract. All rows contain non-ASCII text, so CPython stores them at 2 bytes per character.
- Every run reads and parses the whole file (`single_shot._cases`), whatever its `limit`.
- At 1 GiB: the run stopped at 1,382 MiB, 1.7 s after the start, before any model call.
- At 2 GiB: the run completed. The peak was 1,828 MiB (after case loading). The run held about
  1,293 MiB through answering and spiked to 1,677 MiB at aggregation.

The cost is fixed: it does not grow with the case count. 2 GiB leaves only about 11% headroom.

## Decision (owner, 2026-10-19)

Option (c): raise the budget now, and remove the fixed cost in a follow-up.

1. This unit: `perRunCharge.memoryLimitMi` 1024 → **2560**. `workerSlots` stays **4**: the owner
   keeps the concurrency and will increase the node VM capacity later.
2. Follow-up (separate issue, not this unit): selective case loading — slice before parse and
   serialize, and store each contract once. After that, lower the budget again.

## Required behavior (chart defaults)

| Quantity | Before | After |
|---|---|---|
| Per-run resident budget | 1,024 MiB | 2,560 MiB |
| `RLIMIT_AS` backstop (factor 2) | 2 GiB | 5 GiB |
| Run slots per runner pod | 4 | 4 |
| Pod memory limit (slots × limit + 256) | 4,352 Mi | 10,496 Mi |
| Pod memory request (slots × 256 + 128 + 2 × 194) | 1,540 Mi | 1,540 Mi |
| Warm children | 2 | 2 |

- INVARIANT: the default per-run budget stays at or above the measured ContractEval peak
  (1,828 MiB) plus 25% headroom, until the follow-up removes the fixed case-load cost.
- No code change. The slot count, the request and `max_ack_pending` do not change.

## Consequences

- The pod limit grows by 6 GiB (4,352 → 10,496 Mi) and the request does not. The node
  overcommit ratio (limit ÷ request) grows from 2.8× to 6.8×. If 4 runs on one pod each come
  near their budget, the node can run out of memory. The owner accepts this risk until the VM
  capacity increases.
- No change in `OpenMined/infrastructure` (prod uses chart defaults; Kargo advances the pin).

## Out of scope

- Selective case loading (follow-up issue).
- Other large bundles (`inspect-bbq` 262 MiB, `inspect-worldsense` 175 MiB): not measured.
- A full 50-case `sota_open_only` validation: it needs the recipe url4 from the OME-1606 owner.
