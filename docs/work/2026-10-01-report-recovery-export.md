---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress
started: 2026-10-01
finished:
---

# report-recovery-export — Stream `Report.export()` with the same bytes (OME-1448 option D, PR A)

## Intent

`Report.export()` builds the whole JSON document as one string before it writes a byte, which is
a second full copy of the Report in memory (OME-1448 failure F2). This unit writes the document
one Candidate at a time, through an atomic temporary file, with bytes identical to today. The
same writer serves recover-to-file in PR D. Plan:
`docs/plan/2026-10-01-OME-1448-report-recovery.md` §PR A. Spec:
`docs/spec/2026-10-01-OME-1448-report-recovery/prd/report-json-writer.md` and
`prd/export-report.md`. This PR also carries the OME-1448 spec and plan docs.

## Planned changes

- New `packages/screamingface/src/screamingface/_atomic_file.py`: `write_atomic(target, write, *, private=False) -> Path`.
- New `packages/screamingface/src/screamingface/_report_writer.py`: `write_report_json(write: Callable[[str], object], *, benchmark, case_count, started_at, completed_at, candidate_names, candidates)`. It emits `str` fragments, not bytes: `to_json()` returns a `str` even for text with lone surrogates, and PR D has no `Report` to call.
  (Deviation from the plan's A2 placement: `report.py` is already more than 820 lines, so the writer gets its own module.)
- `packages/screamingface/src/screamingface/report.py`: extract `_require_report_candidate` from `Report.__init__`; `to_json` and the JSON branch of `export` use the writer.
- `packages/screamingface/src/screamingface/_named_values.py`: `_require_unique_names`, shared by `_NamedValues` and the writer.
- New tests: `tests/test_atomic_file.py`, `tests/test_report_writer.py`, `tests/test_report_streaming_export.py`, helper `tests/_report_fixtures.py`.
- `packages/screamingface/CHANGELOG.md`.
- Docs: `docs/spec/2026-10-01-OME-1448-report-recovery/`, `docs/plan/2026-10-01-OME-1448-report-recovery.md`, `docs/work/2026-10-01-report-recovery.md`, `docs/tasks/OME-1448-report-recovery.md`.

## Test plan

Spec rows RW-0 … RW-6 and EX-0 … EX-7. RED first: EX-1 (a crash mid-export keeps the previous
file), then RW-1 (hypothesis: the writer's bytes equal `json.dumps(report.to_dict(), …)`).

## Acceptance

- Every existing report and export test is unchanged and green.
- The new tests are green. The `run_gates.py screamingface` gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** new `packages/screamingface/src/screamingface/_atomic_file.py`, `_report_writer.py`;
  changed `report.py` (`_require_report_candidate`, `_require_report_candidate_names`, `to_json` and the JSON
  branch of `export` use the writer), `_named_values.py` (`_require_unique_names`), `CHANGELOG.md`;
  new tests `tests/test_atomic_file.py`, `tests/test_report_writer.py`, `tests/test_report_streaming_export.py`,
  helper `tests/_report_fixtures.py`.
- **Commits:**
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface` -> ALL GATES GREEN (append-only, ruff check,
  ruff format --check, pyright, pytest coverage >= 95%, notebooks, build, distribution). The fresh worktree
  needed `uv sync --extra notebook` first, as CI does.
- **Deviations:**
  - The writer module is separate from `report.py` (see Planned changes), and its `write` argument takes `str`
    fragments (see Planned changes).
  - `_named_values.py` is also touched: the duplicate-name rule moved to `_require_unique_names` so the writer
    and `_NamedValues` share one rule. `report.py` gained `_require_report_benchmark`,
    `_require_report_candidate_names` and `_require_report_candidate` for the same reason.
  - The memory threshold is 2.0 x the one-Candidate reference, not the spec's 1.5 x. Measured 1.68 x: one
    fragment, its UTF-8 bytes and the 1 MiB buffer. The old code measures about 6.9 x.
  - No `hypothesis` in the dev dependencies, so RW-1 uses a seeded, parametrized table (24 reports).
  - EX-1 passes on the old code too (the old `export` built the whole string before it opened the file). The
    real RED for atomic replace comes from the lone-surrogate test (the old `write_text` truncated the target
    first) and the disk-full test (`os.fsync` raises ENOSPC).
  - The memory tests cannot see a list of all Candidate dicts (the dicts share the case strings), so a second
    guard counts the live `CandidateResult.to_dict` results at each call.
  - New tests beyond the spec rows: error-masking cleanup, permission-bits-only copy, non-Candidate item,
    lone-surrogate export. Existing-test duplicates (parent directories, inspect delegation) are not repeated.

- **Flake seen (not caused by this unit):** the first full gate run after the review fixes failed
  `tests/test_evaluation_outcome.py::test_a_callback_exception_aborts_the_evaluation_and_is_re_raised`
  (run took 224 s, about 2x normal). It passed 5/5 alone and 8/8 as a file under `-n 8`, and the next
  full gate run was ALL GREEN. The test drives real threads and sockets with a 10 s join, and it calls
  none of the code this unit changes. It is recorded here as a possible load-sensitive race in the
  run-isolation tests (`docs/work/2026-09-28-sdk-run-isolation-evaluation-outcome.md`), to watch in CI.
