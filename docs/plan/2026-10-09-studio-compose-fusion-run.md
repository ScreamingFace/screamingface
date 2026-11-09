---
status: draft 2026-10-09 (rev 2: U1 judges, U3 Tavily, desktop label)
ticket: unfiled (five leaves under epic OME-1308, each filed at its PR-open)
spec: docs/spec/2026-10-01-studio-compose-fusion-run.md (approved 2026-10-09, with D10)
base: origin/main @ 93fef7ae5
---

# Plan — Studio Compose Fusion runs a real fusion

Paths are relative to `apps/screamingface-studio/` unless they start with `packages/`. Every
task runs RED → GREEN → refactor and ends with its stack's gates green (§Gates). One PR per
slice: **A, B, C, D1, D2**.

| Slice | Lands in | Depends on | Leaf landing label |
|---|---|---|---|
| A — benchmark picker | `frontend/` | — | `desktop` |
| B — Engine run client + recipe fixes | `frontend/src/lib/` | — | `desktop` |
| C — Run panel wiring | `frontend/` | A, B | `desktop` |
| D1 — runtime `--benchmark-assets-dir` | `packages/screamingface` | — | `client-sf` |
| D2 — bundle datasets, pass the folder | `src-tauri/`, `runtime/` | D1 | `desktop` |

A, B and D1 can be built in parallel. C and D2 come after the slices they depend on.

## Checked against the live runtime (2026-10-05, sidecar from source on this branch's base)

| Check | Result |
|---|---|
| `GET /v1/benchmarks` | 8 rows: `contracteval` 4182, `draco` 100, `draco-3pass` 100, `gdpval-text` 102, `healthbench-professional` 525, `healthbench-worst30` 157, `ifeval` 541, `medxpert` 2450. Keys: `id title description revision case_count origin focus difficulty interaction failure_policy dataset_url href object`. |
| `?limit` above `case_count` | 422 |
| `POST /token` | `{token}`, a JWT |
| CORS preflight from `tauri://localhost` | Granted for `url4-capability` and `prefer` |
| Attach frame | `data.from_sequence` must be **null or ≥ 1**. Sending `0` returns `ai.url4.error invalid_frame`, and **no events arrive at all**. This matches the SDK's `run_lifecycle._attach(None)`. |
| `GET /?q=` + `Prefer: respond-async` | 202 with an empty body |
| Event order (IFEval, 1 case) | `started` → `span`… → `log` (`case_loading` started/completed, `answering`, `model_call`) → `log` with `sf.progress.*` (`completed`, `graded`, `score`) → `cost.usage` (`scope: subtree`) → `result` → `terminated` |
| `result.data.body` | A **JSON string**, so it needs a second `JSON.parse` to get the `CandidateResult` |
| Provider not connected | The run still ends `terminated: succeeded`, but with `score: null` and `coverage: 0`. Each case has `failures[0] = {code: "upstream_error", metadata.source_code: "profile_not_found"}`. |
| Datasets missing (fresh data directory) | `terminated: failed`, `error.code: benchmark_unavailable` |
| Datasets on a read-only folder (`chmod -R a-w`) | Cases load for all 6 bundles, with no write errors. Grading is **not yet verified** because no provider was connected (§T-D2.4). |
| DRACO and DRACO 3-Pass | Cases fail with `benchmark_retrieval_unavailable`. The local Engine reads Tavily only from the runtime process's `TAVILY_API_KEY` env var (`world/factory.py:219`), and the Studio sidecar, launched from Finder, has none. A notebook sets it with `export` before `screamingface up`. |
| Fixed judges (checked in code, 2026-10-09) | DRACO, DRACO 3-Pass and GDPval Text: `openrouter/google/gemini-3.1-pro-preview`. HealthBench (both): `openrouter/openai/gpt-5.4`. IFEval, MedXpertQA and ContractEval have no judge. The catalog does not expose judges. |
| Installer size (D10) | 227.3 → 304.9 MiB |

**UI decisions that follow from these checks.** They refine the spec; they are not new scope.

