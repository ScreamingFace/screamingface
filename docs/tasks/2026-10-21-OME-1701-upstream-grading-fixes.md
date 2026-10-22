---
id: OME-1701
linear_url: https://linear.app/openmined/issue/OME-1701/fix-the-grading-and-case-bugs-inherited-from-inspect-evals-in-eleven
status: done
type: bug
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-10-21
closed: 2026-10-21
---

# Fix the grading and Case bugs inherited from inspect_evals in eleven imported Benchmarks

Eleven Imported Benchmarks grade with, or build their Cases with, inspect_evals v0.20.0 code
that inspect_evals has since found wrong. We stay on v0.20.0 and adopt each fix as our own
Named Deviation citing the inspect_evals item, with a tripwire test that fails when a pin bump
brings the fix. Seven stacked PRs, one fix each:

- PR 1: the revision rule (a scorer of ours joins the revision by its source), and paws and
  boolq graded on a bare Yes or No (inspect_evals PR #2334).
- PR 2: chembench's letters graded as a set (#2591) and InfiniteBench Math.Find by its first
  number (#2346).
- PR 3: MATH reads its answer line through a boxed answer, outer delimiters and bold (#2199,
  #2340, and ours).
- PR 4: worldsense keeps every trial, 40,176 → 87,048 Cases (#2507).
- PR 5: stereoset keeps every record, 2,115 → 2,123 Cases (#2524).
- PR 6: onet_m6 leaves out 18 more questions whose options v0.20.0 misparses (#2590), and 1
  whose source gives its key's text to two options, 391 → 372.
- PR 7: a reply cut off before its answer reaches the scorer as cut off, and AIME scores it
  wrong (issue #2701).

Published revisions are frozen (owner decision, 2026-10-22). The eight rows whose fix changes
only the grading (paws, boolq, chembench, infinite_bench_math_find, math, aime24, aime25, aime26)
keep main's revision through `published_revision`; the three whose Cases change publish a new
one (worldsense, stereoset, onet_m6). The per-row table is in the work ledger:
`docs/work/2026-10-21-upstream-grading-fixes.md`.

- 2026-10-21: owner approved the split into seven PRs and every prior-test edit in session; the
  stack was rebuilt on main after OME-1698. Merging the stack and any paid re-run of the moved
  rows are owner steps.
- 2026-10-21: review fixes applied on every PR (one commit each). After the deploy, the owner
  retires the orphaned scoreboard rows `inspect-worldsense` and `inspect-stereoset` (see the
  ledger's owner-verify note).
- 2026-10-22: owner decision, hold 8 / move 3: the eight grading-only rows hold main's
  published revision, each computed fingerprint pinned in `test_benchmark_fingerprints.py`; only
  worldsense, stereoset and onet_m6 publish a new revision. The leaderboard had no entry or
  baseline on any of the eleven.
