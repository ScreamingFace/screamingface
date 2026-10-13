---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# gdpval-text-local-task — serve GDPval-text as a local inspect Task, delete its folder

## Intent

OME-1527 Work order #10 (PR 10 of 20). GDPval-text lived in a sixteen-file hand-built folder
(`benchmarks/gdpval/`) that only the hand-built serving spine could serve. With the judge
redraw (R3, #1321), concurrent grading of judged Cases (R4, #1322) and the gateway-cache
opt-out for a redraw (#1350) in the plugin lane, and the thinner Report accepted (owner
decision 1, 2026-10-13: one Check per Case), it moves to a local Task under
`screamingface_engine_inspect/local_tasks/gdpval/`, fed to the same importer as inspect_evals,
keeping its id `gdpval-text`. The three things that must stay the paper's (here: the hand-built
Benchmark's): prompt bytes, grading rule, score.

## Planned changes

- `local_tasks/gdpval/{gdpval.py,README.md}` (new): the loader (`datasets.load_dataset` at the
  pinned revision, the frozen selection, references flattened to text, the filtered rubric in
  Sample metadata), the `gdpval_rubric` scorer (one judge call per criterion through
  `judge_until_parsed`, earned over winnable), the `@task`.
- `local_tasks/gdpval/{prompts,references,rubric_filter,subset,__init__}.py`: moved from the
  folder; `references.py` is `ingestion.py` plus the download half of the hand-built
  `prepare.py`; `FILTER_REVISION` and `subset_sha()` go (the revision no longer reads them).
- `benchmarks.py` / `prepare.py`: the two importer-generated rows, the judge and its params
  pinned on the row (`JudgeSpec`), provenance carried over, `origin="screamingface"`.
- Delete the rest of `benchmarks/gdpval/` (11 files) and 7 of its 10 test files; port the
  three that test moved code (rubric filter, reference extraction, subset).
- `builtins.py`: drop the registration. `gdpval_grading_failed` loses its only emitter but stays
  declared on both sides (the SDK refuses an undeclared code when it reads a Report).
- SDK: drop gdpval from the hand-built prepare list, the e2e replay tuple and the shared-bundle
  map; notebook 10's setup cell says it needs an inspect-capable Engine.
- Delete the e2e golden triple (`gdpval-text.golden.json`, snapshot, manifest) and its
  `.gitignore` exception (owner decision 2026-10-13).

## Test plan

- `tests/unit/inspect/test_local_task_gdpval.py` (new): conservation literals (five canned
  Cases graded as the hand-built grader graded them, headline −0.1875 = hand-built), the
  judge's wire (route, params, one user message, a pinned grader prompt), the Candidate prompt
  bytes from a synthetic row, the row.

## Acceptance

- Prompt bytes and filtered rubrics of all 102 Cases equal the hand-built bundle's.
- The Case scores, per-criterion verdicts, failed Case and headline equal the hand-built
  grader's on canned judge replies, pinned as literals.
- No `benchmarks/gdpval/` folder; nothing emits `gdpval_grading_failed`, and it stays declared.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus: `single_shot.py` (one failure message, see Deviations);
  the shared tests that named the folder (stage parity, early-score timing, early-grade
  compatibility and its fixture, fresh judge retry, native case index, provenance factories,
  the declaration and family tables, the revision literal, the activity helper);
  `docs/adding-a-benchmark-manually.md` (two stale gdpval examples); the SDK's paid
  case-provenance map and test, the e2e slice tool's bundle map; and
  `.claude/test-change-approvals/OME-1527.json` (rewritten for this branch); the e2e golden
  triple deleted with its `.gitignore` exception.
- **Import:** `importer …gdpval.gdpval:gdpval_text --key gdpval-text --no-answer-key
  --keep-sample-metadata` (HF_HUB_DISABLE_XET=1, `benchmarks` extra): 102 Cases, Case Digest
  `06dd52ec…`, Case Source `openai/gdpval` @ `11e7900c` (the hand-built pin). The 58 reference
  files (36 Cases) are fetched by URL on the dataset's moving branch, unpinned, as before; the
  row's comment says so. Every TODO resolved from the hand-built definition (title,
  description, focus, difficulty `hard`, paper/authors/citation/harness, licence NotPublished,
  baseline and Frontier Score NotPublished, notebook `10_gdpval`); the judge row added by hand.
- **Prompt bytes:** the hand-built bundle (prepared from upstream/main before the deletion) and
  the new bundle compared Case by Case: 0 of 102 inputs differ, 0 of 102 filtered rubrics differ
  (4,447 criteria). All 11 grader prompts the conservation Cases send equal the hand-built
  route's.
- **Conservation literals:** from the hand-built routes at `2b3d477fe`, driven route by route
  on the canned replies (judge requests → verdict, redrawn as `;retry=2` would → rubric and
  case evaluation → its rubric grade hook → the shared mean scorer): Case scores 0.25, 0.5,
  −2.5, 1.0 and one failed Case (judge never parsed); headline −0.1875.
- **Revision:** `cacfc3e6b83765f6` (hand-built) → `1d82f69ca3650609` (local Task),
  owner-accepted (no external users).
- **Report:** thinner, as decided: one Check per Case carrying each criterion's id, points,
  verdict and the judge's words plus the redraw count; no per-criterion Check, judge cost per
  Case; `pass_rate`, `verdict_coverage`, `score_sd` and `judge_invalid_replies` not served.
- **Commits:** see the PR.
- **Gates:** relevant files only (listed in the PR), with and without the inspect extra; ruff +
  format clean; extra-less pyright 0 errors on touched files; layering OK. Full gate = pre-push
  hook + CI. Append-only check run by hand (the hook passes silently in worktrees, bug
  `OME-1575`): it FAILS only on the 7 deleted `test_gdpval_*.py` files, which the manifest
  cannot approve; every edited test passes through `OME-1527.json`. The deletions are the
  owner's decision on OME-1527 (Work order #10: the folder and its tests go). The SDK's check
  FAILS only on the 3 deleted e2e golden files (golden, snapshot, manifest), deleted by the
  owner's decision of 2026-10-13; every edited SDK test passes through the manifest.
  Size: the owner waived the ~500-line cap for this PR (deletions are mechanical, ~125 test
  lines are canned data).
- **Deviations:** (1) the plugin aggregate had no failure message for `judge_reply_invalid`,
  so a Case whose judge never parsed crashed the whole aggregate with a KeyError (the redraw
  helper, #1321, had no consumer until now); one line in `single_shot.py`, pinned by the
  headline test. (2) The hand-built `prepare.py` tests (fetch atomicity, selection, rubric
  validation) were not ported; the loader keeps the same logic and the Case Digest seals its
  output. (3) The e2e golden triple (`gdpval-text.golden.json`, snapshot, manifest) is deleted
  (owner decision 2026-10-13): the replay stack syncs the Engine without the inspect extra, so
  it cannot serve a local Task (contracteval and musique have no golden for the same reason);
  this migration's acceptance check is the one paid run, not a re-record. (4) The shared
  judge-reply parser and redraw helper are not pinned into this Benchmark's revision; accepted
  by the owner, like every imported Benchmark's dependence on shared harness code.
- **Owner-verify:** (1) the next Engine image build prepares the `gdpval-text` bundle (needs the
  `benchmarks` extra, as before) and its Case Digest matches; (2) one paid gdpval-text run after
  merge on an Engine with the inspect extra, its score read beside the hand-built golden's
  0.8044 (25 Cases, the open panel) — this run is the migration's acceptance check, no golden
  re-record; (3) notebook 10 opened against `just local-stack-notebooks` once.
