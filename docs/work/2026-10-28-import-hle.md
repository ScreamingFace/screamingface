---
ticket: OME-1478
stack: screamingface-engine
status: done
started: 2026-10-28
finished: 2026-11-02
---

# import-hle — import the full HLE (Humanity's Last Exam), pictures included

## Intent

HLE is 2,500 expert-written questions across 100+ subjects; about 14% carry a picture. It is
judge-graded. inspect_evals ships it as `hle`, and the importer could not take it while a Case
could not carry a picture. OME-1271 (#1554) now saves an eval's pictures inside the Case, so the
full set (never the text-only subset) can become a Benchmark by Task replay, exactly as
LAB-Bench FigQA and TableQA did in OME-1327 (#1556). Onboarding only: no paid run and no
state-of-the-art run (that is OME-1672).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`,
  `.../benchmarks.py`: the two rows the importer writes for `inspect_evals.hle.hle:hle`, key
  `hle`; prose, provenance, baselines and the judge declaration filled by hand.
- The per-Benchmark test tables, one row each, as OME-1327: `test_benchmark_declaration.py`,
  `test_failure_policy_rows.py` (and its row counts), `test_inspect_imported_benchmarks.py`,
  `test_published_revisions.py`, `test_benchmark_fingerprints.py`.
- `.claude/test-change-approvals/OME-1478.json` for those prior-test edits.
- `docs/tasks/` mirror for OME-1478.

## Test plan

- RED first: the shared Benchmark tables gain the `hle` row before the declaration exists.
- Captured prompt equals what inspect_evals sends: run the real `hle` Task offline on a few real
  rows (one with a picture, one text-only) and compare the Case's messages byte for byte with
  the Sample inspect builds.
- The build-side replay reproduces the Case Digest with every pin forced (the importer's own
  second run).

## Acceptance

- `inspect-hle` registered, 2,500 Cases, pictures inside the Cases, every Case under
  `MAX_CASE_BYTES` and `MAX_PICTURES`; licence MIT (31 MIT precedents); no TODO left; no check
  surface.
- Both numbers the scorer returns kept: headline = `score`, `confidence` alongside.
- Relevant inspect-lane tests, ruff and pyright green on the touched files.

## Findings (2026-10-28, before any code)

- **Cases (real Hub data, `cais/hle` at `5a81a4c7`, the pin inspect_evals sets):** 2,500 Cases;
  342 (13.7%) carry exactly one picture (218 PNG, 115 JPEG, 6 WebP, 3 GIF by label). Largest
  Case 2,205,828 bytes (`hle_80658bf3`), none over `MAX_CASE_BYTES`, none over `MAX_PICTURES`;
  largest text-only Case 21,635 bytes. Whole Benchmark 118 MB of Case inputs, 123 MB with
  Grading Material (FigQA is 330 MB). Capture took all 2,500 with no refusal.
- **Prompt fidelity:** the captured Case equals the messages inspect_evals builds, for all
  2,158 text Cases (system text, blank line, question) and all 342 picture Cases (system text
  part, then the question and the picture's exact bytes).
- **Licence:** dataset card says MIT; 31 rows already carry MIT. Gated (`auto`); the cached
  `hf auth login` on this machine has access.
- **The importer refuses HLE** (`importer.py`, `_resolve_scorer`): `inspect_evals/regex_judge`
  lives in `inspect_evals.hle.scorers`, not the Task's module. Behind that, more refusals
  the code names: two judged scorers (`grader`, `grader_2`), so no scorer is conservable; the
  judge role arrives in a variable (`get_model(role=<unknown>) in scorers.py:93`); the
  headline is hle's own `accuracy`, and honouring it is refused for `attempt_preserving_mean`.
  Neither eval judge (`openrouter/z-ai/glm-5.3-flash`, `openrouter/google/gemini-3.7-flash`)
  is a declared gateway model. `confidence` is read by regex from the Candidate's reply, not
  from a judge; the two judge calls are two separate judges, each a `{score, confidence}`.
- Blocked on owner decisions; see the session report.

## Decisions (2026-11-02, owner)

- **Judge:** inspect_evals' maintained grading (`run_configs/default.yaml`): `regex_judge`, its
  primary judge `openrouter/z-ai/glm-5.3-flash` in the `grader` role, pinned with default.yaml's
  stanza (`temperature=0`, `max_tokens=32768`) plus `web_search=false`, and
  `redraw_repeats=True` so its three attempts are three draws, not one cached reply. The paper-faithful
  o3-mini judge (`original.yaml`, picked 2026-10-28) is on OpenRouter only as
  `openai/o3-mini:batch`, whose live-call latency is unknown.
- **Named deviations:** default.yaml's backup judge (`grader_2`, gemini-3.7-flash, a separate
  column) is not run, since a row pins one judge; default.yaml's fp8 provider pin is not sent,
  since our gateway sends no OpenRouter provider routing.
- **Headline:** `--whole-run-metric mean`: the mean of the judge's C/I, a Case the judge cannot
  grade counting 0 (`withhold`), which is the CAIS accounting (`original_accuracy`); the
  Candidate's stated confidence is the second named score.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the two importer-written rows (`prepare.py`, `benchmarks.py`) with the prose,
  tier `hard`, policy `withhold`, named scores, baselines and judge filled by hand; the five
  per-Benchmark test tables; `tests/unit/inspect/test_hle_cases.py`; the judge seeded in the
  gateway (`openrouter_provider/settings.py` and its seed-pin test) and the Engine
  (`world/models/seeds/openrouter.py`, `test_model_seeds.py`: 116 → 117 ids, 87 → 88 routable,
  plus a new test that the HLE judge stays routable); `.claude/test-change-approvals/OME-1478.json`;
  the OME-1478 mirror. The importer and judge fixes are PR 1 of 2 (#1631).
- **Import (2026-11-02, real Hub data at `cais/hle` `5a81a4c7`):** 2,500 Cases, Case Digest
  `7fb3221865f1…`, published revision `d30effc2a0698079`, licence mit. Pictures arrive as
  `data:` URIs and are not re-encoded, so the seal does not depend on the platform's Pillow (the
  image build's replay in CI is the outside check).
- **Baselines (read from the sources):** no human baseline (arXiv 2501.14249v12 reports none);
  frontier 0.484, Gemini 3.1 Deep Think, no tools, full set (Google DeepMind's own page, 2026-02).
- **Fidelity:** `test_hle_cases.py` replays the real task over a text row and a picture row;
  the picture's bytes match, and our judge's whole prompt equals the one inspect's own `eval()`
  sends its judge for the same row and reply.
- **Commits:** see the PR.
- **Gates:** the five tables, the judged-row assembly and imports suites, the model-seed suites
  (Engine and gateway) and `test_hle_cases.py` pass; ruff, ruff format and pyright clean on the
  touched files. Full suites: pre-push hook and CI.
- **Deviations:** the judge change above.
- **Owner-verify:** a paid 2-Case HLE run on dev (one text Case, one picture Case) through the
  notebook, reading the judge's reply and the run's peak memory against the 2,560 MiB budget.