- **U1. Check connections before a run: the fusion's models and the benchmark's judge.** If
  any selected model's provider, or the benchmark's judge provider (U3 table), is not
  `connected` in the model store, Run is disabled and names what is missing. For example:
  "Connect Anthropic to run this fusion", or "HealthBench is graded by OpenRouter — connect
  OpenRouter to run it". Without the model check, the run "succeeds" with a null score.
  Without the judge check, every case is answered (and paid for), then fails at grading.
- **U2. A null score is shown as "—"**, with "No cases were graded". The case failures shown
  come from the result. This is never shown as 0.
- **U3. A Studio presentation table records what each benchmark requires.**
  `lib/benchmark-presentation.ts` maps each id to `{judgeProvider?: string, needsWebSearch?: true}`,
  using the judges listed above, with `needsWebSearch` for `draco` and `draco-3pass`. It follows
  the same pattern as `provider-presentation.ts` (OME-1415 D6), because the catalog exposes
  neither field.
  - Web-search benchmarks are listed but cannot be run, labelled "Needs a Tavily web-search key —
    not available in Studio yet".
  - An unknown id has no requirements. That keeps the picker working when the Engine adds a
    benchmark, at the risk of a grading failure the run row then reports.
  - The table carries a header comment naming the follow-up unit that replaces it with catalog
    fields (spec §5, "Notebook parity: Tavily connection + catalog requirements").
- **U4. Retry the start while the socket attach is registering.** On a 428 whose detail
  contains "attach a websocket", retry the start up to 5 times, 100 ms apart. This mirrors the
  SDK's `_attachment_is_still_registering`.
- **U5. Timeouts match the SDK.** A run fails after 120 s with no frame. Stop waits 5 s for
  `terminated`, then falls back to `DELETE /?topic=`.

## Slice A — benchmark picker

### T-A1. Client method and types

- `lib/engine/types.ts` adds `BenchmarkSummary`: the catalog keys above, with `focus` and
  `dataset_url` optional.
- `lib/engine/client.ts` adds `listBenchmarks()`. It reuses `request` and `listData`, and
  supports ETag the same way `listModels` does.
- RED tests (`client.test.ts`): the happy path checks the URL; problem+json is mapped to an
  `EngineError` kind; a fetch rejection is reported as `unreachable`.

### T-A2. `lib/benchmark-store.ts` and `lib/benchmark-presentation.ts`

- A zustand store, not persisted, with `status: idle|loading|ready|error`, `benchmarks`,
  `refresh()` and `error`, modelled on `model-store.ts`.
- `benchmarkPresentation(id)` returns `{judgeProvider?, needsWebSearch}` (U3).
- RED tests:
  - the states move loading→ready and loading→error, and retry recovers;
  - two concurrent `refresh()` calls make one request;
  - `draco` and `draco-3pass` need web search and are judged by `openrouter`;
  - `healthbench-*` and `gdpval-text` are judged by `openrouter`;
  - `ifeval`, `medxpert`, `contracteval` and unknown ids have no requirements.

### T-A3. Picker in `RunsPanel` (`app/(studio)/ensembles/new/page.tsx`)

- Remove the `benchmarks` constant (`:119`) and the custom-file upload (`:1193–1212`).
- Each option shows the title, the `focus` (falling back to a truncated `description`), and
  `case_count` cases. Web-search benchmarks are listed but disabled, with "Needs a Tavily
  web-search key — not available in Studio yet" (U3).
- Sample-size presets: a preset above `case_count` is disabled; Custom is clamped to
  `1…case_count`; Full uses `case_count`. The default stays at 50, clamped.
- Loading, error (with Retry) and empty states. Run is disabled until a runnable benchmark is
  selected.
- RED tests (`ensembles/new/page.test.tsx`, extended):
  - 8 options render from a mocked client;
  - DRACO is disabled with the Tavily label;
  - the "100" preset is disabled for a 52-case fake;
  - Custom 9999 clamps to `case_count`;
  - the error state with Retry;
  - no "Upload" control exists.
- Coverage: add `src/lib/benchmark-*.ts` to `vitest.config.ts` `include`.

## Slice B — Engine run client and recipe fixes

### T-B1. url4 text quoting and linking (`lib/engine/url4.ts`)

- `quoteText(s)` is `"'" + s.replaceAll("\\", "\\\\").replaceAll("'", "\\'") + "'"`. It mirrors
  `url4/core/render.py:367`.
