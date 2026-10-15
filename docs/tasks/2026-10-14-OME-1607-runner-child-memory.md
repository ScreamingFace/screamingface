---
id: OME-1607
linear_url: https://linear.app/openmined/issue/OME-1607/large-judged-runs-die-with-memoryerror-in-the-runner-child-and-the
status: in_progress
type: task
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-10-14
closed:
---

# Large judged runs die with MemoryError in the runner child, and the client waits forever

Big judged runs (`draco-3pass`: 100 cases, about 7,400 judge calls) die in the runner child with
`MemoryError` on aks-dev and aks-prod, and the client then shows "waiting" forever. Measured on a
local kind replay: pyarrow's mimalloc pool (1 GiB) and OpenBLAS (about 32 MiB per CPU) reserve
address space that the per-child 2 GiB `RLIMIT_AS` counts, so the run dies with only about 460 MiB
resident; RSS also grows by about 35 KB per model call; and the supervisor's crash terminal frame
uses the transport source, which the SDK ignores.

- 2026-10-14: filed at the owner's request at work start (not at PR-open). Ledger:
  `docs/work/2026-10-14-runner-child-memory.md`. No infrastructure change needed (Kargo, ADR-0008).
- 2026-10-14: built on one branch; review fixes applied; measured on kind (`draco-3pass` 444 MiB
  peak, was `MemoryError`). PR opened. Follow-ups found while verifying: wall-clock span times
  (engine) and a too-strict span check (SDK), `max_deliveries` transport source.
