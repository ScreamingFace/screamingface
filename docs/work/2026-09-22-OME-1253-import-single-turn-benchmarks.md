---
ticket: OME-1253
stack: screamingface-engine
status: in_progress
started: 2026-09-22
finished:
---

# OME-1253 — Import every remaining single-turn text benchmark from inspect_evals

## Intent

Finish the single-turn text lane of the imported catalogue. The ticket's empirical
sweep (2026-09-22, post-PR-#1009, 248 registry refs) is ground truth: 29 Stage-1
green, 22 in scope. 10 of the 22 are already on main (gsm8k, mmlu, arc ×2, boolq,
commonsense_qa, mmlu_pro, paws, race_h, aime24/25) — the remaining imports are
7 registry-`choice` boards (hellaswag, musr, sec_qa_v1/v2, wmdp_bio/chem/cyber)
and 4 custom-but-deterministic boards (ds1000, class_eval, compute_eval,
frontierscience, each with the runbook's per-board fidelity check). Everything
else is excluded on paper via a scope-correction comment on the ticket.

## Planned changes

Per board, the importer edits in place (generated rows only — importer, spine,
and CI are out of scope for this train):

- `apps/screamingface-engine/src/screamingface_engine_inspect/pins.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/boards.py`
- `apps/screamingface-engine/tests/unit/inspect/` — appended per-board assertions
  (plain `test_` functions; suites importing inspect stay in this dir)

Batch boundaries (one PR each, ~110 changed lines per board, cap ~500):

1. hellaswag + musr — general MCQ (this worktree)
2. wmdp_bio, wmdp_chem, wmdp_cyber — WMDP family
3. sec_qa_v1, sec_qa_v2 — SecQA family
4. ds1000, class_eval, compute_eval, frontierscience — custom-deterministic
   scorers + fidelity checks

Plus: scope-correction comment on OME-1253 (image-parked, judge-scored, two
unlock-pipe families, offline-unresolved trio, gsm8k fewshot=0 note, aime2026
flag to product) and full 248-ref reconciliation.

## Test plan

- Per board: appended definition assertions in the imported-boards and snapshots
  test modules (existing pattern), asserting key, revision identity, case count,
  check-surface flag — MCQ boards never get a check surface.
- Offline full-bake per board after HF capture.
- `run_gates.py screamingface-engine` green per PR.

## Acceptance

- Every in-scope sweep task either a catalogue row (offline bake verified,
  licence line in diff) or named in the scope-correction comment with a reason.
- All 248 sweep refs reconciled: imported / parked / refused-with-reason /
  pipe-pending.
- No importer/spine/CI edits; refusals reported verbatim, never worked around.
- Uncleared licences, --skip-append-only, unlock pipes, merges: owner asks only.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
