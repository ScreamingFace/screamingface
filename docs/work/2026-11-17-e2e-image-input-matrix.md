---
ticket: OME-1950
stack: python
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-17
---

# e2e-image-input-matrix — workbench notebook that validates image and PDF input per model

## Intent

Prove the OME-1529 image-input feature against real models: a workbench notebook runs a
model × media × path matrix on the `local` target with known-answer pictures, and passes only
when every capable model reads the picture and every blind model is refused before a paid call.
Spec: `docs/spec/2026-11-17-e2e-image-input-matrix.md`.

## Planned changes

- Spec + plan: `docs/plan/2026-11-17-e2e-image-input-matrix.md` (tasks 1–6).

## Test plan

- Defined in the plan.

## Acceptance

- Spec §3 holds on one recorded paid local run; evidence bundle and `matrix.json` attached.

## Task 4 — gold Cases calibration (2026-11-17, paid, local on a Mac)

- **Stack:** the workbench `local` target (`workbench.targets.local_stack`: `screamingface up`
  on :9105/:9106/:9108 + an inspect Engine on a free port), assets root in the session
  scratchpad (ifeval copied from `~/.screamingface/benchmark-assets`, FigQA prepared fresh:
  181 Cases, digest `616aeb49…`, equal to the pin). Key via the `workbench-ui` launcher's
  resolver, never printed. Everything torn down after the run.
- **Served picture Benchmarks:** the Engine lists all eleven (FigQA, TableQA, MMMU mc/open,
  MathVista, HLE, HLE-Diamond, LABBench2 FigQA2/TableQA2 img, ZeroBench, MaCBench). Dropped as
  Linux-sealed (picture notebook `SEALED_ON_LINUX`): MMMU mc, MMMU open, MathVista, ZeroBench.
- **PDF Cases on any served Benchmark: no.** The inspect importer keeps only png/jpeg/gif/webp
  (`picture_input._media_type`); the candidate-input envelope admits PDF, but no Benchmark
  produces one. The PDF column is url4-only (spec §3.4).
- **`labbench2_figqa2_img`: not run.** Its dataset (EdisonScientific/labbench2) is gated and no
  `HF_TOKEN` is available here, so its Cases cannot be prepared. Gold Cases come from FigQA only.
- **Run:** `inspect-lab_bench_figqa`, Cases 1–10, `max_tokens` 4096, one evaluate per model.

  | Model | Score | Correct Cases | Spend (usage.cost_usd) | Trace |
  |---|---|---|---|---|
  | `google/gemini-3-flash-preview` | 0.7 | 1 2 4 6 7 8 9 | $0.0161105 | `cccebbf787ede4a486bd364f47ced91a` |
  | `openai/gpt-5-nano` | 0.4 | 1 2 7 10 | $0.00821811 | `aec1f586c91c8690006c72664a8fa905` |

  Both correct: 1, 2, 7. Kept **1 (gold B)** and **2 (gold F)**; gold read from the scorer's
  MET verdict on each CaseResult and cross-checked against the prepared `targets/<id>.json`.
- **Measured spend:** $0.0161105 + $0.00821811 = **$0.02432861** (budget $2).
- **Files:** `tests/e2e/workbench/fixtures/image_input/gold_cases.json`,
  `tests/e2e/workbench/test_gold_cases.py`.

## Task 6 — real proof (2026-11-17, paid, local on a Mac) — NOT MET

- **Stack:** as in Task 4 (same scratchpad assets root), key from the repo-root `.env`, never
  printed. `FIXTURE_REF` `6c127c63` (on `origin/e2e-image-input-matrix`; fixtures unchanged
  since). Deadline 1800 s.
- **quickstart on `local`: PASS**, trace `5db6bc8fd7f991d962f966f144cae332`, chain clean. First
  paid run of the local target; no workbench-side fix needed.
- **image_input_matrix on `local`: FAIL** (149 s). Matrix (url4 path; ✓ answered, ✗ error):

  | Model | png | jpeg | gif | webp | pdf |
  |---|---|---|---|---|---|
  | gemini-3-flash-preview | ✓ | ✓ | ✓ | ✓ | ✗ `internal_error` |
  | gpt-5-nano | ✓ | ✓ | ✓ | ✓ | ✗ `internal_error` |
  | claude-haiku-5.5 | ✓ | ✓ | ✓ | ✓ | ✗ `internal_error` |
  | llama-4-scout | ✓ | ✓ | ✓ | ✓ | ✗ `internal_error` (expected refuse) |
  | mistral-small-24b (control) | ✗ | ✗ | ✗ | ✗ | ✗ (all `internal_error`, expected refuse) |

  Every image answer was exactly `7392`, each with 1 provider dispatch under its trace.
  Benchmark path (`inspect-lab_bench_figqa` Cases 1, 2): all four vision models answered both
  (graded correct); mistral was refused at admission with `intent_error`. All Case pictures
  fetched back with matching digests (no media failure).
