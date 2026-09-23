---
ticket: OME-1253
stack: screamingface-engine
status: done
started: 2026-09-22
finished: 2026-09-22
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

- **Actual files:** batch 1 (PR #1016): generated rows in pins/prepare/boards +
  2 appended bake tests + 3 roster extensions + ledger + mirror. No batch-2 PR:
  all three candidates failed the per-board fidelity check (see Deviations).
- **Commits:** `7bf89ee` feat(screamingface-engine): import the musr and wmdp
  boards (PR #1016, CI green); `a4c5a92` feat(screamingface-engine): import
  hellaswag, delivering its system instruction as leading input text
  (PR #1018, stacked on #1016). Both await owner merge.
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN on both committed
  branches (append-only included). PR #1016: pytest 3537 passed. PR #1018
  after the review round: pytest 3550 passed, 0 failed, 9 skipped (209 in
  the inspect lane). Offline full-bakes 250/250, 1273/1273, 408/408,
  1987/1987, hellaswag 10042/10042 re-baked with the policy shuffle seed
  (seeded prefixes mix both domains at the base rate).
- **Deviations:**
  - Batch plan reshuffled: 10 of the sweep's in-scope 22 were already on main,
    so the train shrank to 7 choice + 4 custom-deterministic candidates.
  - hellaswag licence owner-approved (MIT per upstream source repo) and
    imported in PR #1018 — with an owner-approved importer/prepare seam:
    a module-level system message binds as a fact and bakes as leading
    input text (contracteval named-deviation pattern). "No importer
    changes" premise amended by the owner for this seam only.
  - sec_qa_v1/v2 licence-REFUSED by owner: cc-by-nc-sa-4.0 non-commercial
    is incompatible with the public catalogue.
  - ds1000 / class_eval / compute_eval fidelity-refused: docker-sandbox
    code-execution scorers (ds1000 also injects a model-specific system
    message). Not row-importable; sent back on the ticket.
  - frontierscience reclassified judge-scored (model_graded_fact) — the
    sweep's custom-deterministic call was wrong; parked with the judge lane.
  - bbh / lingoly / mbpp re-probed ONLINE: upstream TypeError / gated dataset /
    prompt-template refusal. All three refused with verbatim reasons on the
    ticket's scope-correction comment.
  - Unlock pipes deferred by owner sizing call (~100 LoC each): filed as
    OME-1264 (lab_bench + truthfulqa + infinite_bench families).
  - Review round on PR #1018 (2 blockers fixed): hellaswag gets an OURS
    policy shuffle seed (the pinned validation split is domain-grouped —
    3,243 ActivityNet then 6,799 WikiHow) + an upstream-pin drift test;
    system_message pointer now rides revision identity; non-string
    system_message resolutions refuse the bake; template-conservation gap
    (params/placeholders) filed as a follow-up ticket.
