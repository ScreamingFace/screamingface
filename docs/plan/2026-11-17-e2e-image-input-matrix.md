# E2E workbench — image input matrix notebook · plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A workbench notebook `image_input_matrix` proves on the paid `local` target that every
capable model reads a known-answer picture or PDF, through both url4 attachments and Benchmark
Cases, and that every blind model is refused before a paid call.

**Architecture:** Test code only, under `packages/screamingface/tests/e2e/workbench/`.
- A pure module `image_matrix.py` holds the cell logic: expectation from `/v1/models`, the answer
  check, the row model.
- The url4 path calls the local Engine directly (`POST /token`, then `GET /?q=<url4>`), because
  the SDK's `evaluate(url4=…)` only replays a Benchmark-owned evaluation URL4 (spike S0, below).
- The Benchmark path uses the public SDK, `sf.evaluate(model, benchmark=…, cases=[…])`.

**Tech Stack:** Python 3.12, httpx (already a dependency), nbclient and the workbench builder.
Pillow is used once, at fixture-generation time only, through `uv run --with pillow`. It is
never a dependency.

**Spec:** `docs/spec/2026-11-17-e2e-image-input-matrix.md`.

## Spike S0 — resolved while planning (2026-11-17)

- `Client.evaluate("<url4>")` goes through `_replayed_url4` (`_evaluation/url4.py:234`), which
  requires a Benchmark-owned outer expression with an embedded `candidate` binding. It cannot run
  a bare model call.
- The Engine runs any url4 expression:
  - `POST /token` mints a capability JWT, with no auth (`rest/routes.py:686`);
  - `GET /?q=<url4>` starts the run and answers synchronously within `sync_max_wait_s`
    (`routes.py:806`). It adopts a `traceparent` header.
- The engine test `test_fair_share_fetch_bytes.py:162` already runs this exact shape locally:
  `/{MODEL}(src=https://…/chart.png;accept=image/png)!'…'`.
- **Consequence:** no SDK change. The notebook mints its own W3C traceparent per call, so the
  trace chain verdict still holds.

## Global Constraints

- **Code location:** no shipped-package change. Everything lives under `tests/e2e/workbench/`
  and `docs/`.
- **Secrets:** come from env only. The executed notebook and `matrix.json` are redacted by the
  existing `redaction.py`.
- **Target:** `local` only (`targets: ["local"]`). The notebook is skipped elsewhere, and is a
  failure under `SCREAMINGFACE_WORKBENCH_REQUIRE_ALL`.
- **Fixture refs:** every fixture URL is `https://raw.githubusercontent.com/ScreamingFace/screamingface/<FIXTURE_REF>/<path>`.
  The fetched bytes must match the manifest sha256 before any model call.
- **Spend:** default `BUDGET_USD = 0.50`. The workbench budget guard runs before each call.
- **Unknown is never a pass:** a cell whose expectation can't be derived is `skipped`, with a
  reason.
- **Gates:** `uv run ruff check .`, `ruff format --check .`, `pyright`, `pytest -n auto` with
  the coverage floor, `scripts/check_notebooks.py`, and `build_notebooks.py --check`.

## Review Focus

1. **Text-only control model:** it must produce `refused` on the url4 path with **zero**
   gateway chat calls under its trace, not `error`.
2. **A model that takes images but not PDFs** (`meta-llama/llama-4-scout`): the png to webp
   cells are expected to answer, and the pdf cell is expected to be refused.
3. **Stale `FIXTURE_REF`**, or a 404 from raw.githubusercontent: this is a setup error naming
   the URL. No model call is made.
4. **A model answers with extra text** ("The number is 7392."): it passes. A different number
   fails.
5. **One model misses a gold Case** while the others answer it: the row says `wrong` and the
   notebook still passes. If every vision model misses it, the notebook fails.

## Model set (from OpenRouter's live `/api/v1/models`, 2026-11-17)

| Model | `input_modalities` | Role |
|---|---|---|
| `google/gemini-3-flash-preview` | text, image, file, audio, video | vision + pdf |
| `openai/gpt-5-nano` | text, image, file | vision + pdf |
| `anthropic/claude-haiku-5.5` | text, image, file | vision + pdf |
| `meta-llama/llama-4-scout` | text, image | vision, **no pdf** |
| `mistralai/mistral-small-24b-instruct-2501` | text | **text-only control** |

All are the cheapest tier of their family. The notebook re-reads modalities from the local
gateway at run time. This table only sets defaults.

---

### Task 1: Known-answer fixtures

**Files:**
- Create: `tests/e2e/workbench/fixtures/image_input/make_fixtures.py`. A dev-time script, run
  with `uv run --with pillow==11.3.0 python make_fixtures.py`.
