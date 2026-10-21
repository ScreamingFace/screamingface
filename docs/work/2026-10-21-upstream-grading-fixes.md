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
- tests: `test_named_deviation_math.py` (new); `test_published_revisions.py` (math's literal);
  `test_scorer_source_pins.py` (its row set gains math).

### Test plan

- each wrapping of a right answer scores correct under ours and 0 under v0.20.0 (the tripwires);
  an unwrapped answer grades exactly as inspect's own scorer grades it.

### Acceptance

- math publishes a new revision; no other revision moves.

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
- **Revisions:** math 0fb750cf19e00c11 → 414043e2d2a9dbcc.
- **Review fixes:** the whitespace trim on the answer line is declared part of the Named
  Deviation (v0.20.0's exact match marked `ANSWER: 42\r` wrong, ours right); two boxes on the
  answer line grade the last one (`\boxed{41} or \boxed{42}` is right for 42), kept as
  inspect_evals PR #2199 and the paper's grader read it, stated in the row description and
  the module docstring and pinned by a test; an answer line holding only wrapping
  (`ANSWER: \boxed{}`, `ANSWER: ****`) stays wrong but now says it is an empty answer line,
  not a missing one. The scorer edits moved math's revision once more
  (4974287b20a4f1aa → 414043e2d2a9dbcc).
- **Gates:** relevant tests only (owner rule): `test_named_deviation_math.py` (new), `test_math_squad_named_scores.py`, `test_published_revisions.py` and `test_scorer_source_pins.py` (edited), and the row sweeps (failure-policy rows and revisions, benchmark declaration, imported benchmarks): 710 passed, 0 skipped with the inspect extra; 23 passed extra-less (the 9 inspect-only skip). ruff check + format and pyright (extra-less) clean on every touched file.
- **Deviations:** `**ANSWER: 42**` (markdown bold on MATH's answer line) and a trailing
  carriage return or tab (`ANSWER: 42\r`) have no inspect_evals item; their fixes are ours
  alone.
