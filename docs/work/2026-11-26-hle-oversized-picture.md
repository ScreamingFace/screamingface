---
ticket: OME-1970   # PR 1 of 9
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-26
finished: 2026-11-26
---

# hle-oversized-picture — shrink HLE's one 14950 px picture so every host accepts it

## Intent

`hle` (2,500 Cases) and `hle_diamond` (1,000 Cases) each hold one picture no Claude or GPT-pro
model accepts: Hub row `66f1b940f8bb4425f74e4299` (`hle` Case 250, `hle_diamond` Case 35), a
14950×2780 px RGBA PNG (991,800 base64 bytes). The 6 Nov prod HLE runs failed it on every Claude
Candidate (400 "The upstream provider rejected the request.", Claude documents 8000 px per side)
and on gpt-6-astra-pro / gpt-6.1-terra-pro ("requires 40716 patches after processing, exceeding
the limit of 30000"). This unit shrinks that one picture at Case Preparation to a long side of
8000 px (aspect kept → 8000×1488), as a Named Deviation declared on both rows, so the OME-1970
seal-time picture-side check (a later PR) never refuses HLE. No other Case changes.

## Planned changes

- `src/screamingface_engine_inspect/prepare.py` — `TaskReplayCasesSpec.shrunk_picture_sample_ids`
  (sibling of `excluded_sample_ids`), the `HLE_OVERSIZED_PICTURE_SAMPLE_IDS` constant, both rows
  declare it with a NAMED DEVIATION comment; new `case_digest` / `case_set_digest` (sealed on
  linux/amd64).
- `src/screamingface_engine_inspect/shrunk_pictures.py` (new) — `MAX_PICTURE_SIDE_PX`,
  `shrunk_size`, `with_shrunk_pictures`: Pillow LANCZOS to long side 8000, PNG re-encode; refuses a
  listed id that is missing or whose pictures are all within the limit.
- `src/screamingface_engine_inspect/capture.py` — apply it after the exclusions, before capture.
- `src/screamingface_engine_inspect/benchmarks.py` — `_task_replay_pins` adds the ids as an
  identity pin when set (as `excluded_sample_ids`).
- Tests: new `tests/unit/inspect/test_shrunk_pictures.py`; `replayed_cases_helpers.py` strips the
  deviation for stand-in rows unless asked; `test_benchmark_fingerprints.py` literals.
- Docs: Fidelity Records `inspect-hle.md` (new D7) and `hle_diamond.md` (new D9), CHANGELOG.
- `.claude/test-change-approvals/OME-1970.json` for the edited prior test files.

## Test plan

- RED first: `shrunk_size(14950, 2780) == (8000, 1488)`; a listed Sample's 9000×90 PNG RGBA →
  8000×80 PNG RGBA, other Samples untouched (same object); deterministic bytes; a listed Sample
  whose picture is within 8000 px → PrepareError; a listed id not in the dataset → PrepareError;
  a non-PNG over-limit picture → PrepareError.
- Through the real `hle` Task (stand-in Hub rows, one carrying the real row id): the Case's
  picture is 8000 px wide; the declared Sample id is `create_stable_id(row id, prefix="hle")`.
- Fingerprint + published revision tests for the two rows.

## Acceptance

- Both rows reseal on linux/amd64 with only the one Case changed (old vs new compared by Case id).
- Published revisions held by named exception (owner, 2026-11-27).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `CHANGELOG.md` and `.claude/test-change-approvals/OME-1970.json`.
  The pending-decision note sits on both rows' `published_revision` in `benchmarks.py` and on the
  fingerprint literals. Not touched: the importer (it never writes the new field; a hand-declared
  deviation, as `ENIGMAEVAL_HELD_OUT_OVER_CASE_CAP`), the hle_diamond README.
- **Commits:** `fix(screamingface-engine): shrink HLE's one 14950 px picture to 8000 px (OME-1970)`.
- **Seal (linux/amd64, image built from this branch's Dockerfile + `uv sync --frozen --no-dev
  --extra benchmarks`, Pillow 13.0.0, source mounted):** main's code reproduced the pinned
  digests (hle `7fb32218…`, hle_diamond `ba7f9bc0…`), and so did this branch with the deviation
  turned off. With it on: hle `127e1592…` / set `8c7dd171…`, hle_diamond `822e5531…` / set
  `d8c4c7ba…`. Old vs new compared by Case id: hle changed `[250]`, hle_diamond changed `[35]`;
  in each only the picture differs (14950×2780 → 8000×1488 RGBA PNG, 991,800 → 671,068 base64
  bytes), texts and Grading Material identical. Each replay took about 25 s.
- **Fingerprints:** hle `6bf010527abe2411` → `0c3d712629ad9515`, hle_diamond
  `7261715107987e29` → `02f3cbc9fce746be`.
- **Gates:** relevant tests only: 28 files (the 26 that import capture, the shrink module, the
  replay helper or the identity pins, plus the fingerprint and published-revision tests) → 1391
  passed with the `benchmarks` extra; `test_shrunk_pictures.py` 12 passed. Ruff check + format and
  pyright on the 7 touched Python files clean, pyright also clean extra-less. Not run:
  `run_gates.py` (full gate, CI's job).
- **Deviations:**
  - **Published revisions HELD (owner, 2026-11-27).** The revision rule says a changed Case
    set moves the id; the owner held both (`d30effc2a0698079`, `9640c5c7e59fc61e`) as a second
    named exception after OME-1939, because Claude and GPT-pro Candidates already failed that
    one Case unread. Recorded in `docs/adding-an-imported-benchmark.md`.
  - The fix is keyed by inspect_evals' Sample id (`hle_350ce3fb`), the handle capture sees, not
    the Hub row id directly; a test pins `create_stable_id("66f1b940f8bb4425f74e4299",
    prefix="hle") == "hle_350ce3fb"`.
  - `replay_in_process_over_rows` gained an opt-in `shrink_named_pictures` flag: the deviation
    refuses a dataset without its row, and the existing hle stand-in replays do not carry it.
  - Both Fidelity Records already read `stale` before this unit (OME-1939 moved the
    fingerprints); this unit adds D7 / D9 without re-auditing.