- Create: `fixtures/image_input/{token.png,token.jpg,token.gif,token.webp,codeword.pdf,manifest.json}`.
- Test: `tests/e2e/workbench/test_image_fixtures.py`.

**What the script does:**
- It renders the 4-digit token `7392` in large dark-on-light type on a 320×120 canvas and saves
  it as png, jpeg, gif and webp.
- It writes a one-page **text** PDF by hand, with stdlib only, containing the code word
  `HELIOTROPE`, so a PDF-capable model reads text rather than an embedded image.
- It writes `manifest.json`: `[{path, media_type, sha256, bytes, expected}]`.

**Steps:**
- [ ] Write the failing tests:
  - every manifest entry exists;
  - its sha256 and byte size match;
  - the file's magic bytes match its `media_type`
    (`\x89PNG`, `\xff\xd8\xff`, `GIF89a`, `RIFF....WEBP`, `%PDF-`);
  - every file is under 64 KiB;
  - the 5 media types are each covered exactly once.
- [ ] Run the tests and see them fail.
- [ ] Write the script and generate the fixtures.
- [ ] Run the tests and see them pass.
- [ ] Commit `feat(e2e): known-answer image and PDF fixtures for the image input matrix`.

### Task 2: `image_matrix.py`, the pure cell logic

**Files:**
- Create: `tests/e2e/workbench/image_matrix.py`.
- Test: `tests/e2e/workbench/test_image_matrix.py`.

**Interfaces (produced):**
```python
Path_ = Literal["url4", "benchmark"]
Observed = Literal["answered", "refused", "wrong", "error", "skipped"]

@dataclass(frozen=True)
class Cell:
    path: Path_; model: str; media_type: str
    expected: Literal["answer", "refuse", "unknown"]
    observed: Observed; answer: str | None; code: str | None
    trace_id: str | None; spend_usd: Decimal | None; reason: str | None

def modality_of(media_type: str) -> Literal["image", "pdf"]
def expectation(models_listing: Mapping, model: str, media_type: str) -> Literal["answer", "refuse", "unknown"]
def answer_contains(answer: str, expected: str) -> bool        # casefold, collapse whitespace; digits must not be part of a longer number
def classify(expected, *, answer, error_code, expected_value) -> Observed
def verdict(cells: Sequence[Cell]) -> list[str]                # the failures, in plain words; [] = pass
```

**`verdict` rules:**
- `expected=answer` with `observed` of `refused` or `error` → failure.
- `expected=refuse` with `observed=answered` → failure, worded "capability table stale".
- `expected=refuse` with `observed=error` (a non-refusal code) → failure.
- url4 `wrong` → failure.
- Benchmark `wrong` fails only when every `expected=answer` model is `wrong` on that Case.

**Steps:**
- [ ] Write the failing tests:
  - a table over `expectation`, covering the gateway listing shapes: modalities present;
    `file` mapping to pdf; a model missing from the listing gives `unknown`;
  - `answer_contains`: `"The number is 7392."` → True; `"17392"` → False; `"7 3 9 2"` → False;
    `"heliotrope"` matches `HELIOTROPE`;
  - `classify` with refusal codes `intent_error` and `unsupported_content_part`;
  - every `verdict` rule above, including Review Focus 1, 2, 4 and 5.
- [ ] Run the tests and see them fail.
- [ ] Implement.
- [ ] Run the tests and see them pass.
- [ ] Commit `feat(e2e): image input matrix cell logic`.

### Task 3: url4 path client (Engine-direct)

**Files:**
- Create: `tests/e2e/workbench/image_url4.py`.
- Test: `tests/e2e/workbench/test_image_url4.py`, using `httpx.MockTransport`.

**Interfaces:**
```python
def fixture_url(ref: str, path: str) -> str
def verify_fixture(client: httpx.Client, url: str, sha256: str) -> None   # raises FixtureError(url, reason)
def run_attachment(client: httpx.Client, engine_url: str, model: str, url: str,
                   media_type: str, prompt: str) -> Url4Outcome           # Url4Outcome(trace_id, answer|None, error_code|None, spend_usd|None)
```

**Behaviour:**
- `run_attachment` mints a traceparent and calls `POST {engine}/token`.
- It then calls `GET {engine}/?q=/<model>(src=<url>;accept=<type>)!'<prompt>'`, with the
  `Authorization` header and `traceparent`.
- A 200 body is parsed into the answer and the run's usage spend.
- A problem body is parsed into its `code` (`intent_error`, `x.source_*`, …).
- A 202 means the run outlived the sync bound. It is an `error` with code `sync_timeout`, never
  a pass.
- The prompt is quoted the way url4 Text requires. The url4 expression is built with
  `url4.build` and round-trip checked, not concatenated blindly.