- `linkCandidate(candidate, benchmarkUrl4)` returns
  ``(candidate:0.0:${quoteText(candidate)}, ${benchmarkUrl4})!''`` (spec D4).
- RED tests use **golden strings generated by the SDK's own `link_candidate`** for two recipes
  (with and without params), committed as fixtures in `lib/engine/__fixtures__/linked.json`.
  `scripts/gen-link-fixtures.py` regenerates them with `uv run` from `packages/screamingface`,
  and its header documents how. Edge cases: a prompt containing `'` and `\`.

### T-B2. `recipe.ts` fixes

- `paramQuery` emits `?k=v&…&q=` and the call follows with `(<context>)`. With no params,
  the output is unchanged. Golden check: `/openai/gpt-4o?temperature=0.7&seed=3&q=($input)!'…'`
  (the SDK's `compile_candidate` output).
- `parseRecipe(url4)` moves into `recipe.ts` and parses `recipeToUrl4`'s own output:
  - Fusion: members plus `synthesis_N`.
  - Pipeline: `$previous` chaining.
  - Solo.
  - Params and prompts, with escaped quotes.
  - Anything it does not recognise is rejected with a message, never half-parsed.
- `page.tsx` deletes its old `parseRecipe` (`:404`), which accepted the `url4://name?models=` form.
- RED tests (`recipe.test.ts`, new):
  - a round trip `recipeToUrl4 → parseRecipe → recipeToUrl4` for fusion, pipeline and solo,
    each with and without params and prompts;
  - the param golden above;
  - rejection of the old `url4://` form and of a truncated string.
- Coverage: add `src/lib/recipe.ts`.

### T-B3. Run protocol (`lib/engine/run.ts`, `lib/engine/run-types.ts`)

- Types:
  - `CandidateResult` and `CaseResult`, following spec §3;
  - `RunEvent` as a union: `progress {completed, graded, score}`,
    `activity {kind, state, caseId?, modelId?, body}`, `cost {totalUsd}` (the subtree),
    `started`, `log`.
- `startRun({candidateUrl4, benchmarkId, limit, useCache, onEvent, signal, deps})` runs:
  1. `GET /v1/benchmarks/{id}?limit=`
  2. `POST /token`
  3. Open `WebSocket(ws://…/ws?ticket=, ["cloudevents.json"])`.
  4. Send attach with `{from_sequence: null, cache: {participate: useCache}}`.
  5. `GET /?q=<linked>` with `URL4-Capability` and `Prefer: respond-async`, plus
     `Cache-Control: no-store` when `!useCache` (spec D9), with the U4 retry.
  6. Dispatch frames:
     - in sequence order;
     - duplicate sequence numbers dropped;
     - a gap waits up to 2 s, then reports `stream_failed`.
  7. Resolve on the `result` frame plus `terminated: succeeded`.
- `result` frames:
  - an inline `body` is passed through `JSON.parse`;
  - an `artifact` result is fetched from `GET /artifacts/{id}` with the capability header.
- Rejections are typed `RunError`s:
  - `failed` or `timed_out`, carrying `error.code` and `error.message`;
  - `stopped`;
  - `unreachable`;
  - `stream_failed`, which is also used for the 120 s silence (U5).
- On `signal` abort: send `ai.url4.stop {reason: "cancelled by user"}`, wait up to 5 s for
  `terminated`, then fall back to `DELETE /?topic=` with the capability. The topic is the
  token's `sub`.
- `deps` = `{fetch, WebSocket, now, setTimeout}`, injected so tests use a fake socket and fake
  timers.
- RED tests (`run.test.ts`), with a fake WebSocket driven by frames **captured from the live
  check above** and kept as fixtures:
  1. the happy path resolves the `CandidateResult`, and the events arrive in order;
  2. the attach frame has `from_sequence: null` and the cache intent;
  3. `useCache: false` sends `Cache-Control: no-store` and `participate: false`;
  4. a 428 "attach a websocket" is retried and then starts; any other 428 rejects at once;
  5. an artifact result is fetched with the capability header;
  6. `terminated: failed benchmark_unavailable` rejects with that code;
  7. out-of-order frames are reordered, a duplicate is dropped, and a gap that never fills
     reports `stream_failed`;
  8. 120 s of silence reports `stream_failed`;
  9. abort sends the stop frame, and `DELETE` is sent only if no `terminated` arrives in 5 s;
  10. the token never appears in any error message.
