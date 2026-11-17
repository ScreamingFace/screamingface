# E2E workbench — image input matrix notebook

Status: draft for owner review · 2026-11-17 · builds on `2026-10-16-e2e-notebook-workbench.md`
and the image-input specs of epic OME-1529 (`2026-10-16-OME-1535-file-input-execution.md`).

## 1. Problem

Image and PDF input (epic OME-1529) is on `main` and well unit-tested, but nothing proves it
against real models:

- no replay tape or golden carries a picture;
- the paid board smoke (`tests/paid/test_imported_board_smoke.py`) checks report shape, not
  that the model saw the picture;
- `examples/18_picture_benchmarks.ipynb` is a user demo, off by default, with no assertions on
  answers;
- there is no per-model × media-type matrix, so a provider that silently drops a part, or a
  capability table that is wrong for one model, goes unnoticed.

## 2. Decisions (locked with the owner, 2026-11-17)

| # | Decision |
|---|---|
| D1 | A **workbench notebook** (`tests/e2e/workbench`), so it gets the trace-chain verdict, evidence bundle and UI. |
| D2 | **Both input paths**: Benchmark Cases (inline `data:` envelope, OME-1678) and url4 attachments (`src=…;accept=…`, OME-1543/1545). |
| D3 | **Known-answer oracle**: a pass means the answer contains a value only visible in the picture. |
| D4 | **Target `local` (paid, OpenRouter)** first; a replay snapshot is a follow-up. |
| D5 | url4 fixtures are committed to this public repo and fetched over https from a **commit-pinned `raw.githubusercontent.com` URL**. No engine or SDK change. |
| D6 | The Benchmark path uses **hand-picked Cases of existing picture Benchmarks** with a pinned gold answer. No new Benchmark. |

## 3. Shape

### 3.1 The notebook `image_input_matrix`

- Metadata: `{"targets": ["local"], "required_result": ["trace_ids", "matrix"]}`. Built by a new
  builder in `build_notebooks.py`, committed output-free, `--check` guards drift.
- `parameters` cell:
  - `MODELS`: four vision models, one per family through OpenRouter (Gemini, GPT, Claude, one
    open-weights model), plus one **text-only control** model. Exact ids are pinned in the plan
    from the live `/v1/models` listing.
  - `MEDIA`: `["image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"]`.
  - `PATHS`: `["url4", "benchmark"]`.
  - `FIXTURE_REF`: the commit sha the fixture URLs are pinned to.
  - `BUDGET_USD`, default small; the existing budget guard (spec §3.4) applies.
- One cell per path; each builds its rows of the matrix, then one `workbench-result` cell emits
  `WORKBENCH_RESULT={"trace_ids": [...], "matrix": [...]}`.

### 3.2 Expected outcome per cell

The notebook does not hard-code which model reads what. Before any paid call it reads the local
gateway's `/v1/models` and takes each model's `input_modalities` (the same evidence the engine
admission and the gateway use):

- the model declares the modality → **expect an answer**, which must contain the known value;
- it does not → **expect a refusal**, with zero paid model calls under that trace:
  - Benchmark path: a run-level `intent_error` from admission (`picture_admission.py`);
  - url4 path: the gateway's 422 `unsupported_content_part` surfaced as url4 `intent_error`
    (admission-time once PR #1853 merges; the assertion accepts either, keyed on the code).
- A model `/v1/models` lists as text-only but that answers correctly is reported as
  **capability table stale** — a failure, because the gateway would refuse it in production.

### 3.3 url4 path — known-answer fixtures

- `tests/e2e/workbench/fixtures/image_input/`: one picture rendered with a random 4-digit
  token (for example `7392`) and saved as png, jpeg, gif and webp; a one-page PDF with a code
  word. A `manifest.json` lists each file's media type, sha256, byte size and expected value.
- The files are generated once by a small script and committed (binary, a few KB each), so the
  bytes behind a pinned sha never change.
- URL: `https://raw.githubusercontent.com/ScreamingFace/screamingface/<FIXTURE_REF>/<path>`.
  The notebook checks the fetched sha256 against the manifest before the run, so a wrong or moved
  ref fails as a setup error, not a model failure.
- Prompt: "Reply with only the number (or word) shown in the attached file." The check
  normalises case and whitespace and asserts the expected value is in the answer.
- Expression: one model call per (model, media) cell with a single `src=<url>;accept=<type>`
  source, sent straight to the Engine (§6, S0).

### 3.4 Benchmark path — gold Cases

- A table in the notebook names, per picture Benchmark, one or two easy Cases and their gold
  answer, chosen in the plan by a calibration run. Benchmarks whose Case Digest is Linux-sealed
  (MMMU, MathVista, ZeroBench, …) are avoided so the notebook runs on a Mac.
- Each vision model runs those Cases through `sf.evaluate(model, benchmark=…, cases=[…])`.
- Scoring noise: a refusal or transport error is a hard failure; a wrong answer from one model
  is reported in the matrix as `wrong` but fails the notebook only when **every** vision model
  misses the same Case, which means the picture did not arrive.
- `CaseResult.media` / `sf.fetch_media` is asserted to return the digest-verified picture that
  was sent.
- PDF on this path is covered only if a served Benchmark carries PDF Cases; otherwise the PDF
  column is url4-only, stated in the matrix.

### 3.5 Evidence

- The standard bundle (`executed.ipynb`, `trace.json`, logs, spans).
- Plus `matrix.json`: one row per (path, model, media) with `expected`, `observed`
  (`answered|refused|wrong|error|skipped`), the answer excerpt (redacted, ≤ 200 chars), the
  error code, trace id and spend.
- The README gets a "Image input matrix" section: how to run it with `--paid` and how to read the
  matrix.

### 3.6 Cost guard

- Scale: 5 models × 5 media on url4 = 25 calls (the 5 control calls must not reach a provider),
  plus 4 vision models × at most 4 gold Cases on the Benchmark path = at most 16 runs.
- Fixtures are a few KB, so image tokens stay small; the existing projected-spend guard aborts a
  cell when the budget would be exceeded. The plan records the measured cost of one full run.

## 4. Out of scope

- The replay target and an image snapshot (follow-up, D4).
- Hosted dev / previews (no headless OAuth in the workbench).
- `blob:` refs and the engine blob store (OME-1890).
- An SDK attach-a-file API (OME-1547).
- Image token accounting checks (`2026-10-20-image-token-accounting.md`).

## 5. Landing

Single landing: `cross-unit/repo-dev-processes`, one leaf under epic OME-1636 (e2e notebook
workbench). Test code, fixtures and docs only; no shipped package changes.

## 6. Open questions

- **S0 — resolved 2026-11-17:** `evaluate(url4=…)` only replays a Benchmark-owned evaluation
  URL4, so the url4 path calls the local Engine directly (`POST /token`, then `GET /?q=<url4>`
  with a client-minted `traceparent`). No SDK change. Details in the plan.
- **Fixture ref after squash-merge:** a branch commit can be garbage-collected after the squash.
  The plan pins `FIXTURE_REF` to a commit on `main` in a one-line follow-up once the fixtures
  merge, and the sha256 check makes a stale ref fail loudly.
