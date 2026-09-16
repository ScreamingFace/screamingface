---
ticket: OME-1116
stack: screamingface-engine
status: in_progress
started: 2026-09-16
finished:
---

# OME-1116 — Import ten single-shot inspect_evals benchmarks into the catalogue

## Intent

Turn benchmark import into a data operation: a board becomes one `SnapshotSpec` row +
one `BoardSpec` row (no per-board Python module — owner decision 2026-09-16, which
closed OME-1115's #955/#956 unmerged), then push gsm8k + mmlu (the OME-1115 proof
boards, re-landed as rows) and ten new single-shot boards through the row machine.
Also absorbs OME-1115's docs close (spec §7 amendment, ledger/mirror), which rode the
closed #956.

## Planned changes (stacked PRs, planned up front per the ≤500-line rule)

**PR A1 — the row machine:** `boards.py` (BoardSpec + empty BOARDS + generic
assembler/installer), the owner-approved conformance amendment
(`test_benchmark_deployment.py`: installer-function `ASSET_BUNDLE_ID` first),
`test_inspect_single_shot.py` (factory suite, probe boards), this ledger + mirror.

**PR A2 — gsm8k row:** the check-surface handler (`single_shot.py`, from closed
#955), the gsm8k `BoardSpec` row, `test_inspect_gsm8k_board.py`, the declaration
roster amendment.

**PR A3 — mmlu row + OME-1115 docs close:** the mmlu row, `test_inspect_mmlu_board.py`,
spec §7 two-board amendment, OME-1115 ledger Outcome + mirror close.

**(superseded plan below, kept for context)**

**PR A — the row machine + the two proof boards (rows):**
- `apps/screamingface-engine/src/screamingface_engine_inspect/boards.py` — `BoardSpec`
  dataclass (title/description/focus/dataset_url · scorer as dotted `"module:attr"`
  reference + kwargs · `with_check_surface` · `multiple_correct`) + `BOARDS` table
  (gsm8k, mmlu rows) + generic installer factory stamping `ASSET_BUNDLE_ID` on the
  installer FUNCTION + `imported_board(key)` accessor + looping `board_registrations()`.
  Revision pins derive from the board's `SnapshotSpec` (dataset/config/split/revision
  + shuffle seed) — no pin duplication.
- `tests/unit/test_benchmark_deployment.py` — OWNER-APPROVED prior-test amendment:
  `_installer_bundle_id` reads the installer-function attribute first, module constant
  fallback (home-grown families unchanged).
- Board tests and metadata cherry-picked from donor branches `OME-1115-5-gsm8k` /
  `OME-1115-6-mmlu` (check-surface sealed feedback, refuse-early, factory identity,
  MCQ surface refusal), rewired to `imported_board("gsm8k"|"mmlu")`.
- `docs/spec/2026-09-09-OME-1113-inspect-evals-import.md` §7 two-board amendment +
  OME-1115 ledger Outcome + `docs/tasks` mirror close (from the donor branches).

**PR B — the pin generator (importer tool):**
- A build-side command: given an inspect_evals task reference → resolve the HF
  dataset's current sha, download + count rows, run the license check, and emit the
  `SnapshotSpec` + `BoardSpec` rows as a generated diff for human review (import time
  is the only trust window — see OME-1116 comments).

**PR C+ — the ten boards, in reviewable batches:**
- Ten generated row pairs (single-shot, license-cleared, `match`/`includes`/`choice`
  scorer families first), each with its per-board definition test; free-text boards
  opt into the check surface, MCQ boards refuse it (OME-796).

## Test plan

- RED first per PR: row-machine identity/registration tests (ported + new), the
  amended conformance test proving the function-attribute path AND the fallback,
  generator golden test (emit rows for a known task, byte-stable), per-board
  definition tests for each batch.

## Acceptance

- ≥10 imported boards evaluate end to end, each board ≤150 lines including its rows
  and tests (bar from the ticket), zero spine edits, `origin="inspect_evals"` +
  license note each, extra-less installs byte-identical, plugin never named in core.
- Solo / fusion structurally covered by the row machine's tests; corrective_loop on
  free-text boards via the check surface; paid `limit=50` acceptance runs remain the
  owner's.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
