---
ticket: OME-1268
stack: screamingface-engine
status: done
started: 2026-10-06
finished: 2026-10-06
---

# ome-1268-importer-named-scores — the importer keeps every conservable scorer (PR 4 of 5)

## Intent

The fourth slice of the OME-1268 stack. The importer stops refusing a Task with several
scorers: it keeps every conservable scorer (`scorer` = the first conservable one, the
Headline Score; `extra_scorers` the rest; `named_scores` their registry names, headline first),
writes any scorer it leaves out as a `dropped_scorers` Named Deviation with a review TODO, and
flags a headline that differs from upstream's first scorer. The headline-metric tripwire refuses
a Task whose headline metric is not a plain mean (SimpleQA's `simpleqa_metric`) by name; a
non-mean metric on another scorer is a dropped-metric note, not a refusal. Case Preparation
accepts SQuAD's list of accepted answers as the Case's target. No new Benchmark row lands here.
Stacked on PR 3 (#1249).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`:
  `_scorer_reference` returns every conservable scorer; `InspectTaskFacts` gains
  `extra_scorers`, `named_scores`, `dropped_scorers`, `headline_differs`; `_scorer_lines`
  renders the three fields, the TODOs and the tripwire; `_custom_metrics` stays the review flag
- `apps/screamingface-engine/src/screamingface_engine_inspect/import_replay.py`: the
  Task-replay facts carry the same fields
- `apps/screamingface-engine/src/screamingface_engine_inspect/task_replay_rows.py`: passes
  them to the shared scorer lines
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`:
  `_validated_answer_key` accepts a non-empty list of non-blank strings; `prepared_case`
  freezes it as a JSON list

## Test plan

- `tests/unit/inspect/test_importer_named_scores.py` (new): a two-scorer stand-in Task renders
  `scorer`, `extra_scorers`, `named_scores`; a self-grading scorer is dropped by name with a
  review TODO and the headline moves; a Task with no scorer is refused; a single-scorer Task
  renders byte-identically; a formula headline metric is refused naming it; a grouped metric on
  a non-headline scorer is a note, not a refusal
- `tests/unit/inspect/test_list_target.py` (new): a list of accepted answers is frozen as a
  list; an empty list and a list with a non-string are refused by name; the adapter grades
  against a list target through the real prepared record

## Acceptance

- Spec §8 items 2 (the "never silently truncated" half), 4, 6, 7; plan Review Focus 5 and 6.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Changed: `importer.py` (`ScorerFacts`, `_scorer_facts`,
  `_resolve_scorer` replacing `_scorer_reference`; `InspectTaskFacts` ×5 fields;
  `_scorer_lines` keyword fields, `_named_score_lines`, `_tuple_literal`;
  `_refuse_injectable_text`), `import_replay.py` (`TaskReplayFacts` ×5 fields),
  `task_replay_rows.py` (the shared lines and the guard), `prepare.py`
  (`_validated_list_key`, `_validated_answer_key` returns `str | list[str]`),
  `scorer_metrics.py` (`headline_metric_name`, `extra_metric_names` public,
  `_declared_metric_names`). New tests: `tests/unit/inspect/test_importer_named_scores.py`
  (10), `tests/unit/inspect/test_list_target.py` (5). One prior test fixture changed:
  `test_every_other_refusal_stays_a_plain_refusal` (see Deviations).
- **Commits:** f246cf767 — feat(screamingface-engine): import Tasks with several scorers and
  list answer keys
- **Gates:** `run_gates.py screamingface-engine` stops at the append-only lane on the one
  prior-test fixture change (owner `--skip-append-only`, named in the PR body); every other
  lane run by hand and green: ruff check, ruff format --check, pyright (0 errors with the
  inspect extra), layering OK, pytest `-n auto --cov-fail-under=80` 5574 passed / 44 skipped.
  `test_published_revisions.py` and the `render_generated_rows` tests untouched and green.
- **Deviations:** (1) the prior test `test_every_other_refusal_stays_a_plain_refusal` used
  a two-scorer Task as its "plain refusal" fixture; that Task now imports by design, so the
  fixture is a no-scorer Task with the same assertion (append-only exception, owner press).
  (2) The tripwire lives in the reader (`_scorer_facts`), not the renderer, so the Task-replay
  path gets it for free. (3) "Conservable" = `_is_judged_by` is False; a dict-valued scorer's
  names are still hand-written. (4) The OME-1253 sweep re-check (spec §8.7) is deferred to
  PR 5, which runs the importer for real.
