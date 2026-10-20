---
ticket: OME-1653
stack: screamingface
status: planned
started: 2026-10-20
finished:
---

# e4b-mapreduce-surface — replace the recipe surface with map → select → reduce

## Intent

The Product Owner proposed a map → select → reduce grammar for recipes (notebook
`e4b-combine-mapreduce.ipynb`, 2026-10-20). The owner took it with no backward compatibility, put
it on top of PR #1461 so the E4b stack merges with the final surface, and added an Engine narrow
step so a narrow step can come before a reducer.

## Planned changes

- See the plan: `docs/plan/2026-10-20-e4b-mapreduce-surface.md` §2 (units 0–8).

## Test plan

- See `docs/spec/2026-10-20-e4b-mapreduce-surface/test-plan.md`.

## Acceptance

- The 13 notebook cases and the part 2–7 recipes run in the new form; the parity set compiles to
  today's bytes except the planned changes (overview §4); `Filter >> Mean` and `Rank >> Vote` run
  in one combine call; the old names are gone; all gates green.

## Log

- 2026-10-20: owner answers A0–A5 (overview §5). Five scouts mapped the compile path, the url4
  rebuild and UI, the Engine combine spec, the public surface, and the test, docs and template
  scope. Spec and plan written (unit 0).
- 2026-10-20: Opus spec review → ESCALATE (4 blocker, 11 major, 7 minor). All 22 findings applied:
  private `_surface` staging + one swap unit (12); `ReduceNode` kept internal as the `over=`
  extractor target (1); pinned `name@v` ids in `over=`/`normalize=` (10); Engine judged set for
  `scores@1` after narrow (2); the one-step places listed (3); member-row rules (4); `NR-C1` refuses
  narrow before Merge/JudgePick/model-fallback Gate (5); one judge per block incl. JudgePick (6); no
  associativity claim (7); corrective loops stay root (8); `First` keeps today's equals rule (9);
  `Node` names for every internal class (11); 4 Engine `test_sdk_*` files in the migration (13);
  O13 message rewording + MSG-1 (14); rg check scope (15); minors 16–22.
- 2026-10-20: second Opus review → PASS WITH FIXES. Applied: `judged` = `present` before any
  narrow step; LO-0 (`lower()` is the identity on old values until the swap) and LO-5 only for a
  closed block; private `_narrow` carrier; one lowering point for every recipe entry; unit 6
  rebuild through `_surface.rebuild` with an exec namespace, judge round trips + RB-2 in unit 7;
  one snapshot statement; fixture list; CH rows moved to the units that add the steps; narrow
  record `signal` + `scores`; EX-2 sentinel; MSG-1 by an `ast` scan with an allow list; CH-14;
  O14/GA-6 (gated vote with an extractor `over=` refused; owner choice open).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

## Unit 2: chain-core

### Intent

Build the core of the new recipe surface in the private package `screamingface._surface`: the
`>>` chain, `Fanout`, `Synthesize`, `Vote`/`Median`/`Mean` with `over=`, the extractor strings,
and the lowering to today's classes. Lower once at the first compile entry. No public name, no
snapshot and no existing test changes.

### Files (planned)

- New: `S/_surface/__init__.py`, `chain.py`, `fanout.py`, `synthesize.py`, `steps.py`, `refs.py`,
  `lowering.py`.
- Edit: `S/recipe.py` (`_recipe` refuses a step and an open chain; a closed chain is a recipe),
  `S/_evaluation/candidate.py` (the entry: judge-writer walk on the user's chain, then `lower()`),
  `S/_evaluation/model.py` (`_candidate_values` lowers), `S/_evaluation/compilation.py` and
  `S/_evaluation/runner.py` (the lowered values pass through).
- New tests: `ST/test_chain_rules.py`, `test_fanout.py`, `test_synthesize.py`, `test_lowering.py`,
  `test_surface_extract.py`, `test_surface_parity.py`, `test_chain_warnings.py`.

### Rows

CH-1, CH-2, CH-8, CH-9, CH-11, CH-13, CH-14, NM-1, WJ-1, FA-1, FA-2, SY-1, LO-0..LO-6, EX-1,
EX-2, LO-P1 (test plan "Unit 2").

### Outcome

- **Actual files:** as planned. New `S/_surface/` (`__init__.py`, `chain.py`, `fanout.py`,
  `synthesize.py`, `steps.py`, `refs.py`, `lowering.py`). Edited `S/recipe.py`,
  `S/_evaluation/candidate.py`, `model.py`, `compilation.py`, `runner.py`. Seven new test files
  (232 tests).
- **Commits:** `43579afa7` test (RED), `03ebdbaf2` feat (GREEN), this ledger commit.
- **Compile entry call sites** (`rg "rewrite_fusion_recipe|_candidate_values|recipes_need_operators"`):
  `model.py` `_candidate_values` lowers (the Evaluation entry) and then runs the judge-writer
  walk on the user's values; `runner.py` (`_evaluation_inputs`, `_operators_sync`,
  `_operators_async`, both `compile_evaluation` calls with `lowered=True`) reads the lowered
  values; `compilation.py` `compile_evaluation` lowers through `entry_recipe` unless `lowered=True`,
  then calls `compile_candidate(..., lowered=True)`; `candidate.py` `compile_candidate` runs
  `entry_recipe` (warn, then `lower`) unless `lowered=True`, then `rewrite_fusion_recipe`;
  `recipes_need_operators` is unchanged (it reads lowered values). `url4.py` has no build from a
  user recipe: `_require_recompiles` compiles internal values, so `lower()` is the identity there.
- **Gates:** `run_gates.py screamingface --base e4d44281c` ALL GATES GREEN;
  `run_gates.py repo --base e4d44281c` ALL GATES GREEN. No pinned file changed.
- **Deviations:**
  - `over="json"` lowers to the operator `json_object` (and `json@1` to `json_object@1`): the
    named reducers store an operator name, and the Extract rule `json` is the operator
    `json_object`. The spec says "rule name → `VoteNode(extract=e)`" literally.
  - `normalize=` is on `Vote` only: surface §6 gives `Median`/`Mean` no `normalize=` (the
    normalizer is always numeric), although §9 EX-2 names a passed value for them.
  - `S/recipe.py` `_recipe` refuses a step (CH-11) and an open chain (CH-8) and accepts a closed
    chain, so `CorrectiveLoop`/`SelfCorrective` take chains as members (surface §1) and today's
    containers can hold one; `lower()` walks them.
  - `compile_candidate` and `compile_evaluation` have a new keyword `lowered=False`: the
    Evaluation entry lowers and warns once, and the compile does not warn a second time.
  - `Vote(weights="score:judge")` with no `sf.Judge` raises the CH-10 message at block close
    (unit 3 adds the judge).
  - WJ-1 uses today's judge Fusion as a chain stage: `sf.Judge` arrives in unit 3.