- **Spend:** budget counter $0.2665970 = 25 url4 calls charged at the $0.01 estimate + the
  mistral Benchmark run at its $0.01 projection + real Benchmark spend $0.0065970
  (0.0027945 + 0.0013165 + 0.0014758 + 0.0010102). Real url4 spend is not reported (sync body
  has no cost); 16 image calls reached a model.
- **Trace verdict:** 20 reported ids (16 url4 + 4 Benchmark), no hop gaps,
  `unattributed_gateway_lines: 0`. The only failure reason is the notebook's own verdict.
- **Runtime assumptions from the final review:** (a) a Benchmark run refused at admission
  reaches the notebook as `ScreamingFaceError.code == "intent_error"`: **holds**. (b) the sync
  200 body carries the reply as text: **holds**. (c) gateway dispatch lines carry `[gateway] `
  and `trace_id=`: **holds** (`chat_calls` = 1 on every answered url4 cell, 2 per Benchmark run).
- **Review Focus 1 (mistral, url4):** expected `refused`, 0 upstream calls. Observed: 0
  upstream calls (the gateway's 422 backstop opened accounting, no dispatch); the repro shows the Engine
  ended the run `intent_error: openrouter cannot accept a image_url content part:
  modality_unsupported image` (engine.log). **But the sync `GET /?q=` answered
  `502 internal_error`**: `rest/routes.py::_sanitized_error` scrubs every code outside
  `ENGINE_ERROR_CODES` to `internal_error`, and `intent_error` is not in it. So the notebook
  cannot tell this refusal from a crash. Runtime issue, not fixed here.
- **Review Focus 2 (llama-4-scout):** pictures answered (as expected). The PDF cell never
  reached admission: see the next item. Not verified.
- **PDF column, all models:** the Engine refused the source before any model call:
  `unsupported_content_type: attachment source '…/codeword.pdf' (;accept=application/pdf)
  returned Content-Type 'application/octet-stream'`. raw.githubusercontent.com serves `.pdf` as
  octet-stream (images get their real type). Surfaced as `internal_error` for the same reason.
  Fixture-hosting issue; the fix is a direction choice (blockers).
- **Repro** (scratch script, same stack, $0): mistral png → `502 internal_error`, trace
  `3820e8590d9ffb82b56459199715d66e`; gemini pdf → `502 internal_error`, trace
  `f4eaf39bf93a004f74da9daf8cc44d81`; the Engine's `run terminated` lines above come from it.

## Task 6 — re-run, GREEN (2026-11-17, paid, local on a Mac)

- **Fixes for both blockers:** fixtures now come from jsDelivr (`8b874f558`, the PDF keeps
  `application/pdf`), and the Engine reports `intent_error` on the sync answer with its message
  withheld (branch `engine-public-intent-error`, `b546c09f5`; applied to this working tree for
  the run only and reverted afterwards, nothing under `apps/` committed here).
- **Run:** `test_notebook[local-image_input_matrix] PASSED` in 140 s, `FIXTURE_REF` 6c127c630,
  first trace `b511703ec467449dcc87b45fdcfae3b8`.
- **Matrix (34 cells, all as expected):** url4 19 answered (4 vision models × png/jpeg/gif/webp
  plus pdf for gemini, gpt-5-nano and haiku) and 6 refused (mistral × 5 media, llama-4-scout pdf);
  Benchmark 8 answered (4 vision models × FigQA Cases 1, 2) and 1 refused (mistral, admission).
- **Measured spend:** $0.0406 (OpenRouter key usage delta).
- **Landing:** this branch now depends on the Engine leaf merging first (the notebook stays red
  on `main` until then).

## Task 6 — models from the OME-1529 timeline (2026-11-17, paid)

- Added the timeline's green OpenRouter models: `gemini-2.5-flash`, `claude-haiku-4.5`,
  `gpt-4o-mini` (`b85c5cc72`). `gpt-4o-mini` + url4 PDF answered "2": the Engine sends the file
  part with no filename, and OpenAI models never see it (a direct OpenRouter call returns 400
  without one and reads it with one). Filed **OME-1942** (bug, Triage) and dropped `gpt-4o-mini`
  (`24b1e2f88`).
- **7-model run GREEN:** `test_notebook[local-image_input_matrix] PASSED`; url4 29 answered +
  6 refused, Benchmark 8 answered + 1 refused + 4 wrong (tolerated). Spend $0.136.
- **Hugging Face:** wired (patch kept in the scratchpad), blocked because the `.env` HF token
  lacks "Make calls to Inference Providers" (403). The owner is asking Irina for access.

## Hugging Face — why it failed, what it took, what is left (2026-11-17, paid)

Five separate causes, peeled one at a time; each was proved, not guessed.

| # | Symptom | Cause (evidence) | Status |
|---|---|---|---|
| 1 | every HF call 403 | `.env` `HUGGINGFACE_KEY` (user IrinaMB, fine-grained) lacked "Make calls to Inference Providers"; router said so verbatim | fixed by Irina |
| 2 | HF cells "not in the gateway listing" | the gateway lists only its seed ids, which carry a provider suffix (`huggingface/google/gemma-4-31B-it:deepinfra`); bare ids are never listed | notebook now uses seed ids |
| 3 | HF rows would read text-only | `AIGW_HUGGINGFACE_LIVE_MODALITIES` defaults **off** (OME-1537): without it every HF row has no `input_modalities` and image parts to HF are refused. The workbench `local` target now sets it (allowlisted, target-set) | worked around in the workbench; **product default still off** |
| 4 | `invalid expression path …:deepinfra` (url4) and `invalid_model_route` (Benchmark) | a url4 path segment admits no `:`. The Engine already routes `:` as `~` (OME-873, `registry.encode_route_id`), and `sf.Model` expects that route form (`sf.models.list()`); the notebook passed the raw gateway id | fixed in the notebook (`image_url4.route_id`) |
| 5 | `Kimi-K3:deepinfra` + GIF → `internal_error` | DeepInfra answers **415 Unsupported media type** for GIF on Kimi-K3 (direct router call); PNG works. The router declares `image`, not per-format, and our 415 surfaces as a scrubbed `internal_error` | open |

Also open, not HF: `gemini-2.5-flash` via url4 answered with the literal `src=https://…;accept=…` line once per run (PDF in one run, JPEG in the next). Direct OpenRouter calls with and without that text read `7392` 8/8, so the pipeline's request needs capturing before a cause is named.

Result with 1–4 fixed: url4 — `gemma-4-31B-it` and `Kimi-K3` read png/jpeg/webp (`7392`), gemma also GIF; both refused PDF with 0 calls; `gpt-oss-120b` refused all media with 0 calls. Benchmark — gemma and Kimi answered FigQA Cases, `gpt-oss-120b` refused at admission.

### What the product needs for HF image input

1. Turn HF live modalities on where image input is offered (runtime `up`, hosted chart), or seed static modalities for the HF list; otherwise HF vision models are refused images by default.
2. `sf.Model` could accept the gateway id and apply `encode_route_id` itself; today a user copying the gateway id gets `invalid_model_route`.
3. Map a provider 415 (unsupported media type) to the refusal family (`unsupported_content_part` → `intent_error`) instead of a scrubbed `internal_error`; or carry per-format modality evidence.
4. Find why one url4 call per run can reach the model with the `src=` line and no picture (capture the request).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `packages/screamingface/tests/e2e/workbench/`: `image_matrix.py`, `image_url4.py`,
  `image_notebook.py`, `fixtures/image_input/*`, `notebooks/image_input_matrix.ipynb`,
  `build_notebooks.py`, `bundle.py`, `targets.py`, README, tests; spec + plan + this ledger.
- **Commits:** see the PR (squash).
- **Gates:** ruff, ruff format, pyright 0 errors; workbench 363 passed, 3 skipped; full package
  pytest 7606 passed, 97.03 % coverage (earlier run); `build_notebooks.py --check` clean.
- **Real runs:** 7-model OpenRouter matrix PASSED ($0.136); with HF the url4 and Benchmark paths read
  images on gemma-4 and Kimi-K3 and refuse correctly; the full 10-model matrix is green only with
  OME-1949, OME-1945 and OME-1946 merged.
- **Deviations:** fixtures on jsDelivr (spec D5 amended); provider-refusal table (spec §3.2
  amended); gpt-4o-mini out until OME-1942; `FIXTURE_REF` stays the fixtures' commit `6c127c63`
  (pushed, reachable) — re-pin to the squash commit on `main` after merge.

## Close-out (2026-11-18)

- Merged as `1e0200977` (#1891), after `#1888`, `#1889` and `#1890`. The four `docs/tasks` mirrors are now set to done.
- `FIXTURE_REF` stays on `6c127c63` and is NOT re-pinned to the squash commit. jsDelivr returns
  403 "Package size exceeded the configured limit of 50 MB" for `codeword.pdf` and `token.gif` at
  `1e0200977`, because the repo at a main commit is over its per-package limit. At `6c127c63` all
  six fixtures serve 200 with the right Content-Type. GitHub keeps that commit through
  `refs/pull/1891/head`. If it ever stops serving, move the fixtures to a small dedicated repo or
  release asset. Re-pinning to another main commit would not fix it.
