---
ticket: OME-2018
stack: screamingface-engine
status: done
started: 2026-11-25
finished: 2026-11-25
---

# medxpert-commit-letter-only — tell the model MedXpertQA's turn 2 wants the option letter only

## Intent

MedXpertQA's turn 2 (the commit) sends the trigger "Therefore, among A through J, the answer
is" and relies on the model finishing that sentence with a letter. `OME-1980` made turn 2 a real
chat continuation, but the first paid smoke on the new revision `952ea002b0f5e3b0` showed the
model still writes an essay: on both Cases the synthesizer replied with 277 and 496 tokens of
new reasoning, and on Case 1 it changed its turn-1 answer `(E)` (the key) to `(G)`. Turn 2
states no reply format, so the model treats the trigger as a new question.

Fix (owner decisions, 2026-11-25): turn 2 states the rule, as a declared deviation from the
official harness: one instruction line before the trigger. The answer reader is made robust to
the one wrapper it misses (`__E__`), with the whole wrapper table the multiple-choice grader of
`OME-1907` reads pinned for MedXpertQA. The published revision moves once more; neither
`490235dc9a53b7d9` nor `952ea002b0f5e3b0` reached a release or holds an entry, so production
goes from `1e5a3b8a461a52f7` straight to the new id.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/prompts.py` — the
  instruction text.
- `.../medxpert/commit.py` — the chat's last user message is the instruction, a blank line,
  the trigger.
- `.../medxpert/answering.py` — a letter wrapped in underscores is read.
- `.../medxpert/revision_inputs.py`, `.../medxpert/definition.py` — protocol v4, new revision
  id, the Named Deviations and the Benchmark description.
- Tests: new cases in `test_medxpert_commit_recipe.py` and `test_medxpert_answering.py`; the
  revision pins and the tests that pin turn 2's last message move to the new bytes.
- `apps/screamingface-engine/CHANGELOG.md`.

## Test plan

- The commit chat's last message is exactly the instruction, a blank line and the trigger, and
  it ends on the unfinished sentence.
- Every wrapper the multiple-choice grader reads (`(E)`, `[E]`, `**E**`, `__E__`, `` `E` ``,
  `$E`, `$E$`, `$$E$$`, `\boxed{E}`, `$\boxed{E}$`) reads as E on MedXpertQA.
- A lower-case letter and a letter inside a word are still not read.
- The protocol constant moved: v3 computes `952ea002b0f5e3b0`, the current one computes the
  new id.

## Acceptance

- A model given turn 2 is told to reply with the option letter only.
- No reply the reader read before is read differently, except `__X__`, which now reads X.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the pins the bump tool names
  (`tests/unit/inspect/test_benchmark_fingerprints.py`, `tests/unit/inspect/test_benchmark_bump.py`,
  `tests/unit/test_medxpert_migration_golden.py`, `tests/fixtures/early_grade_compatibility.json`),
  the canonical url4 hash in `tests/unit/test_benchmark_protocol.py`, and
  `.claude/test-change-approvals/OME-2018.json`.
- **Commits:** one commit on `OME-2018-medxpert-commit-letter-only`.
- **Gates:** relevant tests only, per owner rule: the 13 `test_medxpert_*.py` files,
  `test_benchmark_protocol.py`, the two early-grade files, `test_combine_reducer_candidates.py`,
  `test_frozen_copy_failed_case.py`, `test_benchmark_stage_installation.py` and
  `integration/test_local_model_fusion_benchmark.py` → 211 passed;
  `inspect/test_benchmark_fingerprints.py` and `inspect/test_benchmark_bump.py` (inspect extra)
  → 107 passed; ruff check + format and pyright clean. Full suite left to the pre-push hook
  and CI.
- **Deviations:** (1) The multiple-choice grader of `OME-1907` could not be reused as code: it
  lives in the inspect plugin, reads inspect's `ANSWER:` label, and core Benchmarks may not
  import a plugin. MedXpertQA's own reader already read every wrapper in that grader's table
  except a letter in underscores, so only that case changed, and the table is pinned in tests.
  (2) The instruction's placement and wording were chosen from a free local check, 6 real Cases
  on `qwen3.8:27b`: the bare trigger gave the letter first on 2 of 6 replies (mean 1,092
  characters); the instruction before the trigger 6 of 6 (mean 10); the instruction after it
  6 of 6 (mean 5). It goes before, so the message still ends on the unfinished sentence.
  Review round 1 (2026-11-25), two changes: (a) the first letter rule ("no ASCII letter or
  digit touches it") also freed a letter touching a Greek letter, a subscript or a superscript,
  so `vitamin B₁₂ ... so D` committed B; the rule is now the harness's word boundary with only
  the underscore removed, and the reviewer's rows are tests. (b) The instruction's text became
  a hashed input of the revision, so rewording it moves the id by itself; the id moved from
  the first build's `97c31c77b39ed19f` to `5f6e01e4fa673215` before anything merged.
  (3) Prior tests were edited (the chat's last message and the revision pins), by the owner's
  decision; the approvals file pins each file's before and after. (4) Not run: any paid call.
  Owner-verify: about 20 Cases with one solo model and one Fusion on the dev Engine, counting
  replies that start with the letter and answers that change between turn 1 and turn 2, before
  the leaderboard reruns (`OME-1981`). The Fidelity Record is still the one audited at
  `1e5a3b8a461a52f7` and needs a re-audit.
