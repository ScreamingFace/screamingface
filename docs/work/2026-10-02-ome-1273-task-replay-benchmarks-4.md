---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1273-task-replay-benchmarks-4 — import bbeh, pre_flight and chembench by Task replay; draft the four upstream issues

## Intent

Plan step 7, batch 2, stacked on #1222 (batch 1): the last three packages of the ticket's 14
(bbeh, pre_flight, chembench) as Task-replay Benchmarks on the capture path (#1219, #1191),
each with its sealed declaration, catalogue row, the owner's licence decision (2026-10-01:
bbeh apache-2.0, pre_flight mit, chembench mit) and a no-network grading test (spec R17).
Plus the four upstream issue drafts the ticket owes (bbh, personality, sciknoweval,
novelty_bench), each re-checked against the installed inspect_evals 0.20.0 before drafting.
Every refusal is read and named in the importer's own words, never patched around.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `benchmarks.py` —
  the generated rows, prose, tiers and licences. chembench passes `shuffle=False` (its
  `hf_dataset(shuffle=True)` default is unseeded, so two replays would disagree).
- `tests/unit/inspect/test_inspect_task_replay_benchmarks.py` — the keys join the
  sealed/licensed test; a grading test per Benchmark under `no_network`.
- `tests/unit/inspect/test_inspect_imported_benchmarks.py`, `test_benchmark_declaration.py` —
  the keys join the family and policy tables (prior-test edits; `--skip-append-only`
  locally, as the owner granted on #1194/#1198/#1220/#1221/#1222).
- `docs/work/2026-10-02-ome-1273-upstream-issue-drafts.md` — the four drafts, owner posts.
- `docs/tasks/2026-09-23-OME-1273-task-replay-import.md` — progress bullet; stays open.

## Test plan

- Each Benchmark: sealed, licensed, registered.
- bbeh: the eval's own rule-based scorer grades "The answer is: (a)" right against "(a)" and
  wrong against "(b)", under `no_network`; free-text, so it has a Draft Feedback route.
- pre_flight: inspect's choice scorer, "ANSWER: B" grades 1.0 against B, 0.0 against A.
- chembench: its own two-way scorer: an MCQ Case graded by the [ANSWER] tag regex, a numeric
  Case graded by relative tolerance from the Case's kept metadata.

## Acceptance

- Every importable key in `TASK_REPLAY_CASES` with two agreeing replays; R7's licence gate
  green; gates green. Every refused task named with the importer's own words. Four upstream
  drafts (or "no longer reproduces") in the drafts file.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `--task-arg shuffle=False` on chembench never reached a
  row (its import was refused before any row was written).
- **Imported** (Cases · Case Digest prefix · Case Source · license, owner 2026-10-01; both
  licences agree with the Hugging Face card the importer read):

  | Benchmark | Cases | Digest | Case Source | License |
  | -- | -- | -- | -- | -- |
  | pre_flight | 300 | eda28835a8b5 | AirsideLabs/pre-flight-06 at 439d2d11 | mit |
  | bbeh | 4,519 | 94e806ce3814 | BBEH/bbeh at 08e07a80 | apache-2.0 |

  bbeh is 4,519, not the 4,520 the eval's own listing says: upstream's `filter_duplicate_ids`
  drops one duplicated record before the Task is built. `keep_sample_metadata=True` on bbeh
  (the importer's rule for an eval-owned scorer); each Case keeps its `task` and `mini`
  fields, so the paper's per-task regrouping is possible from a full run.
- **Refused, in the importer's own words** (nothing patched to let it through):
  - chembench (`--task-arg shuffle=False`): `PrepareError: case 27: target 'A,B,E,G,J,L,M' is
    neither a letter within 16 choices nor one of them` — its multiple-choice Samples can
    name several right options at once (the eval joins the right letters with commas, and
    its template asks for "the letter(s)"), and the Case boundary takes one text key naming
    one option; batch 1 named the same shape on cyberseceval_4 malware_analysis (there a
    list of letters). Its scorer itself maps cleanly (CORRECT/INCORRECT), so OME-1268 is not
    the reason. The change it would need: a declared several-right-options key shape at the
    Case boundary (`_validated_answer_key`) and the adapter marking every listed letter —
    mechanism this ticket does not carry. Not a scorer-lookup problem (bbeh's scorer sits in
    its task file; spec R8 was dropped for that reason), so no resolver change was made.
- **Upstream drafts:** `docs/work/2026-10-02-ome-1273-upstream-issue-drafts.md`: novelty_bench
  drafted (reproduces: torch imported at Task build, no extra declares it); bbh and
  sciknoweval do not reproduce (the sweep's crashes were the Hugging Face reader's stand-in
  Sample); personality_TRAIT cannot be checked (gated dataset). The owner posts the one draft.
  bbh now builds under a real fetch (6,509 Samples), so its "upstream issue" destination in
  the ticket's table is stale; re-importing it is a separate unit, not done here.
- **Commits:** one `feat(screamingface-engine)` commit: the two rows, prose and licences,
  the tests, the drafts file, ledger and mirror note.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` → ALL GATES GREEN (ruff,
  format, pyright, layering, pytest with coverage ≥ 80); the skip
  covers the two contract-table edits only (`_EXPECTED_FAMILIES`, the policy table), as the
  owner granted on #1194/#1198/#1220/#1221/#1222.
  `test_benchmark_row_scorer_resolves_and_constructs[frontierscience]` fails standalone and
  passes in the full gate (pre-existing).
- **Deviations:** the batch was planned as three Benchmarks; two landed, chembench refused.
  bbeh keeps the importer's `with_check_surface=True` (free text, no `choices` on any
  Sample), though 1,120 of its answer keys are a bracketed letter over options listed in the
  question and 174 are yes/no, where pass/fail Draft Feedback narrows the options; boolq
  (yes/no, Draft Feedback on) is the standing precedent, and the limitation is named in the
  PR for the owner's call. The three "does not reproduce" verdicts replace three of the four
  drafts the plan promised.
- **Owner-verify:** post the novelty_bench draft upstream (or not); decide bbeh's Draft
  Feedback; decide whether bbh gets a re-import unit now that it builds.
