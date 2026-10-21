---
ticket: OME-1701
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-21
finished:
---

# upstream-grading-fixes — adopt inspect_evals grading fixes as our own Named Deviations

## Intent

Several Imported Benchmarks grade with an inspect_evals v0.20.0 scorer, or build Cases with
v0.20.0 code, that inspect_evals has since found wrong (merged or open fixes). We stay on
v0.20.0 and adopt each fix as our own Named Deviation that cites the inspect_evals item, with a
tripwire test asserting v0.20.0's old behaviour: when a later pin bump brings the fix, the
tripwire fails and says to drop ours. The work is a 7-PR stack under OME-1701, one fix per PR,
each on its own branch `OME-1701-prK-…` stacked on the one before. Each branch's copy of this
ledger carries the sections of the PRs up to its own; PR 7's is the whole.

- 2026-10-21: first built as a 4-PR stack, then split into these 7 on top of main after OME-1698
  merged. The rebase followed OME-1698's rename (`upstream_case_count` is now
  `inspect_evals_case_count`) and its wording in the lines both changes touched.
- 2026-10-22: owner decision, hold 8 / move 3. Published revisions are frozen (grant
  researchers key on them), so the eight rows whose fix changes only the grading (paws, boolq,
  chembench, infinite_bench_math_find, math, aime24, aime25, aime26) keep main's revision through
  `published_revision`, and `test_benchmark_fingerprints.py` pins the fingerprint each fix
  moved (the first rows of the file OME-1610 plans for every Benchmark row). The
  three rows whose Cases change (worldsense, stereoset, onet_m6) publish their new revision. The
  leaderboard had no entry or baseline on any of the eleven (checked 2026-10-22).

## PR 1 — the revision rule, and a bare Yes/No on paws and boolq

### Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/__init__.py`: a
  `scorer_source_pins` rule. A scorer or whole-run metric that is OUR code but lives outside
  the row's Task package joins the revision by its source, as a local Task does; inspect's and
  inspect_evals' scorers ride the package version pins, and a local Task's own scorers ride
  `task_source`. A Named Deviation imports none of our code outside its own package, so the
  hashed package is the whole marking code (tested).
- `.../benchmarks.py`: wire that pin into `_assemble`; point paws and boolq at our scorers;
  honest descriptions; NAMED DEVIATION comments citing inspect_evals PR #2334 (merged).
- `.../named_deviations/` (new): the package docstring, and `yes_no/` with the two scorers.
- tests: `test_named_deviation_yes_no.py`, `test_scorer_source_pins.py` and
  `test_benchmark_fingerprints.py` (new); `test_published_revision.py`'s hand-set list adds paws and
  boolq.

### Test plan

- per row: a bare Yes or No scores correct under ours; a refusal ("I cannot determine this.",
  "I don't know") scores incorrect; the tripwire asserts v0.20.0's scorer credits it.
- pin rule: no row outside paws and boolq moves; a scorer edit moves the revision.

### Acceptance

- paws and boolq keep their published revisions (held); their computed fingerprints move and
  are pinned; every other revision is byte-identical.
- the tripwire names #2334.

## PR 2 — chembench's letter set and InfiniteBench's first number

### Planned changes

