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

**PRs B1 + B2 — the pin generator (importer tool)** (owner decisions 2026-09-16:
edit files in place so `git diff` is the review artifact; auto-introspect from the
task name with dev review as the gate; license check warns but emits; split in two
stacked PRs by the ≤500-line rule — B1 = stages 1–2 reading facts, B2 = stage 3 +
CLI writing rows):
- `src/screamingface_engine_inspect/importer.py` — build-side command
  (`python -m screamingface_engine_inspect.importer <task_ref> --key <k>`):
  1. *introspect* — import the eval's task module, patch its `hf_dataset` binding
     with a recorder returning a stub dataset, call the task function, then read
     the recorded kwargs (dataset path/config/split, `record_to_sample`, pinned
     revision if the eval pins one) and the Task's solver/scorer registry metadata
     (family: templated | mcq | raw; scorer ref + kwargs; template attr resolved
     by identity scan of the module).
  2. *capture* — observations the eval's code can't provide: HF revision sha (when
     not pinned upstream), row count at that sha, dataset license (warn-only
     gate; the license lands as a comment in the generated rows).
  3. *emit* — insert the three row fragments in place at anchor comments: pin
     constants (pins.py), the `SnapshotSpec` entry (prepare.py), the `BoardSpec`
     entry (boards.py, title/description/focus as TODO placeholders for the dev).
- Anchor comments added to pins.py / prepare.py / boards.py (the insertion contract).
- `tests/unit/test_inspect_importer.py` — fabricated eval module (no network):
  introspection facts, renderer goldens (emitted code parses), in-place insertion
  round-trip on file copies, license-warn path, duplicate-key refusal; capture
  layer injected/faked.

**PR D — the onboarding runbook (docs only):**
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md` — the AI-first
  import walkthrough (agent runs/writes, human verifies the diff) + refusal table +
  new `importer-pipeline` diagram (.drawio + PNG, sf-dark).
- Rename `adding-a-benchmark.md` → `adding-a-benchmark-manually.md`; cross-link the
  pair; update the two path references (README, `benchmarks/__init__.py`).

**PR C+ — the ten boards, in reviewable batches** (onboarding is AI-first — owner
direction 2026-09-16: the agent runs the importer, writes the TODO catalogue prose
from the eval's own docs, and resolves every TODO(review) flag; the human's role is
reviewing/verifying the generated diff, plus the paid acceptance runs):
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
