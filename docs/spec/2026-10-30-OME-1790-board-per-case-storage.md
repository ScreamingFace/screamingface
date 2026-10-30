# OME-1790 — Imported-board storage that a run reads in O(selected Cases)

Status: draft, 2026-10-30. Parent: OME-1314 (capacity). Related: OME-1675 (Cases route loads
only the selected Cases), OME-1789 (aggregation reads only the selected Cases), OME-1792 /
PR #1622 (url4 parses a collection once and releases finished results), OME-1648 (the 2.5 GiB
per-run budget this work should let us lower).

All file:line references were re-read on `origin/main` at `f76cacf85`.

## Problem

An Imported Benchmark's public Cases are one JSON array, `<bundle>/cases.json`. Every consumer
reads and parses the whole array, even for a 2-Case run. The cost is O(board), not O(selection).

Board sizes (from the ticket): FigQA 330 MB, MMMU 265 MB, ContractEval 192 MB, TableQA 145 MB.
OME-1648 also lists `inspect-bbq` 262 MiB and `inspect-worldsense` 175 MiB. Average row size,
computed from the size and the pinned `case_count` in `TASK_REPLAY_CASES`:

| Board | Size | Cases | Average row |
|---|---|---|---|
| `lab_bench_figqa` | 330 MB | 181 | 1.82 MB |
| `mmmu_multiple_choice` | 265 MB | 847 | 0.31 MB |
| `contracteval` | 192 MB | 4,182 | 46 KB |
| `lab_bench_tableqa` | 145 MB | 244 | 0.59 MB |

