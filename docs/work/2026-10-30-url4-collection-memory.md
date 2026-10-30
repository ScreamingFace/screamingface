---
ticket: OME-1792
stack: url4
status: done   # planned | in_progress | done | blocked
started: 2026-10-30
finished: 2026-10-30
---

# url4-collection-memory — cut url4's peak memory on large fetched collections

## Intent

A measurement on origin/main (f76cacf85) of a 330 MB `cases.json` (181 base64-image rows)
iterated by `src*(…)` showed url4 holding the body several times over: `parse_collection`
strips (a full copy — `str.strip` on a `FetchedText` subclass always copies), `json.loads`
it, `json.loads` it AGAIN to keep number spellings, then re-serialises every row even when
`;iteration.slice` keeps two; and the executor's `_memo` pins every finished node result for
the whole run. Make the collection path parse once, materialise only the rows iteration uses,
and let the executor drop a node's result once its last consumer has it — with outputs,
ordering, dedup and caching unchanged.

## Planned changes

- `packages/url4/src/url4/dag/semantics/collection.py` — single parse (number spelling kept via
  `int`/`float` subclasses carrying source text); no `.strip()` copy when the ends are JSON
  whitespace only; `_lines` only computed when the JSON-array sniff fails; optional `window`
  so only kept rows are re-serialised; parsed elements dropped as they are converted.
- `packages/url4/src/url4/dag/nodes/iteration.py` — `MapNode` passes its slice as the window.
- `packages/url4/src/url4/dag/_memo.py` (new) — per-run memo with consumer-counted release
  (edge counts over `deps`; root never released; only on successful consumption).
- `packages/url4/src/url4/dag/executor.py` — use it (module is 1 line under its size cap).
- `packages/url4/scripts/bench_collection_memory.py` (new) — tracemalloc benchmark, not a test.
- New tests only: `packages/url4/tests/unit/test_collection_memory.py`,
  `packages/url4/tests/unit/test_executor_memo_release.py`.
- `_shared.py` `FetchedText` copy: investigate; a `str` subclass instance always owns its own
  buffer, so removing the copy means changing the payload type contract.

## Test plan

- Byte-identity of parsed items for number spellings (`2.50`, `1e5`, `-0`, big ints, NaN /
  Infinity at top level and nested), bools/null, unicode, nested objects; declared + sniffed.
- `json.loads` runs once per declared/sniffed JSON array; sniffed arrays never build `_lines`.
- Windowed parse equals parse-then-slice for JSON / NDJSON / CSV / text, incl. negative and
  out-of-range bounds; rows outside the window are never serialised.
- Unicode-whitespace-padded JSON still parses (strip semantics preserved).
- tracemalloc: windowed parse of a large declared-JSON `FetchedText` peaks well under the
  old ~4x body.
- `MapNode` hands its slice to `parse_collection`.
- Executor: diamond / multi-role shared node resolves once with release on; a large result is
  unreachable after its last consumer finished (weakref); root result stays memoised (reuse of
  an executor after success does not re-resolve).

## Acceptance

- `uv run .claude/scripts/run_gates.py url4 --base origin/main` green; module-size check green
  with no cap raised; no existing test edited.
- Before/after peak numbers reported from the benchmark.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `semantics/collection.py`, `nodes/iteration.py`, new
  `dag/_memo.py` (`RunMemo`), `dag/executor.py` (311 -> 306 lines, cap 312),
  `scripts/bench_collection_memory.py`, tests `tests/unit/test_collection_memory.py` (59) and
  `tests/unit/test_executor_memo_release.py` (4). `_shared.py` untouched (see Deviations).
- **Commits:** see branch `url4-collection-memory` (perf(url4): …).
- **Gates:** `run_gates.py url4 --base origin/main` ALL GATES GREEN (append-only, ruff,
  format, pyright, pytest+cov >= 95); `check_module_size.py` within baseline, no cap raised;
  `check_suppressions.py` 5/5.
- **Measured** (`scripts/bench_collection_memory.py --mb 50`, tracemalloc, body allocated
  before tracing): `cases*(…)` slice 0:2 over a 50 MiB declared-JSON body — peak added
  200.5 MiB (4.01x body) -> 50.2 MiB (1.00x); sniffed: 4.01x -> 1.00x; full parse, no slice:
  4.01x -> 1.02x. Memo: a 50 MiB result alive after its only consumer finished — 50.0 MiB ->
  0.0 MiB.
- **Deviations:** `FetchedText` copy NOT removed — a `str` subclass instance always owns its
  buffer, so dropping the copy means changing the payload contract (media type off the
  string). The copy is transient (the adapter's `FetchResult.body` dies when `_fetch`
  returns). Memo release applies to counted (non-prevalidated) runs only; spawned per-row and
  guard executors memoise as before. Edge: reusing ONE Executor for a second, DIFFERENT root
  that shares already-released nodes would re-resolve them (production builds one Executor
  per run; reuse with the same root still answers from the memo).