- Coverage: already in scope through `src/lib/engine/**`.

## Slice C — Run panel wiring

### T-C1. Store changes (`lib/ensemble-store.ts`)

- `SavedRun` becomes the summary shape in spec §4.3. The persist `version` is bumped, and
  `migrate` drops every `runHistory` entry; fusions are kept.
- A new store, not persisted: `lib/run-results-store.ts`, a `Map<runId, CandidateResult>`
  (spec D7).
- RED tests:
  - migrating a v0 payload with mock runs keeps the fusions and empties the runs;
  - a new run summary is persisted; the full result is not persisted.

### T-C2. `RunsPanel.startRun` and the running view

- Replace the `setInterval` simulation (`:1112–1191`) with `startRun` (T-B3), passing
  `recipeToUrl4(root)`, the selected benchmark, the limit and `useCache`.
- Check connections first (U1).
- The progress bar shows `completed / selected_case_count`, alongside the running score
  ("—" while null) and the most recent activity line ("Model call · claude-opus-4-5 · case 3").
  Cancel aborts the `signal`.
- Merge the two cache switches into **Use cache** (spec D9). Show OM compute disabled, with
  "Coming soon" (spec D6). Disable Publish, with "Coming soon" (spec D1).

### T-C3. Results view (`RunDetail`)

- Delete `scoreForModel`, `questionBank`, `reasoningTraces`, `synthesisTraces`,
  `stableFraction`, `publicRankingSeeds` and the public ranking, plus the baseline and gain UI.
- Summary: score ("—" when null, per U2), coverage %, cost (the subtree total) and duration.
- A paginated case list (25 per page), showing each case's `input`, `output`,
  `grade.score`/`checks` and `failures` (code plus message). Failed cases are shown first,
  behind a filter.
- Per member: cost and latency summed from each case's `operations[]` when they are present.
  When they are absent the section is hidden.
- The local ranking is ordered by score, on the same `benchmarkId` and `benchmarkRevision`.
- A summary without an in-memory result shows "Per-case details are kept until Studio
  restarts" plus a Re-run button (spec D7).
