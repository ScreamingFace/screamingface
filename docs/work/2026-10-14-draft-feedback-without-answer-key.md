---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-14
---

# draft-feedback-without-answer-key — offer an owner-allowed Benchmark's Draft Feedback without an answer key

## Intent

OME-1527 Work order #13 (R10). IFEval moves to a local inspect Task in row 15: no answer key,
no judge, its own scorer grading the reply against the instructions in each Sample's metadata,
and a Draft Feedback offer, because the Corrective Loop's paper worked on IFEval. Assembly
refuses that row today: a reply-only row may not offer a mid-run check (owner decision
2026-10-05, so a fusion can't re-word a refusal-regex draft until it slips past). This unit
keeps that refusal for every reply-only row except one whose catalogue id the owner named, and
moves the owner's allow-list from a test into the assembler.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`:
  `OWNER_ALLOWED_DRAFT_FEEDBACK = frozenset({"ifeval"})` (catalogue ids); the check-surface
  branch of `_check_reply_only_claim` refuses unless the row's catalogue id is on it.
- `apps/screamingface-engine/tests/unit/inspect/test_judged_benchmark_assembly.py`: appended
  R10 section.
- `apps/screamingface-engine/tests/unit/test_draft_feedback_offer_is_owner_opt_in.py`: the
  row-level test compares by catalogue id against the owner list and pins the code's copy to
  the test's literal (approval in `.claude/test-change-approvals/OME-1527.json`).

## Test plan

- An IFEval-shaped row (key-less, judge-less, own scorer, local Task "ifeval") with a check
  surface assembles and carries the offer.
- The same row under another catalogue id ("ifeval_twin") is refused, naming the list.
- An inspect_evals row keyed "ifeval" (catalogue id "inspect-ifeval") is refused.
- The empty-key refusal of a check surface still fires for the allowed id.
- The row-level owner test: rows asking for the offer ⊆ owner list by catalogue id, and the
  assembler's constant equals the test's literal.

## Acceptance

- No row changes, no revision moves; every assembled Benchmark is unchanged.
- A reply-only row not on the owner list is refused the offer exactly as before.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the approval manifest rewritten for this branch.
- **Commits:** see the PR.
- **Gates:** relevant files only, with the inspect extra:
  `test_draft_feedback_offer_is_owner_opt_in.py`, `test_judged_benchmark_assembly.py`,
  `test_scorer_draft_feedback.py`, `test_task_replay_rows.py`,
  `test_inspect_task_replay_benchmarks.py`: 226 passed. Extra-less: the owner test passes, the
  assembly file skips. Mutations, each edited back in place: allowing every reply-only row
  turned two tests red; matching the row key instead of the catalogue id turned the
  inspect-ifeval test red; widening only the code's list turned the owner test and the
  allowed-row test red. ruff + format clean; extra-less pyright 0 errors on the touched files.
  Append-only check by hand (OME-1575): passes, the owner test's edit approved by the manifest.
- **Other refusals found:** none for this combination. `single_shot_benchmark` refuses a check
  surface only on a judged row, on a row serving the input envelope, and refuses
  `scorer_draft_feedback` without the offer; `prepare.py` has no check-surface rule. The
  plugin's check route reads each Case's `targets/<id>.json`, which a key-less row still writes
  (with an empty target), so it does not refuse either; row 15 proves that end to end.
- **Deviations:** the refusal message now opens with the catalogue id (the id the owner would
  add) instead of the row key. The R10 tests are appended to the existing reply-only assembly
  file rather than a new file, to reuse its row builders.
- **Owner verify:** confirm `OWNER_ALLOWED_DRAFT_FEEDBACK` names exactly "ifeval" and that
  the test's literal stays the owner's own gate.
