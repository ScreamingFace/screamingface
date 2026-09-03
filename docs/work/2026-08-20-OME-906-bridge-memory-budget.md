---
ticket: OME-906
stack: screamingface-engine
status: in_progress
started: 2026-08-20
finished:
---

# OME-906 — Bound the event bridge by memory, not by event count

## Intent

`_Bridge` raises `BridgeOverflowError` at 8192 buffered events and blames the consumer. The
consumer is not the cause. Measurement shows the peak backlog is flat across a 100x range of
publish latency, and that the buffer holds one uninterrupted producer burst whose size scales
with DAG width — because `url4/dag/executor.py:182` emits `NodeStarted` before it awaits and
`:186` fans out over `node.deps` with an unbounded `asyncio.gather`.

So the cap is a ceiling on DAG width. A 100-Case DRACO Fusion is legitimately about 3500
nodes wide and sits at the limit. The quantity defended is 2.1 MB, in a process that accepts
a 1 GiB result.

This unit replaces the count bound with a memory budget and makes the error say what
happened.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` — derive the hard
  cap from `BRIDGE_MEMORY_BUDGET_BYTES`; add a drained counter beside the high-water mark;
  rewrite the overflow message to distinguish a legitimate burst from a stuck consumer.
- `apps/screamingface-engine/src/screamingface_engine/job_env.py` — read the budget from the
  environment, with the existing result caps as the model.
- Tests in `apps/screamingface-engine/tests/`.

## Test plan

RED first:

- A DAG whose single burst exceeds 8192 events completes through the real bridge and the real
  publish loop. This test fails today.
- A producer that never stops fails at the budget, not before it.
- A consumer that never drains fails the run, with a message that says the consumer is stuck.
- A burst over budget fails with a message naming the width and the budget.
- `Log` is still the only event kind ever dropped.
- The budget is read from the environment and falls back to the default.

## Acceptance

The six criteria in `docs/spec/2026-08-20-OME-906-bridge-memory-budget.md`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/screamingface-engine/src/screamingface_engine/job_env.py` —
    `BRIDGE_MEMORY_BUDGET_BYTES` name + `DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES` (64 MiB),
    `DEPLOY_TIME` + `__all__` membership.
  - `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` —
    `EVENT_SIZE_ESTIMATE_BYTES = 512`; `_Bridge(maxsize, *, memory_budget)` with
    `hard_cap = max(1, budget // 512)`; `_HARD_CAP_MULTIPLIER` removed; `drained` counter
    in `drain()`; two-variant overflow message keyed on `drained`; `BridgeOverflowError`
    docstring rewritten; `Url4Executor(memory_budget=...)` plumbed to the bridge.
  - `apps/screamingface-engine/src/screamingface_engine/runner/main.py` —
    `bridge_budget_from_env` (tolerant, like the result caps) wired into
    `build_executor`.
  - `apps/screamingface-engine/tests/unit/test_url4_executor.py` — RED-first: wide
    fan-in (9 000 deps) completes through the real engine; budget-derived cap;
    never-stopping producer fails at the budget; burst message names the budget and
    the DAG, stuck message says "never drained"; two pre-existing hard-cap tests given
    explicit small budgets (the default cap moved 8 192 → 131 072 and made them
    pathological — one took 838 s).
  - `apps/screamingface-engine/tests/unit/test_runner.py` — env resolution defaults,
    override, tolerance, and the `build_executor` wiring hop.
- **Commits:** conventional, `Refs: OME-906`; branch stacked on PR #667
  (`OME-906-pipelined-frame-publishing`) because the drained counter sits beside the
  high-water mark that PR introduces — a `main` base would duplicate the feature and
  guarantee a conflict. Deviation from the branch-from-`origin/main` rule is deliberate
  and recorded here.
- **Gates:** `screamingface-engine` stack — ruff check, ruff format --check, pyright,
  `check_layering.py`, pytest with coverage: 1 890 passed, 5 skipped, 93.57 % (≥ 80 %).
  No other stack touched.
- **Deviations:** PR #667 and this unit's PR #672 are linked as a native GitHub stack
  (stack #673, `gh stack link`) — merging #667 auto-rebases/retargets #672 to `main`;
  no manual retarget. The 64 MB budget stands as specced (owner did not name a tighter
  number; it is env-tunable at deploy time). Open item for the owner: PR #667's
  split-out Linear issue and OME-906's root-cause correction still need Linear MCP,
  which is unavailable in this session — payloads remain blocked on credentials.