- Failures appear inline on the run row, with the Engine's message and Retry.
  `benchmark_unavailable` gets a specific message ("This benchmark's dataset is missing from
  this build"), which is a D2 regression signal.

### T-C4. Tests (`ensembles/new/page.test.tsx`)

The run client is mocked at the module boundary.

- Run is disabled, naming the provider, when a fusion model's provider is not connected (U1).
- Run is disabled for HealthBench when OpenRouter is not connected, even though every fusion
  model is connected, and the message names the judge (U1).
- A run streams progress, then shows score, coverage, cost and the first case's output.
- Cancel calls abort, and the row shows "Stopped".
- A null score renders "—" and "No cases were graded".
- `failed benchmark_unavailable` renders its message, and Retry starts a new run.
- After the results store is cleared, opening a run shows the D7 note and Re-run.
- **No fabricated values are left:** the text from `questionBank` and `publicRankingSeeds`,
  such as "GPQA Diamond", appears nowhere in the rendered page.
- Coverage: add `src/lib/ensemble-store.ts` and `src/lib/run-results-store.ts`. The page itself
  is checked by these tests, not by the coverage threshold, as in OME-1415.

### T-C5. Manual end to end

Use `next dev` against the runtime run from source, with a real provider connected. Capture
screenshots for the PR.

1. A 2-model fusion plus a synthesizer, on IFEval with sample size 5, completes with a real
   score.
2. Re-run it with the cache on: it is faster, and the cost shows the cache's savings.
3. Cancel in the middle of a run.
4. A fusion using a disconnected provider is blocked. HealthBench with OpenRouter disconnected
   is blocked with the judge message (U1).
5. Copy the recipe, import it through `?recipe=`, and get the same fusion back.

## Slice D1 — runtime `--benchmark-assets-dir` (`packages/screamingface`)

Follow the `sdlc-python` loop, using the card's `screamingface` stack.

### T-D1.1. `RuntimeConfig.benchmark_assets_dir: Path | None = None`

- It is resolved in `__post_init__`. The `assets_dir` property returns it when it is set.
- RED tests: the default is unchanged; the override resolves `~` and relative paths; it is
  absolute.

### T-D1.2. CLI and server

- `up` (and `run` if present) gets `--benchmark-assets-dir PATH`. The value reaches the
  Engine's `URL4_BENCHMARK_ASSETS` (`server.py`) and Scoreboard's seeding is unchanged.
- `status` and `doctor` report bundle status from the effective folder. This reuses the
  runtime-state record pattern from #1217 if that has merged, and otherwise records the folder
  in `runtime.json` the same way.
- `prepare` keeps writing to `data_dir/benchmark-assets`, and errors if it is given
  `--benchmark-assets-dir`.
- RED tests:
  - the env passed to `create_local_app` carries the override;
  - `doctor` lists the six bundles as prepared from a fixture folder;
  - `prepare` combined with the option exits non-zero with a clear message;
  - a missing override folder fails `up` before services start, with the path in the error.
- CHANGELOG entry and README "Runtime" section.

## Slice D2 — bundle the datasets in Studio

### T-D2.1. `src-tauri/before_build.sh`

- After the sidecar step:
  - `runtime/dist/screamingface-runtime/screamingface-runtime prepare --all --data-dir runtime/build/benchmark-data`
    (`HF_TOKEN` is passed through when set);
  - then `--list` must show all six as `prepared`, or the script exits 1;
  - then `rsync -a --delete runtime/build/benchmark-data/benchmark-assets/ src-tauri/resources/screamingface-runtime/benchmark-assets/`.
- The existing `rm -rf` of `_internal` and the executable does not touch `benchmark-assets/`.
- A test via the bats-free shell harness `src-tauri/tests/before_build_test.sh`: it stubs the
  sidecar binary to print a fake `--list`, and asserts a non-zero exit when one bundle is
  `missing`.

### T-D2.2. `runtime_process.rs`

- `sidecar_command(...)` appends `--benchmark-assets-dir <resource_dir>/screamingface-runtime/benchmark-assets`
  only when that folder exists. In dev runs (`tauri dev` without bundling), the runtime then
  falls back to the data directory.
- RED `cargo test`: the argument is present when the folder exists and absent when it is
  missing, and the path is built from the resource dir.

### T-D2.3. `runtime/verify-sidecar.sh`

- Add: `/v1/benchmarks` returns 8 rows. Then, for each bundle's first benchmark (skipping
  DRACO), a 1-case run must emit `case_loading completed`. The expected terminal state with
  no provider is `succeeded` with `score: null`.

### T-D2.4. Build and measure

- Run `tauri build` from `apps/screamingface-studio` and record the DMG size in the ledger. It
  should be within ±2 MiB of 304.9 MiB.
- Install the DMG, connect one provider, and run a 3-case IFEval and a 3-case MedXpertQA from
  the app. This **verifies grading against the read-only bundled folder**, which closes the
  open item in the table above.

## Gates (all run locally before each PR; Studio has no CI)

```sh
# A, B, C, D2 (frontend)
cd apps/screamingface-studio/frontend
npm ci && npm run lint && npm run typecheck && npm test -- --coverage && npm run build
# D2 (Rust)
cd ../src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo test
# D1 (packages/screamingface, card stack `screamingface`)
cd packages/screamingface && uv run ruff check && uv run ruff format --check && uv run pyright \
  && uv run pytest -n auto --dist worksteal --cov=screamingface --cov-fail-under=95 -q \
  && uv run --extra notebook python scripts/check_notebooks.py
```

## Filing (at each PR-open, after your confirmation)

- Each slice is filed as one leaf under **OME-1308**, self-assigned, with `actor: agentic`.
- Landing labels: `desktop` for A, B, C and D2 (owner decision 2026-10-09, as OME-1415);
  `client-sf` for D1.
- Each PR gets its own ledger in `docs/work/`. This umbrella ledger tracks the five.

## Open items carried, not blocking

- Grading from the read-only bundled folder is closed by T-D2.4.
- The Engine catalog has no judge or web-search fields (U3 is a Studio stopgap until the parity
  unit in spec §5).
- Trimming IFEval's 64 MB of `nltk_data` (spec §5).
- The OME-1415 mirror still says `In Progress` in the main checkout.
