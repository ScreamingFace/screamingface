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

## PR 1 — the revision rule, and a bare Yes/No on paws and boolq

### Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/__init__.py`: a
  `scorer_source_pins` rule. A scorer that is OUR code but lives outside the row's Task package
  joins the revision by its source, as a local Task does; inspect's and inspect_evals' scorers
  ride the package version pins, and a local Task's own scorers ride `task_source`.
- `.../benchmarks.py`: wire that pin into `_assemble`; point paws and boolq at our scorers;
  honest descriptions; NAMED DEVIATION comments citing inspect_evals PR #2334 (merged).
- `.../named_deviations/` (new): the package docstring, and `yes_no/` with the two scorers.
- tests: `test_named_deviation_yes_no.py` and `test_scorer_source_pins.py` (new);
  `test_published_revisions.py` literals for paws and boolq.

### Test plan

- per row: a bare Yes or No scores correct under ours; a refusal ("I cannot determine this.",
  "I don't know") scores incorrect; the tripwire asserts v0.20.0's scorer credits it.
- pin rule: no row outside paws and boolq moves; a scorer edit moves the revision.

### Acceptance

- paws and boolq each publish a new revision; every other revision is byte-identical.
- the tripwire names #2334.

## Outcome (fill at the end — required before COMMIT)

### PR 1

- **Actual files:** as planned. The paws/boolq Yes/No patterns are inspect_evals' merged ones;
  they live in our own module only so their source joins the revision (inspect's scorer kwargs
  are not a revision input).
- **Revisions:** paws 8f4e0e9c0864a6e7 → ab44cff9bea304ca; boolq 00d4443ca7e66d43 →
  b4a47768ef2ebf95. Every one of the 85 imported revisions computed before and after (on the
  original combined change): only the scorer-fix rows moved.
- **Gates:** relevant tests only (owner rule): `test_named_deviation_yes_no.py` and `test_scorer_source_pins.py` (new), `test_published_revisions.py` (edited), and the row sweeps (failure-policy rows and revisions, benchmark declaration, imported benchmarks): 695 passed, 0 skipped with the inspect extra; 21 passed extra-less (the 8 inspect-only skip). ruff check + format and pyright (extra-less) clean on every touched file.
