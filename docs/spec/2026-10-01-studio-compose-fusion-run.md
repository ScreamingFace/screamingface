---
status: approved 2026-10-09 (D10 + §4.4 amendment approved)
ticket: unfiled (leaves under epic OME-1308, filed at PR-open)
date: 2026-10-01
depends_on: OME-1415 (Studio Models page un-mock, merged #1137)
---

# Studio Compose Fusion — run a real fusion against a real benchmark

## 1. Problem

OME-1308 (E18 · A local app) replaces the Studio mock one feature at a time. The Models
page is done (OME-1415). On Compose Fusion (`frontend/src/app/(studio)/ensembles/new/page.tsx`)
only the model catalog is real. The rest is mocked:

- **Benchmarks** are a hardcoded list at `page.tsx:119`: GPQA, MMLU Pro, HumanEval+, ARC
  and MATH-500. None of them is installed in the Engine.
- **Running** is fake. `RunsPanel.startRun` (`page.tsx:1112`) advances a 110 ms
  `setInterval` for 20 ticks. It makes up each model's score from char codes
  (`scoreForModel`, `:426`), sets latency to `1100 + i*187`, and sets
  `score = min(95, baseline + 8 + 3n)`.
- **Results** are fake. Every run shows the same 8-question `questionBank` (`:443`),
  correctness is an FNV hash of the run id, the reasoning is canned, and the
  `publicRankingSeeds` are hardcoded (`:650`).
- **Cache toggles and the OM-compute choice** are saved with the run and change nothing.
- **Custom benchmark upload** (`:1193`) turns a file's line count into a "benchmark".

The Engine already runs on `127.0.0.1:9108` inside the Studio runtime and has everything a
run needs. Studio's TypeScript client (`lib/engine/client.ts`) covers only connections,
models and health.

## 2. Decisions (confirmed with the owner, 2026-10-01)

| # | Decision |
|---|---|
| D1 | **End to end means a real run with real results.** Publishing to Scoreboard is out of scope: the Publish control is disabled and labelled "Coming soon". It becomes its own unit, which shares a Scoreboard client with the homepage and the Leaderboard. |
| D2 | **Fusion score only.** The Engine scores the whole candidate, never single members. The fake per-model scores, `baseline` and gain go away. Per-member data is limited to what the Engine reports (cost/usage and latency per operation). A real baseline needs solo member runs; that is a later unit. |
| D3 | **The Engine is the only source of benchmarks.** The picker reads `GET /v1/benchmarks`. Custom file upload is removed, because the Engine has no such input. |
| D4 | **Studio links the candidate itself**, exactly as the SDK does: `(candidate:0.0:<quoted candidate url4>, <benchmark url4>)!''` (`packages/screamingface/src/screamingface/_evaluation/linking.py:34`). Checked 2026-10-01 with the SDK's own `link_candidate`: Studio's canonical recipe text, wrapped this way, matches the SDK's output byte for byte. Studio does not send the SDK's `_sf_recipe` metadata source; the Engine never reads it. |
| D5 | **The webview talks to the Engine directly** over `fetch` and `WebSocket`. CORS already covers Studio's origins with wildcard methods and headers (`screamingface_engine/cors.py`, OME-1403), so the `URL4-Capability` and `Prefer` headers pass. |
| D6 | **Unsupported controls are hidden, not faked.** Studio has no reducer/loop script selection, majority vote or weights on this page, and the Engine supports none of them; a synthesizer model does all combining. Studio already hardcodes those fields (`buildDraft`, `:1721`), so this removes nothing users can change. The OM-compute choice is shown disabled, labelled "Coming soon", as on the Models page (OME-1415 D4). |
| D7 | **No new persistence in this cut.** Saved fusions stay in localStorage, unchanged. Each run's summary (a few hundred bytes) also goes to localStorage, so run history and the local ranking survive a restart. The full `CandidateResult`, with per-case details, is kept in memory only, until Studio restarts or the page reloads. A full result can be several MB, and localStorage has roughly 5 MB per origin. Old mock runs are dropped when the persisted store is migrated. A later unit adds durable storage (§5). |
| D8 | **Recipe import accepts exactly what Copy produces.** `?recipe=` parses canonical url4 from `recipeToUrl4`, so copying a recipe and importing it gets the same fusion back. |
| D9 | **One cache switch.** AI Gateway's cache control is a single opt-out flag, `use-cache` (`apps/aigateway/src/aigateway/core/request_cache/global_controls.py`). It deliberately refuses `no-store`, `no-cache` and `ttl`, and a request carrying any of them skips the cache entirely. The Engine passes on only "participate or not" (`screamingface_engine/world/cache.py`). So a run either reads and writes the cache, or does neither. "Use cache" and "Save to cache" become a single **Use cache** switch, on by default. On sets `participate: true`; off sends `Cache-Control: no-store`, which the Engine turns into `use-cache: false`. Separate read and write control would be an AI Gateway feature, not a Studio one. |
| D10 | **All benchmark datasets ship inside the app (for now).** On a fresh install every run failed with `benchmark_unavailable`, because the Engine reads datasets from disk and only the CLI (`screamingface prepare`) downloads them. The owner chose to bundle all six bundles (8 benchmarks) in the installer. Measured 2026-10-05 with two real `tauri build` DMGs from the same sidecar and frontend: **227.3 → 304.9 MiB (+77.6 MiB, +34%)**. The installed app grows by +293 MiB; the zipped .app, a stand-in for the update download, by +84.5 MiB. ContractEval (209 MB raw) and IFEval (66 MB raw, 64 MB of it `nltk_data`) are about 97% of the growth. A run against the datasets in a read-only folder (`chmod -R a-w`) loaded cases for all six bundles with no write errors. The hosted Engine is unchanged; its `-benchmark` image already bakes the datasets in (`Dockerfile.benchmark`). Revisit later with on-demand downloads or a hybrid. |

## 3. Engine contract used

| Call | Use |
|---|---|
| `GET /v1/benchmarks` | Picker: `id`, `title`, `description`, `revision`, `case_count`, `origin`, optional `focus`, `href` |
| `GET /v1/benchmarks/{id}?limit=N` | The benchmark's url4 for exactly N cases (`1 ≤ N ≤ case_count`, else 422). `candidate_binding` is `"candidate"`. |
| `POST /token` | `{token}`: an HS256 capability JWT whose `sub` is a fresh, single-use topic |
| `WS /ws?ticket=<token>` (subprotocol `cloudevents.json`) | First frame sent: `ai.url4.attach {from_sequence: 0, cache: {participate}}` |
| `GET /?q=<linked url4>`, headers `URL4-Capability: <token>`, `Prefer: respond-async` | 202. Results arrive on the socket. 428 if no socket is attached; 409 if the topic was reused. |
| Socket events | `ai.url4.started`; `ai.url4.log` (progress when `sf.progress.schema = screamingface.benchmark-progress.v1`, carrying `completed`, `graded` and a running `score`); `ai.url4.span`; `ai.url4.cost.usage`; `ai.url4.result` with `{body \| artifact}`; `ai.url4.terminated` with `{status, error?}`; `ai.url4.error` |
| `GET /artifacts/{id}` | Fetches a result too large to send inline (over 1 MiB), with the capability header |
| Stop | `ai.url4.stop {reason}` sent on the socket. Fallback: `DELETE /?topic=` (204, idempotent). |

The result body is a `CandidateResult` (`screamingface.candidate-result.v1`): `benchmark_id`,
`benchmark_revision`, `case_count`, `score` (it can be negative), `coverage`, `metrics`,
`cases[]` (`status`, `case_id`, `input`, `output`, `grade{method, score, metrics, checks}`,
`failures`, `operations[]`), `failures[]` and optionally `inverted_grade`
(`benchmarks/contract.py:409`).

## 4. Design

Five PRs, each a leaf under OME-1308. Slices A, B, D1 and D2 have no dependencies on each
other, except that D2 needs D1. C needs A and B. A real run in the packaged app also needs D2.
D1 lands in `packages/screamingface` and D2 in `apps/screamingface-studio`, so they are
separate leaves, per the one-leaf-per-package rule.

### 4.1 Slice A: benchmark picker from the Engine

- Add `listBenchmarks()` to `lib/engine/client.ts`, using the same `request`/`listData`/
  problem+json handling as `listModels`.
- Add `lib/benchmark-store.ts`, built like `model-store.ts`: states `idle | loading | ready |
  error`, with retry.
- `RunsPanel` drops the `benchmarks` constant and custom upload, and reads the store. Each
  option shows its title, its description or focus, and its case count. The sample-size
  presets (1/50/100/custom/Full) are clamped to `case_count`.
- Empty, loading and error states each get an inline message. Run is disabled until a
  benchmark is chosen.

### 4.2 Slice B: Engine run client (no UI)

Add `lib/engine/run.ts`:

- `linkCandidate(candidateUrl4, benchmarkUrl4)` implements D4. Quoting follows url4's
  `_quote`: escape `\` then `'`, then wrap in `'…'`.
- `startRun({candidateUrl4, benchmarkId, limit, cache, onEvent, signal})` runs these steps:
  1. Fetch the benchmark url4.
  2. Get a token from `POST /token`.
  3. Open the WebSocket and send the attach frame.
  4. Send `GET /?q=` with `respond-async`.
  5. Dispatch typed events as they arrive.
  6. Resolve with the final `CandidateResult`, or reject with an `EngineError`.
- `signal` aborts the run: send `ai.url4.stop`, then fall back to `DELETE /`.
- Artifact results are fetched from `/artifacts/{id}`. Socket frames are applied in
  `sequence` order; a heartbeat timeout reports the run as failed.
- **Fix in `recipe.ts`:** `paramQuery` must emit `?k=v&…&q=(<context>)`. The current
  `?k=v(<context>)` form cannot be parsed. Confirmed against the SDK's
  `compile_candidate`, which renders `/openai/gpt-4o?temperature=0.7&seed=3&q=($input)!'…'`.
- **Fix the import grammar (D8):** `parseRecipe` (`page.tsx:404`) accepts a
  `url4://name?models=…` form that `recipeToUrl4` never produces. It is replaced with a
  parser for `recipeToUrl4`'s output. A test runs `recipeToUrl4 → parseRecipe →
  recipeToUrl4` for fusion, pipeline and solo recipes, with and without params and prompts.

### 4.3 Slice C: wire up the Run panel

- `startRun` calls the slice-B client with `recipeToUrl4(root)`, the selected benchmark,
  the sample size and the cache switch (D9).
- The existing sample-size presets (1/50/100/custom/Full) stay. A preset larger than the
  benchmark's `case_count` is disabled. Custom is clamped to `1…case_count`.
- **While running:** a progress bar built from `completed / selected_case_count`, the
  running score, and member and synthesizer activity from `sf.activity.*` logs. A Cancel
  button stops the run (§4.2).
- **Results:**
  - Score, coverage, cost (from `cost.usage`, subtree total) and duration.
  - A per-case list with the real `input`, `output`, grade and failures. It replaces
    `questionBank` and the canned reasoning text.
  - Per-member cost and latency taken from case `operations[]`.
- **Removed:** `scoreForModel`, `baseline`, the gain display, `publicRankingSeeds`, the
  public ranking, and the local ranking's gain column. The local ranking stays, ordered by
  score on the same benchmark and revision.
- **New `SavedRun` (the summary, in localStorage):** `{id, benchmarkId, benchmarkRevision,
  benchmarkTitle, caseCount, full, cache, status, score, coverage, costUsd, durationMs,
  createdAt}`. It holds no cases. The store gets a version bump and a `migrate` that drops
  mock runs.
- **Full results (D7):** an in-memory `Map<runId, CandidateResult>` in a non-persisted zustand
  store. Opening a run whose result is no longer in memory shows the summary plus "Per-case
  details are kept until Studio restarts. Re-run to see them again." The note includes a
  Re-run button, which is cheap when the cache is on.
- **Failures:** `terminated.failed` or `timed_out`, an Engine that cannot be reached, and a
  provider not connected all appear inline on the run row with the Engine's message and a
  Retry button.

### 4.4 Slices D1 and D2: bundled benchmark datasets (D10)

**D1. The runtime can read datasets from a separate folder** (`packages/screamingface/src/screamingface/_runtime/`):

- `RuntimeConfig` gets an optional `benchmark_assets_dir: Path | None`. The `assets_dir`
  property returns that folder when it is set, and `data_dir / "benchmark-assets"` otherwise.
  Today the location is fixed (`config.py:54`), and `server.py:264` passes it to the Engine as
  `URL4_BENCHMARK_ASSETS`.
- `screamingface up` gets `--benchmark-assets-dir PATH`. `status` and `doctor` report that
  folder's datasets when the option is set. `prepare` keeps writing to the data directory,
  because a bundled folder is read-only.
- Tests:
  - the default location is unchanged;
  - the override reaches the Engine's environment;
  - `doctor` reports the bundled folder;
  - `prepare` refuses to use the bundled folder.
- Studio's sidecar build resolves `screamingface` from this monorepo (`runtime/pyproject.toml`
  `[tool.uv.sources]`), so no PyPI release is needed.

**D2. Studio bundles the datasets and points the runtime at them** (`apps/screamingface-studio/`):

- `src-tauri/before_build.sh`:
  - after the sidecar step, runs the sidecar's `screamingface prepare --all` into a build cache
    at `runtime/build/benchmark-data`, which is gitignored by `build/`;
  - copies the prepared bundles into
    `src-tauri/resources/screamingface-runtime/benchmark-assets/`, which is gitignored by that
    folder's `.gitignore`.
  - `prepare` skips bundles that are already prepared, so only the first build downloads, at
    about 2 minutes. `HF_TOKEN` is passed through when it is set.
  - The build fails if any bundle is not `prepared` afterwards. Shipping a partial set is a
    build error, not a warning.
- `src-tauri/src/runtime_process.rs` adds
  `--benchmark-assets-dir <resource_dir>/screamingface-runtime/benchmark-assets` to the sidecar
  command. This is the only Rust change: one argument, computed from Tauri's resource path.
  Tauri stays a thin shell.
- `runtime/verify-sidecar.sh` additionally checks that `/v1/benchmarks` lists every
  benchmark, and that a 1-case run gets past case loading for every bundle. A model failure
  is the expected outcome, since there is no provider.
- The datasets contain no Mach-O binaries, so `sign-sidecar.sh` is unaffected.
- **DRACO and DRACO 3-Pass** also need a Tavily web-search connection, which the local runtime
  does not have (`world/web_tools.py:135`, `benchmark_retrieval_unavailable`). Slice A's
  picker lists them but disables Run, with the label "Needs web search — not available in
  Studio yet". Configuring Tavily is out of scope.

## 5. Out of scope

- **Durable storage of fusions, runs and full results (D7).** A separate unit. What we found
  on 2026-10-01:
  - The Studio sidecar (`screamingface[runtime]`, `packages/screamingface/src/screamingface/_runtime/server.py`)
    bundles existing apps and owns no service of its own:
    - AI Gateway (port 9105) and the Engine's `create_local_app` (port 9108) run in one
      process.
    - Scoreboard (port 9106) runs as a child process.
    - Gateway and Scoreboard each keep SQLite through Tortoise under the data directory,
      and the runtime runs their migrations.
  - The candidate options:
    1. Local-only workspace routes plus SQLite in the Engine's local app. No new port, no
       Rust changes, needs Engine-owner buy-in.
    2. A new bundled app, the cleanest separation, at the cost of a new component.
    3. Local Scoreboard, which models published scores rather than drafts.
  - Already rejected:
    - Files written through Tauri commands, because they put state in the Rust layer.
    - A split between localStorage and files, because two stores drift apart.
- On-demand or hybrid dataset download, and trimming IFEval's `nltk_data` (D10; Engine-owner
  question).
- **Notebook parity: a Tavily connection and catalog requirements**, the next unit after this
  one, as a leaf under OME-1308. Goal: anything a notebook can do, Studio can do.
  - A notebook runs DRACO by exporting `TAVILY_API_KEY` before `screamingface up`. The Studio
    sidecar, launched from Finder, has no such environment and no way to enter the key.
  - Tavily becomes an Engine connection (`/v1/connections/tavily`), stored by the local Engine
    and read by the runner, falling back to the env var.
    - It must not live in AI Gateway: "aigateway never calls Tavily and never holds a Tavily
      credential" (`request_cache/tavily_retrieval.py:11`).
    - Engine owners decide where the local Engine keeps the secret.
  - The catalog gains `judge` and `requires` fields, which replace Studio's
    `benchmark-presentation.ts` table (plan U1 and U3).
  - Audit the other notebook capabilities that come from env vars, such as `HF_TOKEN` and local
    providers.
- Publishing to Scoreboard (D1).
- Solo member baselines (D2).
- OM compute (D6).
- Reducer/loop scripts and weights (D6).
- Separate cache read and write control (D9; an AI Gateway feature).
- A hosted Engine URL (OME-1415 D5).