Measured cost (OME-1648, kind, 2026-10-19): the 192 MiB ContractEval board held about 1,293 MiB
through answering, with a peak of 1,828 MiB, for a 3-Case run. A FigQA run (2 of 181 Cases) was
killed at 2,862 MiB against the 2,560 MiB budget (PR #1622).

## Facts this design relies on

- **Selection is always a prefix.** The protocol asks the Cases route for `selected_case_count`
  rows and iterates `slice=(0, selected_case_count)` (`benchmarks/protocol.py:270-274`). That is
  the only `slice=` in the engine and SDK sources.
- **Case ids are `1..N` in served order.** Capture numbers Cases with
  `enumerate(..., start=1)` (`screamingface_engine_inspect/capture.py:309-312`). Aggregation
  asks for `tuple(range(1, selected_case_count + 1))` (`single_shot.py:1133`, `:1179`).
- **The Case Digest does not depend on the file layout.** `case_digest` hashes the in-memory
  prepared Cases after a JSON round trip (`prepare.py:157-181`). `task_replay.py:327` checks it
  before anything is written. Any storage change that serves the same rows keeps every pinned
  digest.
- **A parseable `cases.json` is the "bundle finished" marker.** It is written last
  (`task_replay.py:334-342`, `bundle_provenance.py:169-170`). Code that relies on it:
  `prepare.py:2354` (refuse a used bundle), `benchmarks.py:7891` (nltk install), the
  `packages/screamingface/justfile:76-100` and `:330-349` asset recipes,
  `.github/workflows/screamingface-e2e-replay.yml:78` and `:90`, and
  `.github/workflows/screamingface-paid-benchmark-smoke.yml:119`. 36 test files under
  `apps/screamingface-engine/tests` name `cases.json`.

## Current consumers of `cases.json` (imported boards)

| # | Consumer | Where | What it does with the board |
|---|---|---|---|
| 1 | Cases route provider | `single_shot.py:821-840` (read at `:827`), installed at `:721` | `read_text` of the whole file; returns it as is |
| 2 | Envelope (envelope boards only) | `single_shot.py:843-863` (`json.loads` at `:855`) | parses every row, wraps each input, re-serialises the whole array |
| 3 | Cases route validation | `benchmarks/case_selection.py:17-41` (`json.loads` at `:23`) | parses the whole array to check `1 <= count <= len(rows)`; returns the raw text, and url4 slices it |
| 4 | Picture admission | `case_selection.py:33-38` → `picture_admission.py:179` → `cases_need_pictures` `:107-129` | scans every row's input. A picture anywhere makes it a picture Benchmark (`case_selection.py:35`) |
| 5 | Aggregation roll call | `shared_grading/case_grades.py:261-295` (read at `:276`), called at `single_shot.py:1113` | parses the whole array, builds `by_id` for all rows, keeps the selected ones |
| 6 | Check surface (not in the ticket) | `single_shot.py:1220-1236` (read at `:1224`), called per check at `:978` | parses the whole array on every mid-run check, finds the row whose input matches exactly |
| 7 | Completion-marker checks | listed in "Facts" above | `is_file` or parse-to-validate; not on the run path |

Out of scope: the hand-built shared-grading path (`shared_grading/serving.py:240-270`,
`:335-345`; MedXpertQA `medxpert/aggregate.py:78`, `packages/screamingface/.../cli.py:1009-1019`).
It has the same shape, but it is not an Imported Board. The port below is built so it can move to
the same format later.

After PR #1622, url4 parses the route's body once and serialises only the rows in the window.
That removes url4's copies. It does not remove consumers 1-6, which run in the Engine before or
after url4 sees the body.

## How boards are built, packaged and loaded

- **Build.** `Dockerfile.benchmark` runs `python -m screamingface_engine.benchmarks.prepare --root
  /opt/benchmarks` in a throwaway stage. For an Imported Board, `task_replay.py` replays the eval,
  checks the count and Case Digest, writes `provenance.json` (and `nltk_data/`), then
  `_write_cases` (`prepare.py:2360-2374`). That writes `targets/<id>.json` per Case (already one
  file per Case), then `cases.json` last.
- **Package.** The runtime stage copies `/opt/benchmarks` into the image (`COPY --from=prepare`) and
  sets `URL4_BENCHMARK_ASSETS=/opt/benchmarks`. The image is the only Runner image, and assets ship
  with the code that reads them. The rootfs is read-only. **There is no S3 or volume path.**
  A mounted volume is a recorded open question in `Dockerfile.benchmark`, not a current path.
- **Load.** `install_imported_benchmark(node, assets, id)` points every route at
  `assets / benchmark_id` (`single_shot.py:704-721`). Reads are plain local-filesystem reads,
  each time a route is called. Nothing is cached across runs (by design, `serving.py:240-258`).
- **Local and CI.** The e2e golden lane and `just` recipes prepare bundles into
  `/tmp/screamingface-data/benchmark-assets` or `~/.screamingface/benchmark-assets`. The CI cache
  restores them across runs, and the "already prepared?" test is `cases.json` exists or parses.
- **Reproducibility.** The Case Digest (content) is pinned per board. File bytes are a function of
  the rows (`json.dumps(..., ensure_ascii=False, separators=(",", ":"))`). Any new file must also be
  a pure function of the rows: no timestamps, no host paths, stable order.

## Options

All three options add one small per-board metadata file, `board.json`, written **before**
`cases.json` so the completion marker keeps its meaning:

```json
{"schema": "screamingface.board.v1", "case_count": 181, "has_pictures": true}
```

`has_pictures` is `cases_need_pictures(rows)` computed at build time, over the rows as the
Candidate will see them (after the envelope, where the board uses one). This makes consumer 4
O(1) with the same meaning ("a picture anywhere").

### Option A — one file per Case plus `board.json`

`cases/<id>.json` holds one row as written today. `cases.json` is no longer written, and
`board.json` becomes the completion marker.

- Route: read `cases/1.json..cases/N.json` and join them as `"[" + ",".join(rows) + "]"`. This is
  byte-identical to `json.dumps(rows[:N])` with the current separators.
- Aggregation: read `cases/<id>.json` for each selected id.
- Check surface: needs an input → id index (below), or a scan of every file.

### Option B — keep `cases.json`, add a byte-offset index

The writer serialises each row once, writes `cases.json` as `"[" + ",".join(row_bytes) + "]"`
(byte-identical to today; a test pins this), and records each row's `(offset, length)` in
`cases.offsets`. That file is binary, 16 bytes per Case (two little-endian uint64), in id order.
`board.json` also records `cases_bytes` (the file size) so a stale index is detected cheaply.

- Route: `seek` to the offsets for ids `1..N`, read those slices, join. No parse is needed except
  for envelope boards (parse only the N rows).
- Aggregation: the same, for the selected ids.
- Check surface: `cases.inputs`, a sorted binary file of `(sha256(input), id)`, binary-searched.
  It is written only for boards that declare a check surface. Without it, fall back to a streaming
  scan.
- An old bundle without `cases.offsets` falls back to today's full read and logs a warning.

### Option C — no format change: stream the prefix

Keep `cases.json` as is. Read it with an incremental decoder (stdlib `JSONDecoder.raw_decode`
over buffered chunks) and stop after row N. Only `board.json` is added.

- Uses the "selection is a prefix" fact. Memory is O(selected). Time is O(bytes before row N).
- Aggregation and check surface: a stream scan, O(1) memory but O(board) time for the check
  surface.
- It stops being O(selected) in time as soon as selection is not a prefix (sampling, resume after
  Case k, retry only the failed Cases).

### Comparison

| Criterion | A — file per Case | B — `cases.json` + offsets | C — stream the prefix |
|---|---|---|---|
| Run memory | O(selected) | O(selected); the index is read by `seek`, O(1) | O(selected) + one read buffer |
| Run time (read) | O(selected) | O(selected) | O(prefix bytes); O(board) for the check surface |
| Non-prefix selection later | O(selected) | O(selected) | O(board) time |
| Build time | +1 file per Case; negligible next to the replay (to be measured) | same writes plus 16 B/Case; negligible | unchanged |
| Image size | +307,949 files across the 89 boards (on top of the 307,949 `targets/` files). Estimate: ~225 MiB of tar headers and padding before compression (768 B/file), and small rows round up to the 4 KiB fs block (WorldSense 2.06 KiB/row avg, ~2× on disk) | +4.9 MB of offsets (307,949 × 16 B), plus `cases.inputs` for check-surface boards | +`board.json` only |
| Golden replay | Safe if the join is byte-identical (tested) | Safe: `cases.json` bytes are unchanged and slices are the original bytes | Safe: `cases.json` is unchanged |
| Migration (prod) | None: assets ship with the code in one image | None | None |
| Migration (local/CI caches) | **Breaks.** A cached bundle has `cases.json`, so the "prepared?" checks skip it. The new reader then finds no `cases/`. `prepare.py:2354` refuses to rewrite the directory. Needs a cache-key bump, new marker checks in 2 workflows + 2 justfile recipes, and a dual reader or a hard error | Old bundles keep working through the fallback. A cache-key bump only to get the speed | none |
| Contract churn | Marker moves: `prepare.py:2354`, `benchmarks.py:7891`, 2 workflows, 2 justfile recipes, `bundle_provenance.py` docs, 36 test files | Additive: the writer plus three readers | Additive: readers only |
| OME-1675 (route) | Route reads N files; OME-1675's "store each contract once" changes the row format again | Route reads N slices; dedupe is done by the writer and the index regenerates | Route streams N rows; dedupe lands as a format change on its own |
| OME-1789 (aggregation) | If OME-1789 lands first on `cases.json`, its reader is rewritten | OME-1789's reader moves behind the port with no format conflict | OME-1789 can be exactly this option |
| Complexity | Low reader; high migration and churn | Medium: offset writer, binary index, staleness check, fallback | Low-medium: a chunked decoder with rows larger than a chunk (FigQA 1.8 MB) |

The image-size figures are estimates, assuming uniform row sizes. The PR must replace them with
measured numbers (acceptance 3).

## Shared design (all options)

- **A port in core:** `screamingface_engine/benchmarks/board_store.py` defines
  `BoardStore(Protocol)`:
  - `case_count() -> int`
  - `has_pictures() -> bool`
  - `rows(ids) -> str` (a JSON array, byte-identical to today's slice)
  - `row(id) -> Mapping`
  - `id_for_input(text) -> int`

  The concrete stores (the format chosen plus the legacy full-read fallback) live beside it.
  The writer in `screamingface_engine_inspect/prepare.py` imports core, and core never imports
  the inspect plugin. Hand-built boards can adopt the store later.
- **The Cases route becomes count-aware.** `case_selection.cases_handler` already parses
  `count = int(request.intent)`. The provider takes `count`, validates it against
  `case_count()`, and returns `rows(1..count)`. The url4 `slice=(0, N)` stays (it is then a no-op)
  so the recipe identity and expression bytes do not move.
- **Admission takes a flag:** `refuse_blind_models(node, needs_pictures: bool)`. The flag comes
  from `has_pictures()`. The legacy fallback computes it with `cases_need_pictures` as today.
- **Envelope per row:** `_enveloped_inputs` runs over the N rows read, never over the whole board.
- **Aggregation:** `read_selected_cases(root, case_ids, ...)` reads `store.row(id)` per id. Error
  wording is unchanged.
- **Staleness and corruption** are bounded errors in the existing published voice ("imported board
  cases are unavailable: …"), never a raw `OSError`, a wrong row, or silent full reads.

## Recommendation

**Option B.** It gives O(selected) memory and time for every consumer, including any future
non-prefix selection. It keeps `cases.json` and its completion-marker contract byte for byte, so
golden replay, the CI caches, the `just` recipes and 36 test files are untouched. Its migration is
a logged fallback, not a coordinated cutover. It costs about 5 MB of image, against an estimated
~225 MiB of tar overhead (and more on disk) for Option A's extra 307,949 files.

Option A's simpler reader does not pay for its marker migration and file count. Option C is the
cheapest stopgap: it is the right shape for OME-1789 to ship now. But it is O(board) for the check
surface and for any non-prefix selection.

This differs from the ticket's title ("one file per Case"). The ticket's Change allows either, but
the owner should confirm the choice (Q1).

## Open questions for the owner

1. **Format:** Option B (recommended), A (the ticket title), or C (no format change)?
2. **Split with OME-1675 (Ionesio) and OME-1789 (in progress):**
   - (a) OME-1790 ships the port, the writer and `board.json`; OME-1675 switches the Cases route;
     OME-1789 switches aggregation. All three are behind the port.
   - (b) OME-1790 also switches the route and admission, and OME-1675 keeps only contract dedupe
     and lowering the budget.

   Recommendation: (b). The route switch and the format are tested together.
3. **Check surface (consumer 6):** is the input → id index in scope? It is not in the ticket, and
   today only text boards without the envelope can declare a check surface (`single_shot.py:498`).
4. **Old bundles without an index:** fall back with a warning (recommended), or refuse? Refusing
   forces the CI cache-key bump in the same PR.
5. **ContractEval contract dedupe (OME-1675 scope):** stays with OME-1675 on top of this format?
   Under Option B the writer emits rows with the contract inlined, so served bytes and the
   Candidate cache are unchanged.
6. **Lowering the 2,560 MiB per-run budget (OME-1648):** in this ticket, or in OME-1675 as filed?

## Acceptance criteria

1. For every Imported Board in the e2e golden lane, run results are unchanged, and
   `screamingface-e2e-replay.yml` passes with no re-recorded golden.
2. For each board, `rows(1..N)` is byte-identical to `json.dumps(json.loads(cases.json)[:N],
   ensure_ascii=False, separators=(",", ":"))`, and `cases.json` is byte-identical to the
   pre-change writer's output. The Case Digest pins do not change.
3. Memory: a 2-Case run of a 300 MB+ board (synthetic FigQA-shaped plus real `lab_bench_figqa` on
   kind) has a peak RSS that does not grow with board size. Measured at two board sizes, the
   difference is within noise (stated ±%), and the numbers are posted in the PR.
4. Build time and image size, before and after, for the full benchmark image, are posted in the
   PR.
5. Picture admission refuses a blind model on a picture board, and passes a text board, with no
   row scan when `board.json` is present.
6. A bundle with no index, or with a stale one (`cases_bytes` mismatch), behaves as decided in Q4,
   with a bounded error or a warning, never wrong rows.
7. `board.json` and the index files are byte-reproducible: two prepares of the same pins give
   identical files.

## Test plan

- **Writer (unit):** the joined-row `cases.json` equals the old `json.dumps(list)` bytes. Cover
  non-ASCII, nested envelopes, a picture row larger than any read buffer, and a single-row board.
  Every `(offset, length)` slice parses to its row. `board.json` fields match the rows.
  `has_pictures` matches `cases_need_pictures` over enveloped and non-enveloped rows.
  Determinism: prepare twice and compare the bytes.
- **Store (unit):**
  - `rows(1..N)` equals the legacy slice for N = 1, mid, all.
  - `N = 0` and `N > case_count` raise the existing `benchmark_contract_error`.
  - `row(id)` for the first, the last, and an unknown id.
  - `id_for_input` with a hit, a miss, and duplicate inputs refused.
  - Legacy fallback without an index.
  - A stale index (a truncated `cases.json`) gives a bounded error.
- **Route and admission (unit):** the count-aware provider returns N rows, and the envelope is
  applied per row. `refuse_blind_models` takes the flag. The existing
  `case_selection` / `picture_admission` tests stay green unedited (append-only).
- **Aggregation (unit):** `read_selected_cases` returns the same `SelectedCase` list through the
  store as through the legacy reader, including the "has no public input" error.
- **Memory (unit, tracemalloc):** a synthetic board at 50 MB and 300 MB with N = 2. The peak
  allocated for route plus aggregation is within a fixed bound that does not grow with board size.
- **Golden replay:** the e2e lane, with the bundle cache key bumped so the new writer runs.
- **Kind (manual, recorded in the PR):** `lab_bench_figqa` and `contracteval` 2-Case runs. Peak
  RSS before and after. Image size and build time before and after.

## Out of scope

- Hand-built boards (MedXpertQA and the shared-grading `serving.py` path). They can adopt the
  port later.
- A mounted-volume or object-store asset path.
- Changing the protocol's prefix selection.