- `.../named_deviations/chembench/` (new): multiple choice graded by the set of letters
  (inspect_evals PR #2591, open); numbers stay the eval's own `pattern_mae`.
- `.../local_tasks/infinite_bench/infinite_bench.py`: the official first-number Math.Find rule
  (inspect_evals PR #2346, open); its README's Scoring section says so.
- `.../benchmarks.py`: the chembench and infinite_bench_math_find rows grade with them; honest
  descriptions; NAMED DEVIATION comments.
- tests: `test_named_deviation_chembench.py` and `test_local_task_infinite_bench_scorer.py`
  (new); `test_published_revisions.py` (both rows first frozen here, at their held revisions);
  `test_benchmark_fingerprints.py` and `test_published_revision.py` gain both rows;
  `test_scorer_source_pins.py` (its row set gains chembench).

### Test plan

- chembench: "A, D", "D,A" and "d,a" answer the key "A,D"; a subset does not; the tripwire
  asserts v0.20.0 scores "A, D" 0.
- infinite_bench_math_find: "The largest number in the list is: 91" is right for 91; the
  tripwire asserts inspect's `exact()` scores it 0.

### Acceptance

- chembench and infinite_bench_math_find keep their published revisions (held); their computed
  fingerprints move and are pinned; no other revision moves.

## PR 3 — MATH reads its answer line through the wrapping

### Planned changes

- `.../named_deviations/math/` (new): both MATH scorers read the `ANSWER:` line through our
  extraction, which unwraps `\boxed{}` (inspect_evals PR #2199), strips an outer `\(..\)` or
  `\[..\]` (PR #2340) and drops markdown bold (ours); the compare steps stay the eval's.
- `.../benchmarks.py`: the math row grades with them; antlr4 joins sympy as a pinned scorer
  dependency; description; NAMED DEVIATION comment.
- tests: `test_named_deviation_math.py` (new); `test_benchmark_fingerprints.py` and
  `test_published_revision.py` gain math; `test_scorer_source_pins.py` (its row set gains math).

### Test plan

- each wrapping of a right answer scores correct under ours and 0 under v0.20.0 (the tripwires);
  an unwrapped answer grades exactly as inspect's own scorer grades it.

### Acceptance

- math keeps its published revision (held); its computed fingerprint moves and is pinned; no
  other revision moves.

## PR 4 — Case-set fix: worldsense keeps every trial (new Cases)

### Planned changes

- `.../local_tasks/worldsense/` (new): inspect_evals' Task with each trial identified by its
  own `Key` (inspect_evals PR #2507, merged), so no trial is dropped: 87,048 Cases, every gold
  answer present.
- `prepare.py`, `benchmarks.py`: the row points at the local Task, new count and digests
  (re-imported with the importer into a scratch copy, then the row edited by hand), honest
  description, origin ours, the frontier comment says which accuracy it is.
- tests: `test_local_task_worldsense.py` (new); `test_published_revisions.py` (its literal);
  `test_benchmark_declaration.py` (its catalogue id).

### Test plan

- the id is the trial's own; two trials of one tuple get different ids under ours and the SAME
  id under v0.20.0 (the tripwire, no network); the whole pinned file gives 87,048 Cases under
  ours and 40,176 under v0.20.0 (tripwire on the count).
- balance: every gold answer of each family present, in the dataset's own balance (Infer TRUE =
  FALSE, Consist POSSIBLE = IMPOSSIBLE, Compl "1" = "2" = "3").

### Acceptance

- worldsense publishes a new revision; no other revision moves.
- the tripwire names #2507.

## PR 5 — Case-set fix: stereoset keeps every record (new Cases)

### Planned changes

- `.../local_tasks/stereoset/` (new): inspect_evals' Task with each record identified by the
  dataset's own `id` (inspect_evals PR #2524, merged): 2,123 Cases.
- `prepare.py`, `benchmarks.py`: the row points at the local Task, new count and digests,
  honest description, origin ours.
- tests: `test_local_task_stereoset.py` (new); `test_published_revisions.py` (stereoset first
  frozen here); `test_benchmark_declaration.py` (its catalogue id).

### Test plan

- the id is the record's own; two records of one context get different ids under ours and the
  SAME id under v0.20.0 (the tripwire, no network); the whole pinned file gives 2,123 Cases
  under ours and 2,115 under v0.20.0 (tripwire on the count).

### Acceptance

- stereoset publishes a new revision; no other revision moves.
- the tripwire names #2524.

## PR 6 — Case-set fix: onet_m6 (fewer Cases)

### Planned changes

- `.../prepare.py`: the onet_m6 row leaves out, by id, every Case whose question as v0.20.0
  builds it differs from the number-order option parse of inspect_evals PR #2590 (open):
  the 6 already excluded plus 18 more, each with a short reason, under the same NAMED
  DEVIATION style; new case_count, case_digest, case_set_digest.
- `.../benchmarks.py`: the onet_m6 description says the new count and why.
- tests: one new test file; `test_published_revisions.py` (onet_m6 first frozen here);
  `test_inspect_imported_benchmarks.py` (its onet test pins 6 exclusions and 391 Cases).

### Test plan

- the excluded ids are exactly the Samples whose input, choices or key differ between
  v0.20.0's parse and #2590's, over the whole pinned file (network, as the other whole-file
  tests); each id's reason (key past the end / key names another option / options missing
  or merged, key right) matches the computed one.
- 2021_40_e2b5: excluded; v0.20.0 keys it to "careless", #2590's parse to "restless"; the
  TRIPWIRE (no network, the real record) asserts v0.20.0 still keys "careless".
- the row: 397 less the excluded ids, the revision moves, no other revision moves.

### Acceptance

- onet_m6 publishes a new revision; every other revision is byte-identical.
- the tripwire names #2590.

## Outcome (fill at the end — required before COMMIT)

### PR 1

- **Actual files:** as planned. Each paws/boolq scorer returns inspect_evals' merged
  `pattern(r"...")` expression verbatim (PR #2334 at merge commit 2999eaad; owner rule
  2026-10-22: a ported fix is a verbatim copy with the same names); they live in our own module
  only so their source joins the revision (inspect's scorer kwargs are not a revision input).
- **Revisions:** held (owner decision, 2026-10-22): paws publishes 8f4e0e9c0864a6e7 and boolq
  00d4443ca7e66d43, as on main; their computed fingerprints moved to 992540ea3309d384 and
  588977e58b380d7f, pinned in `test_benchmark_fingerprints.py`. Every one of the 85 imported revisions
  computed before and after: none publishes a new revision.
- **Gates:** relevant tests only (owner rule): `test_named_deviation_yes_no.py` and `test_scorer_source_pins.py` (new), `test_benchmark_fingerprints.py` (new), `test_published_revision.py` (edited), `test_published_revisions.py`, and the row sweeps (failure-policy rows and revisions, benchmark declaration, imported benchmarks): 702 passed, 0 skipped with the inspect extra; 23 passed extra-less (the 10 inspect-only skip). Mutation: one byte added to `yes_no.py` fails both held pins and leaves every published literal passing. ruff check + format and pyright (extra-less) clean on every touched file.

### PR 2

- **Actual files:** as planned, plus two edited prior tests: `test_letter_list_key_imports.py`
  ("A, D" on chembench now scores 1) and `test_local_task_infinite_bench.py` (its row test was
  named for inspect's `exact()`; renamed, and its docstring now says the first-number rule).
- **Revisions:** held (owner decision, 2026-10-22): chembench publishes a36d91b7eb601253 and
  infinite_bench_math_find eb87494cb4dab437, as on main; their computed fingerprints moved to
  b86658ea78c51962 and 1ed274442ad5dba1, pinned in `test_benchmark_fingerprints.py`.
- **Verbatim copies (owner rule 2026-10-22: a ported fix is a verbatim copy with the same
  names):** chembench's scorer is PR #2591's `multiple_choice_letters` and `chembench_scorer`,
  unchanged (head 3bfc894a); the key is now split on commas, as the PR splits it.
  infinite_bench_math_find's scorer is PR #2346's `math_find_scorer.py`, copied into the local
  Task package unchanged (head 0174742e) except the one import v0.20.0 lacks
  (`INVALID_RESPONSE_FORMAT`, replaced by the PR head's own definition of it). Our earlier
  rewrites of both are gone; the row now names the copied modules.
- **Review fixes:** the numeric "agrees with inspect_evals" check now carries the eval's real
  1% relative tolerance and an expected verdict per reply (1.505 vs 1.5 right, 1.6 wrong), so
  a numeric path that always marks wrong fails it; the renamed letter-list test names the
  set-of-letters rule; the scorer docstring states the one one-letter difference ("B,B" or
  "B B" against "B" is now right, as the authors mark it), pinned by a test. The docstring
  edit moved chembench's computed fingerprint once more (2fdb430f6a3505f0 → 7af1d67ffad68471;
  the verbatim copy then moved it to b86658ea78c51962).
- **Gates:** relevant tests only (owner rule): `test_named_deviation_chembench.py` and `test_local_task_infinite_bench_scorer.py` (new), `test_letter_list_key_imports.py`, `test_local_task_infinite_bench.py`, `test_published_revisions.py`, `test_published_revision.py`, `test_benchmark_fingerprints.py` and `test_scorer_source_pins.py` (edited), the yes_no tests, and the row sweeps (failure-policy rows and revisions, benchmark declaration, imported benchmarks): 759 passed, 0 skipped with the inspect extra; 23 passed extra-less (the 14 inspect-only skip). ruff check + format and pyright (extra-less) clean on every touched file.

### PR 3

- **Actual files:** as planned, plus one edited prior test: `test_math_squad_named_scores.py`
  (the dependency pins now list antlr4 beside sympy; its docstring says the conservation
  invariant holds for MATH only on an unwrapped answer line with no trailing carriage return
  or tab).
- **Revisions:** held (owner decision, 2026-10-22): math publishes 0fb750cf19e00c11, as on
  main; its computed fingerprint moved to 4129dccca9dbb8ce, pinned in `test_benchmark_fingerprints.py`.
- **Verbatim copies (owner rule 2026-10-22: a ported fix is a verbatim copy with the same
  names):** the module now holds v0.20.0's two exact-match scorers and `score_helper`, copied
  unchanged (v0.20.0 binds `extract_answer` in its own module, so its scorers can't be pointed
  at ours), and `extract_answer` built from v0.20.0's with PR #2199's and PR #2340's blocks,
  each verbatim and joined the way a merge would. Ours is marked `OURS` where it runs: the
  whitespace-and-bold step before the PR blocks, and the empty-answer-line explanation after
  `score_helper`. ruff format rewrapped two copied lines to our 100-column limit (whitespace
  only), and a file-level pyright directive silences a possibly-unbound warning in the copied
  `score_helper` rather than editing it.
- **Review fixes:** the whitespace trim on the answer line is declared part of the Named
  Deviation (v0.20.0's exact match marked `ANSWER: 42\r` wrong, ours right); two boxes on the
  answer line grade the last one (`\boxed{41} or \boxed{42}` is right for 42), kept as
  inspect_evals PR #2199 and the paper's grader read it, stated in the row description and
  the module docstring and pinned by a test; an answer line holding only wrapping
  (`ANSWER: \boxed{}`, `ANSWER: ****`) stays wrong but now says it is an empty answer line,
  not a missing one. The scorer edits moved math's computed fingerprint once more
  (4974287b20a4f1aa → 414043e2d2a9dbcc; the verbatim copy then moved it to 4129dccca9dbb8ce).
- **Gates:** relevant tests only (owner rule): `test_named_deviation_math.py` (new), `test_math_squad_named_scores.py`, `test_published_revisions.py`, `test_published_revision.py`, `test_benchmark_fingerprints.py` and `test_scorer_source_pins.py` (edited), the yes_no and chembench tests, and the row sweeps (failure-policy rows and revisions, benchmark declaration, imported benchmarks): 751 passed, 0 skipped with the inspect extra; 23 passed extra-less (the 13 inspect-only skip). ruff check + format and pyright (extra-less) clean on every touched file.
- **Deviations:** `**ANSWER: 42**` (markdown bold on MATH's answer line) and a trailing
  carriage return or tab (`ANSWER: 42\r`) have no inspect_evals item; their fixes are ours
  alone.

### PR 4

- **Actual files:** as planned (the local Task package with README, the row in `prepare.py` and
  `benchmarks.py`, one new test file, `test_published_revisions.py`), plus
  `test_benchmark_declaration.py`: its per-Benchmark table is keyed by catalogue id, and the id
  loses the `inspect-` prefix (below).
- **Cases:** 40,176 → 87,048 (case_digest 426b5a4e… → 347a2aa2…, case_set_digest dc359e88… →
  a24618fd…). Sealed by two build replays of the new declaration (`replay_with_provenance` +
  `case_digest`/`case_set_digest`). The importer refuses the local Task: its judge reader does
  not follow a scorer re-exported from another package, so the row is hand-edited (the
  importer's own "add the row by hand" route).
- **Balance (all 87,048):** Infer TRUE = FALSE (10,044 normal, 3,348 trivial), Consist POSSIBLE
  = IMPOSSIBLE (10,044 each grade), Compl "1" = "2" = "3" (3,348 each grade). Best constant
  answer per family: 0.917 on the 40,176, 0.462 on the 87,048.
- **Revisions:** worldsense a2f8699ca22f49e5 → ad49b23d305a87dd; no other moved.
- **Verbatim copy (owner rule 2026-10-22: a ported fix is a verbatim copy with the same
  names):** `worldsense` and `record_to_sample` are inspect_evals' own, as merged with PR #2507
  (merge commit 2cb54ae9), names and bodies unchanged; our earlier wrapper (inspect_evals'
  Sample with its id replaced) is gone. Ours: the Task's `version=`/`metadata=` lines are left
  out, marked; ruff format rewrapped two copied lines (whitespace only) and a file-level
  `noqa: E501` keeps their docstring's long lines. Two build replays reproduce the sealed
  Cases exactly (87,048; case_digest 347a2aa2…, case_set_digest a24618fd…). The copy moved the
  revision once more (a9ea4fd817d0f54b → ad49b23d305a87dd).
- **Review fixes:** the frontier score is GPT4's own published replies scored on our headline
  metric (the plain mean over all 87,048 trials): 0.730 (63,551 right), from the authors'
  `basic___GPT4___results.jsonl` at the pinned commit. The paper's 0.756 ("WS avg.") weights
  trials per tuple and grades the Compl questions know/don't-know ("1" and "2" both KNOW in
  the authors' `compute_acc_table`); re-implementing it on the same files reproduces 0.756
  (GPT4) and 0.556 (GPT3.5). The provenance change alone keeps the revision; the Task
  docstring's correction (the Sample id is not inside the Case Digest: served Cases are
  numbered, the id only decides which trials survive the duplicate filter) moved it once more
  (c6ed2a98cd4ff1ca → a9ea4fd817d0f54b).
- **Gates:** relevant tests only (owner rule): `test_local_task_worldsense.py` (new), `test_benchmark_declaration.py` and `test_published_revisions.py` (edited), and the row sweeps (failure-policy rows and revisions, imported benchmarks, scorer source pins): 689 passed, 0 skipped with the inspect extra; 23 passed extra-less (the 8 inspect-only skip). ruff check + format and pyright (extra-less) clean on every touched file. Mutation (measured before the split, on worldsense and stereoset together): dropping the id override fails 4 of their 14 new tests.
- **Deviations:** the existing invariant "a Task under `local_tasks/` is origin `screamingface`"
  (test_inspect_imported_benchmarks) holds, as for infinite_bench and bbh, so the row is now
  ours: catalogue id `worldsense` (was `inspect-worldsense`), and `inspect_contributors` moves to
  a comment (the provenance rule allows it only on inspect_evals-origin rows). The on-disk
  bundle grows about 2.2×, 174 MiB → 376 MiB (cases.json 17.5 MB → 38.2 MB, i.e. 36.4 MiB, plus
  one ~170-byte target file per Case, each taking a whole disk block); OME-1675 already lists
  it as an unmeasured large bundle under the per-run memory budget.

### PR 5

- **Actual files:** as planned (the local Task package with README, the row in `prepare.py` and
  `benchmarks.py`, one new test file, `test_published_revisions.py`), plus
  `test_benchmark_declaration.py` (the id loses the `inspect-` prefix, as worldsense's did).
- **Cases:** 2,115 → 2,123 (case_digest 1c3774ed… → 2c8f8b3b…, case_set_digest 69db3f56… →
  be5e20b5…), the old 2,115 a subset of the new. Sealed by two build replays of the new
  declaration, which reproduce the old seal exactly on the old Task; hand-edited row, as
  worldsense's.
- **Revisions:** stereoset 6fe6deab5af299e2 → c2bf158bee6d5f8b; no other moved.
- **Verbatim copy (owner rule 2026-10-22: a ported fix is a verbatim copy with the same
  names):** `stereoset` and `record_to_sample` are inspect_evals' own, as merged with PR #2524
  (merge commit 5f2013df; both are v0.20.0's plus the PR's id line), names and bodies unchanged;
  our earlier wrapper and hoisted `INSTRUCTIONS` table are gone. Ours: the Task's
  `version=`/`metadata=` lines are left out, marked; the merge commit's later, unrelated scorer
  changes are not taken (the scorers stay v0.20.0's). Two build replays reproduce the sealed
  Cases exactly (2,123; case_digest 2c8f8b3b…, case_set_digest be5e20b5…). The copy moved the
  revision once more (dd1c2cc6e587ed15 → c2bf158bee6d5f8b).
- **Review fixes:** the row description and the Task README no longer call our score the
  paper's language modeling score: it is a multiple-choice adaptation (the model picks one of
  three sentences once; the paper compares likelihoods, two comparisons per record, averaged
  per target term) and not comparable with it. The description is not a revision input, so
  the revision holds.
- **Gates:** relevant tests only (owner rule): `test_local_task_stereoset.py` (new), `test_benchmark_declaration.py` and `test_published_revisions.py` (edited), and the row sweeps (failure-policy rows and revisions, imported benchmarks, scorer source pins): 692 passed, 0 skipped with the inspect extra; 23 passed extra-less (the 8 inspect-only skip). ruff check + format and pyright (extra-less) clean on every touched file.
- **Deviations:** origin ours, catalogue id `stereoset` (was `inspect-stereoset`),
  `inspect_contributors` moves to a comment, as for worldsense.

### PR 6

- **Actual files:** `prepare.py` (the onet_m6 row: 18 ids with a reason each under a second
  NAMED DEVIATION block, new count and seals), `benchmarks.py` (the description),
  one new test file `test_onet_m6_option_parse_exclusions.py`, and two edited prior tests:
  `test_published_revisions.py` (onet_m6 first frozen here) and
  `test_inspect_imported_benchmarks.py` (its onet test pinned 6 exclusions and 391 Cases; now
  6 + 18 + 1 and 397 − 25, docstring says why).
- **Probe (pinned revision 93ffb5e3, inspect_evals' own Task, both parses):** 24 of 397 Samples
  differ: the 6 already excluded (key past the last option), 16 whose key names another
  option's text, 2 whose key is right but an option is missing. The other 373 are identical,
  question text included. Same ids under both parses (the id hashes the question only).
- **Cases:** onet_m6 391 → 372 (case_digest 92d013fe… → 224831b1…, case_set_digest
  7a6f28e4… → 89e60804…). Sealed by two build replays (`replay_with_provenance`), which
  reproduce the old seal exactly on the old six-id declaration; the 372 are the old 391 less
  the 19, same bytes and order bar the positional Case ids.
- **Revisions:** onet_m6 fefdc98fb53b0777 → cfc5f0da9f9418bd; no other moved.
- **Review fixes:** a 25th exclusion, under its own note (not #2590's): 2020_32_08b1 gives
  options C and E the same text ("สนับสนุน สรุป สนับสนุน") and the key is C, so an E reply
  names the right answer and is marked wrong; a source-data fault neither parser catches, and
  the only question both parses agree on whose key's text sits under two letters (pinned by a
  test). It took the row 373 → 372 and the revision fa7e02ef6c82f99d → cfc5f0da9f9418bd. The
  tripwire message now says #2590's parser fixes all 24 parse exclusions (the 18 can come
  back, the six need the OME-1269 decision owner's OK); the #2590 copy is a faithful copy with
  annotations, not verbatim; the revision comment says the questions are excluded, the parser
  not adopted; and the row comment names the deciding reason for not re-parsing (it needs a
  local Task, so a new origin and catalogue id).
- **Gates:** relevant tests only (owner rule): `test_onet_m6_option_parse_exclusions.py` (new), `test_inspect_imported_benchmarks.py` and `test_published_revisions.py` (edited), and the row sweeps (failure-policy rows and revisions, benchmark declaration, scorer source pins): 691 passed, 0 skipped with the inspect extra; 23 passed extra-less (the 8 inspect-only skip). ruff check + format and pyright (extra-less) clean on every touched file. Mutation (measured before the split): un-excluding 2021_40_e2b5 fails 3 of the 5 new tests.
- **Deviations:** #2590 is still open (not merged), so the tripwire guards a fix inspect_evals
  has not landed yet. Re-parsing would have changed only these 24 rows (the other 373 are
  identical under both parses); the deciding reason against it is that it needs a local Task,
  so a new origin and catalogue id for the row (the stack adopts other open PRs where the fix
  sits beside inspect_evals' Task); exclusion kept, per the owner's call.