**Steps:**
- [ ] Write the failing tests:
  - the expression round-trips through `url4.build`;
  - a sha256 mismatch and a 404 each raise `FixtureError` naming the URL (Review Focus 3);
  - 200 → answer; 422 problem → code; 202 → `sync_timeout`;
  - the traceparent sent equals the returned `trace_id`.
- [ ] Run the tests and see them fail.
- [ ] Implement.
- [ ] Run the tests and see them pass.
- [ ] Commit `feat(e2e): url4 attachment calls for the image input matrix`.

### Task 4: Gold Cases calibration

**Files:**
- Create: `tests/e2e/workbench/fixtures/image_input/gold_cases.json`:
  `[{benchmark, case, expected, note}]`.
- Modify: the ledger, recording the calibration run.

**Steps:**
- [ ] On `local` with `--paid`, list the served picture Benchmarks.
  - Drop the Linux-sealed ones: MMMU, MathVista, ZeroBench, and the others the
    `build_notebooks.py` picture builder lists.
  - Check whether any served Benchmark carries PDF Cases, and record yes or no.
- [ ] Run Cases 1 to 10 of `inspect-lab_bench_figqa` and `labbench2_figqa2_img` with
  `gemini-3-flash-preview` and `gpt-5-nano`, `limit` bounded by the budget.
- [ ] Keep 2 Cases per Benchmark that both models answer correctly. Record each Case's gold
  answer from `CaseResult`.
- [ ] Write a failing test that `gold_cases.json` has 2 to 4 entries, each with a non-empty
  `expected`, and names no Linux-sealed Benchmark.
- [ ] Commit the file, the test and the ledger. Record the measured cost of the calibration run.

### Task 5: The notebook, builder and verdict wiring

**Files:**
- Modify: `tests/e2e/workbench/build_notebooks.py`. Add `_image_input_matrix()` and register it
  in `_BUILDERS`.
- Create: `tests/e2e/workbench/notebooks/image_input_matrix.ipynb`, generated and output-free.
- Modify: `test_build_notebooks.py`, and `verdict.py` / `bundle.py` so `matrix.json` is written
  from the result.
- Test: `test_build_notebooks.py`, `test_bundle.py`.

**Notebook cells:**
1. A `parameters` cell: `MODELS`, `MEDIA`, `PATHS`, `FIXTURE_REF`, `BUDGET_USD`,
   `ENGINE_URL`, `GATEWAY_URL`, `EVENTS_PATH`.
2. Read `GET {GATEWAY_URL}/v1/models` and verify every fixture (Task 3). On a setup failure,
   stop before any spend.
3. url4 path: one `run_attachment` per (model, media) pair, rows built with `image_matrix`.
4. Benchmark path: `sf.evaluate(sf.Model(m), benchmark=b, cases=[…])` per vision model and gold
   Case.
   - A text-only control gets one run, expected `refuse` at admission.
   - `sf.fetch_media` must return bytes whose digest matches `CaseResult.media`.
5. A display cell: the matrix as an HTML table (model rows × path/media columns, ✓ ✗ ⊘ ?).
6. The single `workbench-result` cell: `WORKBENCH_RESULT={"trace_ids": [...], "matrix": [...]}`,
   then `assert not verdict(cells)`.

**Steps:**
- [ ] Write the failing builder tests:
  - the notebook exists with `targets == ["local"]` and
    `required_result == ["trace_ids", "matrix"]`;
  - it has exactly one `workbench-result` cell;
  - the `parameters` cell carries no secret;
  - `--check` passes after regeneration.
- [ ] Write a failing bundle test: a result carrying `matrix` writes a redacted `matrix.json`
  with answers capped at 200 characters.
- [ ] Implement, regenerate, and run the tests.
- [ ] Commit `feat(e2e): image input matrix workbench notebook`.

### Task 6: Real proof and docs

- [ ] Before anything else, run `quickstart` on `local` once with `--paid`. The local target
  has never run with a key; fix only workbench-side issues, and stop and report any runtime
  issue.
- [ ] Run `image_input_matrix` on `local` with the branch head as `FIXTURE_REF`. The ref must
  be pushed first, so push the branch; this needs no issue.
- [ ] Record in the ledger:
  - the matrix;
  - the spend;
  - the trace verdict;
  - each Review Focus outcome observed for real, with expected and observed results for items
    1 and 2.
- [ ] Add a README section "Image input matrix": how to run it, how to read the matrix, and the
  re-pin step after merge (spec §6).
- [ ] Run the full gates (Global Constraints).
- [ ] Commit `docs(e2e): image input matrix guide and real proof`.

## Done when

- All gates are green.
- A recorded paid local run where:
  - every vision cell answers;
  - llama-4-scout's PDF cell and every text-only cell are `refused`, with zero gateway chat
    calls under their traces;
  - the trace-chain verdict holds.
- After merge, a one-line follow-up re-pins `FIXTURE_REF` to the fixtures' commit on `main`.
