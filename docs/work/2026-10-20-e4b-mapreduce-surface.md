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

- 2026-10-20: unit 1 (Engine narrow) built in worktree e4b-narrow, design review ACCEPT WITH FIXES,
  fix round done (Engine NR-C1, `reduce` key, judged default, whole-message tests). OWNER APPROVED
  the unit 1 pinned edits: combine-spec.v1.json, combine-evidence.v1.json,
  public_surface_snapshot.json, answer.v1.json, and the literals in test_combine_evidence_words.py,
  test_combine_consistency_words.py, test_band_words.py, test_evidence_words.py,
  test_gate_words.py, test_pick_output.py. Cherry-picked onto this branch (c31a90603..0000b95f4).
  Errata U1a–U1h applied to the spec.

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
  (232 tests; 251 after the fix round).
- **Commits:** `43579afa7` test (RED), `03ebdbaf2` feat (GREEN), this ledger commit.
- **Compile entry call sites** (`rg "rewrite_fusion_recipe|_candidate_values|recipes_need_operators"`):
  `model.py` `_candidate_values` lowers (the Evaluation entry) and then runs the judge-writer
  walk on the user's values; `runner.py` (`_evaluation_inputs`, `_operators_sync`,
  `_operators_async`, both `compile_evaluation` calls with `warn_judge_writers=False`) reads the lowered
  values; `compilation.py` `compile_evaluation` runs `entry_recipe` (the warning only when
  `warn_judge_writers=True`), then `compile_candidate(..., warn_judge_writers=False)`;
  `candidate.py` `compile_candidate` always runs `entry_recipe`, then `rewrite_fusion_recipe`;
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
  - `compile_candidate` and `compile_evaluation` have a new keyword (`warn_judge_writers=True` after the fix round): the
    Evaluation entry lowers and warns once, and the compile does not warn a second time.
  - `Vote(weights="score:judge")` with no `sf.Judge` raises the CH-10 message at block close
    (unit 3 adds the judge).
  - WJ-1 uses today's judge Fusion as a chain stage: `sf.Judge` arrives in unit 3.

### Fix round (design review: ACCEPT WITH FIXES)

- **Fixed:** (1) a `Vote` holds the normalizer that applies and an `sf.Extract` in `over=` holds
  none, so equal votes lower to equal bytes; the default marker stays only for
  `over="benchmark"`; `Median`/`Mean` hold a bare extract and refuse a non-numeric one.
  (3) `compile_candidate` always lowers; the keyword is now `warn_judge_writers=True` (it was
  `lowered=`), and `_candidate_values` and `compile_evaluation` use the one `entry_recipe` helper
  (warn on the user's values, lower, then the name checks). (9) `over="benchmark@1"` and a
  normalizer with `over="benchmark"` are refused with `over=` messages. (10) a judge-weighted
  `Vote` checks its other options at construction. (4) the lowering rebuilds with `_kept_name`;
  unit 7 deletes `fusion_recipe.py`. (5) `Fanout` uses `fusion._members(values, kind)`; the Fusion
  messages keep their bytes. (13) a chain flattens an unnamed `Pipeline` of today; one
  `_Chainable` mixin gives `>>`; the repr hides `_is_named`. (14) test fixes: `match=`, an explicit
  `_LATER_UNITS` set for the doc examples of units 3–4, `inspect_aime`, no `# ----` dividers in
  `src`.
- **Recorded for later units:** the FA-2 wording (unit 3), a recipe on the left of `>>` (unit 7),
  the WJ-1 test with different numbering (unit 3), the card of a Fusion that holds a chain (unit 6).
- **Commits:** `ee6a50afd` test (RED), `fdb7b5344` fix (GREEN), this ledger commit.
- **Tests:** 251 tests in the 7 unit-2 files; full SDK suite 5145 passed, 33 skipped.
- **Gates:** `run_gates.py screamingface --base e4d44281c` ALL GATES GREEN;
  `run_gates.py repo --base e4d44281c` ALL GATES GREEN.

## Unit 3: steps

### Intent

Add the score, narrow and the other reduce steps to the private surface: `Judge`, `JudgePick`,
`Rank`, `Filter`, `Concat`, `ArgMax`, `ArgMin`, `First`, `Merge`, signal key strings in `by=` and
`weights=`, and `field()`. Add the chain rules that need them (CH-3..CH-7, CH-10, CH-12, NR-C1 for
`Merge`/`JudgePick`), errata E4 (FA-2 only with no narrow step) and E6 (WJ-1 with a block that
lowers to `Pipeline([Fusion, writer])`). Every step lowers to today's classes and today's `@1`
judge templates.

### Files (planned)

- New: `S/_surface/judge.py`. Edit: `S/_surface/steps.py`, `refs.py`, `chain.py`, `lowering.py`,
  `__init__.py`; `S/_evaluation/candidate.py` (the judge-writer walk inside a block).
- New tests: `ST/test_chain_rules_steps.py`, `test_judge_step.py`, `test_narrow_steps.py`,
  `test_reduce_steps.py`; appended: `test_surface_parity.py` (LO-P2), `test_chain_warnings.py`
  (E6). The E4 test is in `test_narrow_steps.py`.

### Rows

CH-3..CH-7, CH-10, CH-12, JU-1, JU-2, RA-1, FI-1, RE-1, AR-1, SI-2, NR-C1 (Merge, JudgePick),
LO-P2, E4, E6 (test plan "Unit 3").

### Outcome

- **Actual files:** new `S/_surface/judge.py`; edited `S/_surface/__init__.py`, `chain.py`,
  `lowering.py`, `refs.py`, `steps.py`, `S/_evaluation/candidate.py`. New tests
  `test_chain_rules_steps.py`, `test_judge_step.py`, `test_narrow_steps.py`,
  `test_reduce_steps.py`; appended `test_surface_parity.py` and `test_chain_warnings.py`.
- **Commits:** `30fb33e2b` test (RED), `c8ad95b6d` feat (GREEN), this ledger commit.
- **Tests:** 365 tests in the 11 surface test files (114 new in unit 3); full SDK suite 5259
  passed, 33 skipped.
- **Gates:** `run_gates.py screamingface --base e4d44281c` ALL GATES GREEN;
  `run_gates.py repo --base e4d44281c` ALL GATES GREEN. No pinned file changed.
- **Deviations:**
  - The doc examples `readme-418-pick-confidence` (`Pick("confidence", order="max")`) and
    `readme-528-rank-by-field` (`Rank(by_field=...)`) stay out of the doc parity: in the new
    surface a field pick reads a signal (overview §4.2), so their bytes change at the swap. The set
    is now `_PLANNED_BYTE_CHANGES`; S5 and S7 compare their new form with today's `by_signal`
    form. Every other README and docs example is in the parity (no example needs the gate).
  - `Filter(over=)` refuses a pinned rule name (`"last_line@1"`): today's `Filter(extract=)` holds
    an `sf.Extract`, which has no pin.
  - A step that reads `score:judge` is checked when it is built with a probe judge; the block's
    `Judge` is used at block close.
  - `Judge` and `JudgePick` hold today's `sf.Judge` as their compile node; their equality is its
    typed key (`params={"t": True}` is not `{"t": 1}`).
  - E6: the judge and writer inside one block warn with the block's lowered Pipeline name and its
    stage numbers 1 and 2 (today's message for the same form, `Pipeline([Fusion(Rank by judge),
    writer])`); the chain's own stage numbers stay the user's.
  - `FieldRule` is re-exported from `screamingface._surface`.

### Fix round (unit 3 review: ACCEPT WITH FIXES)

- **Fixed:** (1) `sf.field(path) == value` keys on the value's JSON text (today's `Pick`), so
  `== 7` and `== "7"` are equal and `== 1` and `== True` are not. (2) `Merge` equality follows
  the field order. (3) `sf.field ==`, `output=` and `First` refusals have new-surface messages
  (no deleted `Pick` name). (4) `ArgMax`/`ArgMin` are two leaves of the private `_ArgBest`.
  (5) `Judge`/`JudgePick` share the private `_JudgeStep` (`_returns`); the repr shows `params`
  only when set. (6) `readme-418-pick-confidence` and `readme-528-rank-by-field` are in the doc
  parity again, compared in-process with today's `by_signal` rewrite (`_TODAY_REWRITE`), not with
  the golden. (9) exact-message JU-1, CH-2 after a `Judge`, CH-3 for a `JudgePick` after
  `Judge >> Rank`. (10) the probe-judge invariant comment. (12) style: the comment above the
  return, `_judge` for unused parameters, `step_node` not in `__all__`, `matches` from `blocks`
  in the package, the field-path alias renamed, a test renamed to what it checks.
- **Note:** JU-1 is today's construction rule, so `Median(weights="score:judge")` raises when it
  is built, before the `>>` that would close the block; the test builds the `Fanout >> Judge`
  chain first and shows the refusal in that expression.
- **Commits:** `655af1a3b` test (RED), `e53872539` fix (GREEN), this ledger commit.
- **Tests:** 379 in the 11 surface test files.
- **Gates:** `run_gates.py screamingface --base e4d44281c`: the append-only check lists only the
  owner-approved unit-1 files (`answer.v1.json`, `public_surface_snapshot.json`,
  `test_band_words.py`, `test_evidence_words.py`, `test_gate_words.py`, `test_pick_output.py`);
  with `--skip-append-only` ALL GATES GREEN. `run_gates.py repo --base e4d44281c` ALL GATES GREEN.

## Unit 4: gate

### Intent

Add `Gate(*, when, then, otherwise="abstain", abstain_if=None)` to the private surface, with the
gate references `sf.signal(x).chosen()`, `sf.signal(x).mean()` and `sf.agreement()`, their
comparisons and `.between(lo, hi)`. A gate lowers to today's `sf.Vote(gate=sf.Gate(...))`.

### Files (planned)

- New: `S/_surface/gate.py`. Edit: `S/_surface/refs.py` (the gate references), `chain.py`
  (NR-C1 for a model-fallback gate), `lowering.py`, `judge.py`, `steps.py`, `__init__.py`.
- New test: `ST/test_gate_surface.py`.

### Rows

GA-1..GA-6, NR-C1 (gate), GA-P, SI-1, CH-10 (a gated judge-weighted vote reads the judge).

### Outcome

- **Actual files:** new `S/_surface/gate.py`; edited `S/_surface/refs.py` (`SignalRef` with
  `.chosen()`/`.mean()`, `GateRef`, `GateCondition`, `GateBand`, `agreement()`), `chain.py`
  (`_sees_every_member()` is now a method, so a gate answers per instance), `judge.py`,
  `steps.py`, `lowering.py` (`_gate_node`, `_fallback_node`), `__init__.py`. New test
  `ST/test_gate_surface.py` (44 tests).
- **Commits:** `999c92fce` test (RED), `f29a80b6e` feat (GREEN), this ledger commit.
- **Tests:** 423 in the 12 surface test files; full SDK suite 5363 passed, 33 skipped.
- **Gates:** `run_gates.py screamingface --base e4d44281c`: the append-only check lists only the
  owner-approved unit-1 files; with `--skip-append-only` ALL GATES GREEN.
  `run_gates.py repo --base e4d44281c` ALL GATES GREEN.
- **Deviations:**
  - `sx.signal(key)` returns `SignalRef`, a subclass of today's `Signal` with `.chosen()` and
    `.mean()`; today's `sf.signal` does not change. Every step stores a plain `Signal`, so a
    lowered value keeps today's typed equality (the block form keys on the option type).
  - GA-1 and GA-2 keep today's messages: the agreement rules come from today's `sf.Gate`, and an
    undeclared name raises the Fusion message at block close ("the gate reads 'chosen:conf', but
    this Fusion does not declare 'conf' ..."), which the O13 rewording at the swap covers.
  - `.between(lo, hi)` checks its band with new messages (two numbers, finite, `lo <= hi`, and a
    share in [0, 1] for `sf.agreement()`), so no message names `abstain_band`.
  - A comparison of a gate reference with a bool, a non-number or a non-finite number raises at
    the comparison.
  - No doc example needed the gate, so no exclusion set was left to clear; GA-P compares the
    README part 5 and 6 recipes (g1–g4, s2) and two more (a writer fallback with a band and
    weights, a judge-weighted gated vote with a JudgePick fallback) in-process.

### Fix round (unit 4 review: ACCEPT WITH FIXES)

- **Fixed:** (1) the gate threshold and the band go through `_signals._finite_number`, so a huge
  int (`10**400`) is "not finite" and no `OverflowError` escapes. (2) `Filter` rebuilds a signal
  comparison around today's `Signal` (`refs.plain_comparison`), so no step and no lowered node
  holds a `SignalRef`. (3) `+ 0.0` on the threshold and the band: `-0.0` and `0.0` are one value
  with one url4. (4) source-like reprs: `agreement() >= 0.5`,
  `signal('risk').mean().between(2.5, 3.5)`. (5) an agreement condition is checked as a share
  when it is built, with the band's message ("sf.agreement() is a share: compare it with numbers
  between 0 and 1"); the GA-1 test now pins that message for a threshold above 1. (7) the GA-P
  comment names the README anchors. (8) the Merge docstring says it reads the whole Fusion
  context. (9) `signal_key` names `by=` and `weights=`.
- **Swap notes (unit 7):** `.chosen()` and `.mean()` move onto today's `Signal`, and `SignalRef`
  and `refs._plain` are deleted. `ST/test_gate_surface.py::test_ga2_a_gate_reads_a_declared_name_of_its_block`
  pins "this Fusion does not declare 'conf'": it is an O13 rewording site at the swap.
- **Commits:** `589d257e6` test (RED), `6dc0f8adf` fix (GREEN), this ledger commit.
- **Tests:** 430 in the 12 surface test files; full SDK suite 5399 passed, 33 skipped.
- **Gates:** `run_gates.py screamingface --base e4d44281c`: the append-only check lists only the
  owner-approved unit-1 files; with `--skip-append-only` ALL GATES GREEN.
  `run_gates.py repo --base e4d44281c` ALL GATES GREEN.

## Unit 5: narrow-compile

### Intent

Compile a block with narrow steps before its terminal: the internal reducer carries the narrow
steps in the private field `_narrow`, `_ReducerPlan.narrow` holds their plans, and the combine spec
gets the `narrow` list (narrow.md §2, §5, §6; lowering.md §2.2). `CH-12` goes away; `NR-C1` stays.

### Files (planned)

- Edit: `S/reducer.py` (`_ReducerPlan.narrow`, the carrier field, the full plan),
  `S/selection.py`, `S/judge.py`, `S/fields.py`, `S/blocks.py` (the carrier field),
  `S/_evaluation/combine_spec.py` (narrow §5 SDK places), `S/_evaluation/reducer_signals.py`
  (one call per key), `S/_evaluation/candidate.py` (the full plan), `S/fusion.py` (checks on every
  step), `S/url4.py` (a narrow spec rebuilds and recompiles), `S/_surface/chain.py` (drop `CH-12`),
  `S/_surface/lowering.py` (the narrow lowering).
- New tests: `ST/test_narrow_compile.py`, `ST/test_narrow_contract_fixtures.py`,
  `ET/test_combine_narrow_run.py`. New fixtures: `ET/data/combine_contract/
  narrow_filter_mean_candidate.url4`, `narrow_rank_vote_candidate.url4`.
- Edited unit 3–4 tests: the CH-12 refusals become passing chains.

### Rows

NC-1..NC-5.

### Outcome

- **Actual files:** `S/reducer.py` (`_ReducerPlan.narrow`, `Reducer._combine_plan`,
  `_with_narrow`, `_step_plans`, `_narrow_steps`, `_narrowed`, the carrier on `Vote`/`Median`/
  `Mean`), the carrier field on `Rank`/`Filter`/`Concat` (`S/selection.py`), `Judge`, `Pick`,
  `Reduce` (its `__eq__` compares the carrier), `S/_evaluation/combine_spec.py` (the `narrow`
  list, `accounting_signal` over every step, `_is_spec`/`_is_narrow`, `spec_operator_pairs`),
  `S/_evaluation/candidate.py` and `S/_evaluation/reducer_signals.py` (the full plan, one call per
  key), `S/fusion.py` (`_check_reads`, `_check_weight_source` and `_check_members` on every step),
  `S/url4.py` (a narrow spec rebuilds and must recompile; `to_python` refuses it until unit 6),
  `S/_surface/chain.py` (CH-12 removed), `S/_surface/lowering.py` (`block_node` lowers narrow).
  New tests `ST/test_narrow_compile.py` (25), `ST/test_narrow_contract_fixtures.py` (4),
  `ET/test_combine_narrow_run.py` (2); fixtures `narrow_filter_mean_candidate.url4`,
  `narrow_rank_vote_candidate.url4`. Edited unit 3–4 tests: the CH-12 refusals in
  `ST/test_chain_rules_steps.py` and `ST/test_gate_surface.py` now build.
- **Commits:** `9bee85e51` test (RED), `21531b5a6` feat (GREEN), `f2999fdc6` refactor, this
  ledger commit.
- **Gates:** `run_gates.py screamingface-engine --base e4d44281c` and `screamingface`: the
  append-only check lists only the owner-approved unit-1 files; with `--skip-append-only` ALL
  GATES GREEN (engine pyright needed `uv sync --frozen`). `run_gates.py repo --base e4d44281c` ALL
  GATES GREEN.
- **Deviations:**
  - The carrier is set by one helper, `reducer._narrowed`, which the lowering AND the url4 rebuild
    call (the spec says "only by the lowering"): a url4 with `narrow` must rebuild with its narrow
    steps, or the recompile byte check fails. `_narrowed` sets it on a copy, because the block's
    judge node is shared (it is the synthesizer of `ArgMax("score:judge")`).
  - `_ReducerPlan.narrow` holds the narrow steps' own `_ReducerPlan`s; `Reducer._combine_plan()`
    merges them, and every compile place reads it (not `_plan()`). The one-judge-call rule lives
    there (`_with_narrow`); `reducer_signals.py` asserts it.
  - A spec with `narrow` now always takes the url4 recompile check (`_PROVED_SPEC_KEYS`).
  - `Url4.to_python()` refuses a url4 with narrow steps ("their editable Python comes with the map,
    select, reduce surface"): today's classes have no spelling for them. Unit 6 replaces this.
  - The two RED NC-1 literals said `"cmp": ">"` (narrow.md §2 example); the SDK writes `"gt"` today,
    so the tests follow the wire. The rank fixture is `Rank(2, by="score:judge") >>
    Vote(weights="score:judge")`: it matches the `judge_rank_weighted_vote` contract case and runs
    NC-3 (one judge call, two readers) in the Engine.
- **Gap (spec silent):** before the swap, `Judge >> <narrow step that reads the judge> >>
  ArgMin("score:judge")` is refused: ArgMin's judge writes the `order=min` template and the
  narrow step's judge does not, so they are two different calls under one key. It works after the
  neutral `@2` template (unit 7).

### Fix round (unit 5 review: ACCEPT WITH FIXES)

- **Fixed:** (1) `Judge.__eq__` reads `_narrow`, so equal values compile to equal bytes; a
  parametrized test covers all nine carrier classes (narrowed != plain, equal narrow ⇒ equal),
  plus the `Judge >> Filter >> ArgMax("score:judge")` case. (2) `reducer._narrowed` is the one
  gate of the carrier for the lowering and the url4 rebuild: at most `MAX_NARROW_STEPS` items
  (NR-S1; one constant, now in `S/reducer.py`, read by `S/combine_evidence.py` and
  `S/_surface/chain.py`), no main step that makes its own call over every member (NR-C1:
  `Reducer._whole_context_call`, set by a label `Judge` and a `Vote` whose gate has a model
  fallback), Rank and Filter only. A hand-edited url4 with 5 items, a label judge or a
  model-fallback gate is refused on the rebuild ("cannot rebuild", the rule as its cause);
  `Merge` cannot carry (confirmed by a test). (3) One table `_NARROW_SELECTS` in `S/reducer.py`;
  `_NARROW_REDUCERS` is derived from it. (4) One idiom: `Reducer._carries_narrow` (ClassVar).
  (5) `ArgMin("score:judge")` after a narrow step that reads the judge is refused in the lowering
  with 'sf.ArgMin("score:judge") cannot follow a narrow step that reads score:judge until the
  neutral judge template' (exact test). **Unit 7 lifts this rule** (the `@2` template makes the
  two judge calls one) **and adds a test row** that the chain then compiles with one judge call.
  (6) NC-5 compares the whole `combine` record with the contract case (one named override for
  the rank fixture: the SDK weighted vote selects with `max_weight_holder@1`); a new fixture
  `narrow_judge_rank_vote_candidate.url4` (`Judge >> Rank(by="score:judge") >> Vote()`) runs a
  judge that only a narrow step reads. Nits: the `_JUDGE_KEY` constant; `_PROVED_SPEC_KEYS` in
  the url4 header; no `_carrying` wrapper (`_narrowed` returns the reducer for no steps); the
  carrier comment once, on `Reducer`; the ArgMax test renamed; the recompile comment says that an
  operator error in a narrow spec shows as the recompile metadata error.
- **Commits:** `56dc5430d` test (RED), `f2e4bd7a7` fix (GREEN), this ledger commit.
- **Tests:** `ST/test_narrow_compile.py` 41, `ST/test_narrow_contract_fixtures.py` 6,
  `ET/test_combine_narrow_run.py` 3; full SDK suite 5417 passed, 33 skipped.
- **Gates:** `run_gates.py screamingface-engine --base e4d44281c` and `screamingface`: the
  append-only check lists only the owner-approved unit-1 files; with `--skip-append-only` ALL
  GATES GREEN (engine pyright needed `uv sync --frozen` again). `run_gates.py repo --base
  e4d44281c` ALL GATES GREEN.

## Unit 6: rebuild-display

### Intent

Rebuild a url4 as a chain of the new surface, with code that names the steps through the alias
`sf`; give the chains and steps a `>>` repr; add the block and chain cards; show the narrow steps
in the Combine section and the run summary (rebuild-display §1–§4). `Url4.to_python()`, today's
cards and the report labels stay until the swap.

### Files (planned)

- New: `S/_surface/rebuild.py` (url4 → chain), `S/_surface/render.py` (the one renderer of `repr`
  and the rebuilt code). Edit: `S/url4.py` (one decode helper shared by `to_python` and the
  rebuild), `S/_surface/*.py` (repr through the renderer, `_repr_html_`), `S/_surface/__init__.py`
  (the names the rebuilt code reads), `S/_ui/cards.py` (block and chain cards, a chain member),
  `S/_ui/combine_view.py` (narrow chips, left-out cells, summary counts).
- New tests: `ST/test_surface_rebuild.py`, `ST/test_surface_cards.py`, `ST/test_narrow_display.py`;
  goldens `ST/data/surface_cards/*.html`.

### Rows

RB-1, RB-3, DS-1, DS-2.

### Outcome

- **Actual files:** new `S/_surface/rebuild.py` (`rebuild(url4) -> Rebuilt(value, python)`,
  `surface_value`), new `S/_surface/render.py` (the one renderer of `repr` and of the rebuilt code);
  `S/url4.py` (`_decode_candidate`, the one decode path of `to_python` and the rebuild, and
  `_replay_check_surface`); `S/_surface/chain.py` (`repr` through the renderer, `_repr_html_`),
  the step modules (`repr=False`, so the renderer is the repr), `S/_surface/__init__.py` (`Model`,
  `CorrectiveLoop`, `SelfCorrective` and the signal sources, the names the rebuilt code reads);
  `S/_ui/cards.py` (`block_card_html`, `chain_card_html`, a chain member is a "nested chain");
  `S/_ui/combine_view.py` (narrow chips, left-out status cells, per-step summary counts). New tests
  `ST/test_surface_rebuild.py` (96), `ST/test_surface_cards.py` (8), `ST/test_narrow_display.py`
  (10); goldens `ST/data/surface_cards/*.html`.
- **Commits:** `4c81994a3` test (RED), `ed6e76d12` feat (GREEN), this ledger commit.
- **Tests:** full SDK suite 5531 passed, 33 skipped.
- **Gates:** `run_gates.py screamingface --base e4d44281c`: the append-only check lists only the
  owner-approved unit-1 files; with `--skip-append-only` ALL GATES GREEN. `run_gates.py repo --base
  e4d44281c` ALL GATES GREEN. The Engine is not touched.
- **Deviations:**
  - U5a decision: the rebuild reuses today's decode and `_recipe_from_topology`, then converts
    today's values (one converter, `surface_value`). Its byte check is `_require_recompiles` on the
    converted chain; a mismatch is "URL4 Candidate has a recipe this SDK version cannot rebuild",
    and a value with no new-surface form is today's "has a {name} spec this SDK version cannot
    rebuild" (a field pick, `Rank(by_field=)`).
  - A `ReduceNode` field extract with only a path rebuilds as `over="field:<path>"` (the S4
    spelling), not `over=sf.Extract("field", path=...)`; any other extract rebuilds as
    `sf.Extract(...)`. Both compile to the same bytes; the string is the form the user writes.
  - A Model whose prompt is the default of its compile role (answer prompt as a member or a later
    stage, synthesis prompt in a Fusion synthesizer slot) rebuilds with no prompt, as `to_python`
    writes it; inside a corrective loop the prompts are kept as they are.
  - The rebuilt code is one line, `candidate = <expr>`, with no import line, so a test runs it in
    `{"sf": screamingface._surface}`. It holds no benchmark call for a linked url4.
  - U5d: `Url4.to_python()` keeps its narrow refusal: today's classes have no spelling for a narrow
    step. The swap switches `to_python` to `rebuild` and lifts it.
  - The card goldens hold the card without the shared `CARD_STYLE` sheet (the test checks the
    prefix), so a house CSS change does not move them.
  - The judge rows (S10, S11, the README judge examples) also round-trip before the swap, because
    the new surface still compiles today's `@1` judge template; RB-1b/RB-2 stay unit 7.

### Fix round (unit 6 review: ACCEPT WITH FIXES)

- **Fixed (structural, 1):** the compile role of a model call comes from the url4 topology, not
  from a copy of the compiler's rules. `_recipe_from_topology(..., editable=True)` (with
  `_fusion_from_topology` and `_synthesizer_from_topology`) gives a model call whose prompt is the
  default of its topology role (`_role_default_prompt`, also used by `_render_model`) no prompt;
  the rebuild reads it, and the `synthesis` argument is gone from every converter. A corrective
  loop rebuilds its Models as `to_python` does (test against today's `to_python` for three loop
  url4s). The url4 recompile check keeps `editable=False`, so `to_python` is byte-identical.
- **Fixed:** (2) an unknown extract op is "cannot rebuild"; (3) a Median/Mean `select=` has no
  pin; (4) `render.model_options` is the one "Model has no options" check; (5) the renderer reads
  every default from the constructors (`inspect.signature`) and the Vote normalizer from
  `steps._vote_normalizer`; (6) leaves give their own `_python()` text, and `render.dispatch` is the
  one dispatch idiom of the renderer and the rebuild; (7) only `_Unexpressible` (raised by
  `_built`, the constructor wrapper, and by the D3 refusals) becomes "cannot rebuild", and the byte
  check is `url4._recompiles` (a compare; a compile error raises as itself); (8) a byte-mismatch
  test; (9) a golden of the Combine section with two narrow steps
  (`ST/data/narrow_display/combine_narrow_no_signal.html`); (12) an open chain card shows its open
  block (`open fanout block`) with its steps; nits: no dead `stage.optional` branch,
  `combine_view._narrow_records`, one `_narrow_word` per record, no "None" reason, `_block_of`
  typed `_Block`, no empty comment, `surface_value` out of `__all__`, and `Filter` keeps `over=`
  as written (`filter_extract` gives its `sf.Extract` at the lowering; the unit-3 test that held
  the two forms equal now checks that both forms lower alike).
- **Commits:** `1af78de80` test (RED), `9b34d1beb` fix (GREEN), this ledger commit.
- **Tests:** `ST/test_surface_rebuild.py` 102, `ST/test_surface_cards.py` 10,
  `ST/test_narrow_display.py` 11; full SDK suite 5540 passed, 33 skipped.
- **Gates:** `run_gates.py screamingface --base e4d44281c`: the append-only check lists only the
  owner-approved unit-1 files; with `--skip-append-only` ALL GATES GREEN. `run_gates.py repo --base
  e4d44281c` ALL GATES GREEN.
- **Unit 7 note:** when `to_python` switches to `rebuild`, the code string of a linked url4 must
  add the evaluation call (today's `_evaluation_call`) and the `import screamingface as sf` line,
  and a large candidate needs multi-line output (today's renderer writes one line).

## Unit 7: swap — steps 7a–7c

### Intent

Steps 7a–7c of [prd/swap.md](../spec/2026-10-20-e4b-mapreduce-surface/prd/swap.md): the Node
rename, `judge-template@2`, and the prep for the test migration (codemod, `>>` on `Recipe`, the gate
references on `Signal`). 7d–7h are not in this round.

### Outcome

- **7a** (`8401ed7f3`): the 12 classes of swap §2 are `FusionNode` … `ReduceNode`, renamed by `ast`
  spans (Name, ClassDef, ImportFrom alias, and the type text of `cast("X", ...)`), so no string or
  docstring changed. Each defining module keeps `Fusion = FusionNode` (etc.) until 7e. A reducer
  message reads `_public_name` (a ClassVar on the 10 Reducer nodes; `Reducer.__init_subclass__`
  gives any other reducer, such as a test fixture, its class name). No byte, message or test
  change: SDK suite 5540 passed, as before.
  - **Deviation:** the annotations in the 4 `__init__` signatures that the public surface snapshot
    records (`Rank`, `Filter`, `Gate`, `Vote`: `Judge | None`, `Gate | None`) keep the alias names,
    with an alias import, so the snapshot does not move before 7e (7e regenerates it).
  - **Spec gap:** `S/fusion.py:277` reads `type(needs[0]).__name__` of a `Logprob`/`Entropy`
    signal source, not of a node, so it needs no `_public_name`; only 3 of the 4 listed sites read a
    node class. `_public_name` is on the Reducer nodes only (no site reads it on `FusionNode` or
    `GateNode`).
- **7b** (`3a0b7d573` RED, `9a1486bb8` GREEN, `08957905f` pinned): `LABEL_TEMPLATE_ID` (`@1`),
  `SCORES_TEMPLATE_ID` (`@2`, "Score each member as the rubric says."); `JudgeNode.order` only
  selects the select step; `judge_intent` lost its `order` keyword; `_parts`/`judge_from_signals`
  accept `@2` scores and `@1` label and refuse `@1` scores and `@3` ("URL4 Candidate has an
  unsupported judge call"). `_refuse_min_order_judge` and the U5c `_check_judge_order` are gone.
  New `ST/test_judge_template_v2.py` (TM-1, 8 tests, with the U5c row). Regenerated through the
  writer functions, and `git diff --stat` on data showed exactly these: 4 goldens (345, 387, 397,
  514) and 8 Engine fixtures (swap §3 list); word diff = only the first line and the last sentence.
  - **Pinned test edits (owner list, MG-3):** as listed in swap §1 7b: `ST/test_filter_judge.py`
    (:66, :68, :84 literals; FJ-D2 test renamed `test_sdk_filter_refuses_a_label_judge`, its 4
    min-judge rows deleted), `ST/test_judge_order.py` (JO-3 literals; JO-2 rewritten as
    `test_sdk_judge_order_min_writes_the_neutral_template`; `test_rank_vote_and_filter_refuse_a_min_order_judge`
    deleted; the 2 tamper rows of `test_url4_round_trip_rebuilds_an_order_min_judge_and_judge_block`
    deleted; JO-D4 literals; module docstring), `ST/test_judge_quorum.py:52`,
    `ST/test_judge_reducer.py` (the id import, the prefix loop, :123), Engine
    `test_sdk_judge_order_contracts.py`, `test_sdk_candidate_contracts.py`,
    `test_sdk_filter_judge_contract.py`, `test_sdk_quorum_contracts.py` (the `@1` literals).
  - **Spec gaps (forced by the template, not in the §1 7b list):** sha256/length pins of judge
    url4s: `ST/test_judge_link_trace.py` (6 shas), `ST/test_judge_writer_warning.py` (sha, length
    2558 → 2557), `ST/test_selection_input_bytes.py` (`_RANKED_SHA256`, the 514 golden),
    `ST/test_signal_recipe_fixtures.py` (S10, S11 max; its "Never update" comment now names the
    exception); and `ST/test_narrow_compile.py::test_nc3_an_argmin_by_the_judge_after_a_judge_narrow_step_is_refused`
    deleted (it pinned the U5c refusal that 7b lifts).
  - **Why the tamper rows go:** with `@2`, a min and a max judge make the same call, so a url4
    whose select step is swapped from `best_holder{order:min}` to `max_score` is a valid max
    judge, and there is no order tail to remove.
- **7c** (`b65f0164c` RED, `047b0dbc8` GREEN, `ef22360ee` RED, `9d1b36599` GREEN): `.chosen()` /
  `.mean()` on `_signals.Signal` (lazy `GateRef`; SI-1 kept); `SignalRef`, `refs._plain`,
  `plain_comparison` deleted; `sx.signal is sf.signal`. `Recipe.__rshift__/__rrshift__` (lazy
  chain import); `Step` keeps its own pair; `_Chainable` deleted; `.then` stays. New
  `ST/test_swap_prep.py` (6). `packages/screamingface/scripts/migrate_surface.py`: R1–R13,
  `--to sx|sf`, `--audit <base> [--allow FILE]` (per test function: assert / pytest.raises+warns /
  assert-helper counts, each category compared), the `file:line: rule: reason` report (also for
  an old class read as a value and `.synthesizer` reads). `ST/test_migrate_surface.py` (MG-1, 29).
  Not applied to any test. A dry run over the 422 test files: 117 would change, 0 crashes, every
  output parses, the audit finds no lost assertion; 87 files have at least one report line.
  - **Codemod choices (spec silent):** a scores `sf.Judge` alone becomes `sx.Judge(...)` (its order
    is read where a synthesizer names it), a label one `sx.JudgePick(...)`; a reader that names its
    judge hoists the name (R7h); a site that fails keeps its whole text, inner calls included; R9
    writes `sx.signal(...)` as the R9 row says; `sf.Reduce(op, mode)` is a hand case.
- **Tests:** SDK 5613 collected; the full suite green in every gate run. Engine suite green.
- **Gates (after 7b and at the end):** `run_gates.py screamingface-engine --base e4d44281c`: the
  append-only check flags the owner-approved unit-1 files (2 schemas, `test_combine_consistency_words.py`,
  `test_combine_evidence_words.py`) plus the 7b pinned edits (6 fixtures that existed at the base,
  the 4 `test_sdk_*` files); with `--skip-append-only` ALL GATES GREEN (pyright needed
  `uv sync --frozen` once: the inspect pitfall). `run_gates.py screamingface --base e4d44281c`:
  flags the unit-1 files (`answer.v1.json`, `public_surface_snapshot.json`, `test_band_words.py`,
  `test_evidence_words.py`, `test_gate_words.py`, `test_pick_output.py`) plus the 7b goldens (4)
  and pinned tests (`test_filter_judge.py`, `test_judge_link_trace.py`, `test_judge_order.py`,
  `test_judge_quorum.py`, `test_judge_reducer.py`, `test_judge_writer_warning.py`,
  `test_selection_input_bytes.py`, `test_signal_recipe_fixtures.py`); with `--skip-append-only` ALL
  GATES GREEN. `run_gates.py repo --base e4d44281c` ALL GATES GREEN.
- **7d-0** (`729006ec4`, `fe0f845f2`, `e56ec10e2`): D7-5 and D7-4.
  - `ST/data/surface_parity.json` (70 rows, `{"<test file>:<case>": url4}`): written once from the
    today forms at `0838f2f17` (judge rows already `@2`), each row compiled the way its test
    compiled it (`flow_operators`, `compile_example`, `compile_evaluation`). Rows:
    `surface_parity:` S1–S4′, S5–S11′, the 41 doc slugs (39 equal their goldens; 418 and 528 hold
    today's `by_signal` rewrite); `gate_surface:` 7; `lowering:` 2; `judge_step:` 1;
    `narrow_compile:` 3; `narrow_steps:` 2; `surface_rebuild:` 3 (field pick, rank by field: the
    D7-8 forms that no internal value can build after 7f; and the vote for `to_python`).
  - New `ST/_nodes.py`: `fusion_node(members, reducer, *, name, signals, quorum, optional)`, the 12
    `Node` class re-exports, and `frozen_url4(row)`.
  - The 16 files of D7-5 (15 edited; `test_narrow_contract_fixtures.py` builds no today form): a
    parity row compares the new form with `frozen_url4(...)`; an equality row (`lower(chain) ==
    ...`, `isinstance`, `_carriers`) names the nodes. Done by an `ast`-span rewrite
    (`sf.X` → `XNode`, `sf.Fusion(m, synthesizer=r)` → `fusion_node(m, r)`), no string touched.
    `migrate_surface.py --audit 0838f2f17`: no lost assertion; 588 tests, as before.
  - **Group D (pinned, owner list MG-3):** only the `sf.Fusion` calls around a fixture reducer
    (`FixtureVote`, `FixtureJudgeish`, the local `Bogus`) moved to `fusion_node`, positional
    reducer; no other line. Files and functions: `_reducer_fixtures.py` (`reducer_fusion`);
    `test_combine_evidence.py` (`test_two_reducers_keep_separate_evidence`); `test_duplicate_members_warning.py`
    (`test_duplicate_members_in_reducer_fusion_warn`,
    `test_three_equal_members_name_all_three_positions`, `test_two_groups_of_duplicates_warn_once_each`, the
    `test_distinct_members_and_non_reducer_fusions_do_not_warn` params `samples`, `prompts`,
    `params`, `nested-fusions` (outer only), `_duplicate_loop`, `_pair`);
    `test_engine_url4_contract_fixtures.py` (`two_reducers_url4`, `_samples_url4`); `test_fixed_seed_sitting_warning.py` (`_samples_fusion`,
    `_unseeded_fusion`); `test_reducer_fusion_quorum.py` (`test_a_quorum_reducer_reads_a_broadcast_panel`,
    `test_a_reducer_with_every_member_required_has_no_panel`,
    `test_an_all_optional_fusion_without_a_quorum_still_needs_every_member`,
    `test_a_quorum_reducer_round_trips_through_url4`);
    `test_reducer_slot.py` (`test_fusion_accepts_a_reducer_in_the_synthesizer_slot` :116, :126,
    :128, :130; `test_reducer_without_catalog_fails_and_bad_specs_are_refused` :209, :217;
    `test_reducer_fusion_compiles_inside_pipeline_fusion_and_corrective_loop` :272);
    `test_reducer_url4_round_trip.py` (`_recipes`,
    `test_to_python_and_corrective_replay_use_the_reducer_registry`); `test_samples_preflight.py` (`_candidate`);
    `test_url4_replay_fixed_seed_warning.py` (`_samples_fusion`,
    `test_no_warning_when_no_call_sets_a_seed`). The other 12 of the 22 only import
    helpers (`engine_operators`, `evidence_wire`, `fixture_operators`, `reducer_fusion`, ...):
    no edit. Audit vs `fe0f845f2`: no lost assertion; the 21 test files: 371 passed.
  - **Left for 7d-n (hand cases, not "around a fixture reducer"):** `test_reducer_slot.py` :75
    (a reducer as a member: `_misplaced`) and :133 (`synthesizer=3` message);
    `test_engine_url4_contract_fixtures.py::test_block_form_samples_vote_compiles_to_the_engine_fixture`
    passes public `sf.Reduce`/`sf.Vote` into `_samples_url4` (now `fusion_node`): the codemod must
    keep them nodes; the `-> sf.Fusion` / `fusion: sf.Fusion` annotations in group D;
    `test_lowering.py` LO-0 rows still read `_fusion_doc_examples` and `_GOLDEN` (today values
    from helpers): they meet the codemod of those helpers.
  - **Gates:** `run_gates.py screamingface --base e4d44281c`: the append-only check flags the
    earlier owner-pending files (unit 1 and 7b, as listed above) plus the 10 group D files of
    7d-0; with `--skip-append-only` ALL GATES GREEN; `run_gates.py repo --base e4d44281c` ALL
    GATES GREEN.

### Fix round (7a–7c review: ACCEPT WITH FIXES)

- **Commits:** `c5340f442` test (RED), `5804e51b8` fix (src: #8, #12), `960890e50` fix
  (codemod), this spec erratum and ledger commit.
- **Fixed (codemod, `scripts/migrate_surface.py`):** (1) a Vote whose extract was
  `sf.Extract("field", path=p)` writes `over="field:p", normalize=None` (MG-1 byte rows: plurality,
  weighted, a plurality `sf.Extract`, a median mode, a named Vote compile to the same url4). (2) A
  name resolves in its own scope (innermost function that binds it, else the module); a parameter
  or a name bound twice is a hand case (row: `def _fusion(synthesizer): sf.Fusion(M,
  synthesizer=synthesizer)` next to a module `synthesizer = sf.Vote()`). **Deviation:** the review
  asked for module-level names only; a function local with one assignment still resolves, in its
  own scope, because the rewritten text keeps that same name in that same scope (row
  `scope-local`). (3) A scores judge alone with `order="min"`, and a synthesizer name for one, is a
  hand case. (4) `Reduce("judge", judge=J)` keeps `J`'s name (shared `_judge_parts`) and refuses
  other options; a signal pick refuses other options. (5) A comment inside a rewritten call that
  the new text would drop is a hand case (a trailing `# type: ignore` after the call is outside the
  span and stays). (6) A field read on a value the run rewrote is reported (`f.members`,
  `(...).synthesizer`; the global `.synthesizer` report is gone); annotations are not reported; a
  reducer value outside a synthesizer slot in a file that imports `tests/_nodes.py` is a hand case
  (`test_block_form_samples_vote_compiles_to_the_engine_fixture` :187, :188 are reported). (7) The
  audit counts every function (helpers too), `match=` keywords and `parametrize` cases. (9)
  `Reduce(op, mode)` maps the Median/Mean mode to `select=`. (10) TM-1 row: `Judge >> Rank >>
  ArgMin` is one judge call. (11) R12 parenthesizes a looser operand. (13) `--check`.
- **Fixed (src):** (8) `selection.py`/`reducer.py`: `RankNode(by=)`, `VoteNode(judge=)`,
  `FilterNode(judge=)` hold a min-order judge as the max judge (`_reader_judge`), so equal bytes
  are equal values (TM-1 row, with the `Reduce("top_k")` block). (12) One `_Chainable` mixin in
  `recipe.py` (Recipe and Step), the duplicate pair in `chain.py` is gone.
- **Spec erratum:** swap.md §4 R10 row (Vote target writes `normalize=None`, the mode map) and the
  rule changes 2–9.
- **`--check` over `tests/` (HEAD `960890e50`):** 102 files would change, 548 report lines in 61
  files: attr 132, R1 128, value 105, R7h 59, R9 37, args 24, R10 18, R2 12, R7 9, R4 8, R5 6,
  R8 5, nodes 2, comment 2, R6 1. Audit of each rewritten file against its own text: no lost
  assertion (0 problems).
- **Tests:** `ST/test_migrate_surface.py` 51, `ST/test_judge_template_v2.py` 10; full SDK suite
  5605 passed, 33 skipped. Engine `test_sdk_*` + `test_combine_*` 1683 passed.
- **Gates:** `run_gates.py screamingface --base e4d44281c`: the append-only check flags the unit-1
  files, the 7b pinned files and the 7d-0 group D files (`_reducer_fixtures.py`,
  `test_combine_evidence.py`, `test_duplicate_members_warning.py`,
  `test_engine_url4_contract_fixtures.py`, `test_fixed_seed_sitting_warning.py`,
  `test_reducer_fusion_quorum.py`, `test_reducer_slot.py`, `test_reducer_url4_round_trip.py`,
  `test_samples_preflight.py`, `test_url4_replay_fixed_seed_warning.py`), nothing of this round;
  with `--skip-append-only` ALL GATES GREEN. `run_gates.py repo --base e4d44281c` ALL GATES GREEN.

## Unit 7: swap — step 7d-1 (helpers)

- **Commits:** `5dbc11896` chore (the codemod sorts the imports it adds), `536c7d76a` test (the
  helpers and their dependents), `619c8443e` test (the pinned field-pick bytes, alone),
  `259256feb` chore (the codemod drops an unused `sf` import), this ledger commit. Pre-batch
  commit: `fafb4a95d`.
- **Codemod `--to sx`:** `tests/_combine_recipes.py`, `_signal_recipes.py`,
  `_fusion_doc_examples.py`, `paid/_panel.py`, `e2e/harness/reducer_golden.py`, and the fixture
  writer `test_pick_output_url4_fixtures.py` (it builds `recipe_s5_pick_output.url4`, so the
  S5 pick-output bytes move with it). `_combine_contract.py`, the other `tests/_*.py`,
  `e2e/harness/*` and `e2e/fixtures/*` had no old call or only hand cases.
- **Hand cases:** `_combine_flow_fixtures.judge_fusion` (`**kw` into `sf.Judge`): a `JudgePick`, or
  a `Judge` and `ArgMax`/`ArgMin` by `order=`; `_combine_recipes` S10/S11 (a judge from a
  function) and the `_judge() -> sx.Judge` annotation; `e2e/harness/goldens.py`,
  `e2e/fixtures/slice_snapshot.py` (a route synthesizer from a model field);
  `e2e/harness/fusion_golden.py` `build` (Fanout >> Synthesize) and `build_block` (= `build`: the
  context block form has one spelling since R11); the lazy `sx` import in `paid/_panel.py` and
  `reducer_golden.py` (free tests never import the SDK at module load).
- **Dependents fixed (pinned):** `e2e/test_fusion_golden_contracts.py`,
  `e2e/test_reducer_golden_contracts.py`, `e2e/test_reducer_lane_contracts.py`,
  `e2e/test_report_tape.py`, `paid/test_panel_models.py` read the chain steps (`steps[0].members`,
  `steps[1]`, `Synthesize.model`); `test_fusion_recipe.py` (group F, deleted in 7f) and
  `test_lowering.py` LO-0 lower the doc examples first (LO-0 now proves the identity on the
  lowered value).
- **Spec gap, README:** `test_combine_recipes_readme.py` compiles the README "Combine recipes"
  code against the builders. The README S5/S7 code (`sf.Pick("confidence", order="max")`,
  `sf.Rank(k=2, by_field="confidence")`) compiles to the old field-pick bytes, so it now spells
  today's by_signal form (`sf.Pick(by_signal=sf.signal("field:confidence"), ...)`,
  `sf.Rank(k=2, by_signal=...)`): two code lines, no prose. 7e moves the section.
- **Pinned data (own commit):** exactly 5 files regenerated through their writers (`git diff
  --stat`): `readme-418-pick-confidence.url4`, `readme-528-rank-by-field.url4`, Engine
  `recipe_s5.url4`, `recipe_s5_pick_output.url4`, `recipe_s7.url4`. S5 == S8 and S5 pick output
  == S8 pick output byte for byte. `surface_parity.json` rows 418 and 528 equal the new goldens.
  (Its S5/S7 rows are the notebook forms with other members and do not equal the Engine
  fixtures; not part of this check.)
- **Forced test edits (pinned):** Engine `test_combine_recipes.py::test_recipe_s5_plain_text_member_is_not_picked`
  (`fail`/`not_json` → `excluded`/`no_signal`, as S8); S7 (:126) and
  `test_combine_empty_cut_envelope.py:187` stayed green, no edit.
  `test_signal_recipe_fixtures.py`: the S5, S5 pick output, S7 sha256 pins (spec gap, as in 7b).
- **Audit** `--audit fafb4a95d` over every touched SDK and Engine test file: no lost assertion.
- **Tests:** SDK suite green (gate); Engine unit suite green (gate).
- **Batches:** `scratchpad/7d-batches.json`: 127 remaining files (94 change under the codemod,
  536 report lines), 4 groups of weight 166/166/166/165 (report lines + files), import-linked
  files kept together (group 1 holds one 38-file component around `test_client_run.py`). Excluded:
  the done helpers, `tests/_nodes.py`, `tests/test_migrate_surface.py`, the 5 README-coupled tests
  (7e). Each group lists its hand files and reasons, the files with old tokens but no codemod
  change, and the files whose `to_python` strings wait for 7e.
- **Gates:** `run_gates.py screamingface-engine --base e4d44281c`: append-only flags the unit-1
  files (2 schemas, `test_combine_consistency_words.py`, `test_combine_evidence_words.py`), the 7b
  files (6 fixtures, 4 `test_sdk_*`), and new: `recipe_s5.url4`, `recipe_s5_pick_output.url4`,
  `recipe_s7.url4`, `test_combine_recipes.py`; with `--skip-append-only` ALL GATES GREEN.
  `run_gates.py screamingface`: the earlier list plus new: `_combine_flow_fixtures.py`,
  `_combine_recipes.py`, `_fusion_doc_examples.py`, `_signal_recipes.py`, the 2 goldens,
  `e2e/fixtures/slice_snapshot.py`, `e2e/harness/{fusion_golden,goldens,reducer_golden}.py`,
  `e2e/test_{fusion_golden_contracts,reducer_golden_contracts,reducer_lane_contracts,report_tape}.py`,
  `paid/_panel.py`, `paid/test_panel_models.py`, `test_fusion_recipe.py`,
  `test_pick_output_url4_fixtures.py`; with `--skip-append-only` ALL GATES GREEN.
  `run_gates.py repo` ALL GATES GREEN.

### 7d review fixes

- **Commits:** `309f59b4e` fix (ArgMax/ArgMin unhashable), `fd2e5a3df` test (the context block
  subjects as group F rows), `3f726a87c` test (the minor rows), this ledger commit.
- **Src (finding 5):** `sx.ArgMax`/`sx.ArgMin` set `__hash__ = None` again (a frozen dataclass
  subclass adds it back), so every step is unhashable. `test_pick_by_signal` checks `hash(pick)`
  on the surface value; the AIDEV-NOTE is gone.
- **Group F additions (deleted in 7f with the context rewrite, D7-8):**
  `test_fusion_block_quorum.py` (whole file: the block side is `fusion_node(...,
  ReduceNode("context"), quorum=…)` in a Pipeline with the writer stage);
  `e2e/harness/fusion_golden.py::FusionLaneSpec.build_block` (the same node form, so the FR-2
  check of `fusion_lane.py::_replay_recipe` and the `"block"` entry of `FORMS` in
  `e2e/test_fusion_replay.py` can fail again; `fusion_lane.py` puts `tests/` on `sys.path` for
  `_nodes`); `test_filter.py::test_filter_as_last_stage_is_rejected` rows 2–3 (a Filter
  `fusion_node` as a Fanout member and as a loop judge, the pre-swap match strings; the surface
  `_OPEN_BLOCK` rows stay); `test_judge_writer_warning_stages.py` `context-then-writer` (the
  pre-swap node subject, stages 3 and 4) and `context-then-judge`. The surface subject of the
  stage-number row stays as the new row `chain-then-judge` (stages 2 and 3), and the evaluation
  compile test reads it.
- **Other rows:** `test_judge_writer_warning.py[middle-stage]` pins "stages 2 and 3" (a judge
  block in stage 2, the same model in stage 3); `test_weighted_median.py` pins the exact "does
  not declare" refusal of `sx.Fanout(...) >> sx.Median(weights="abc")`;
  `test_benchmark_answer_rule.py` notes why the `benchmark@1` Median message changed;
  `test_fusion_quorum.py::test_optional_members_flag_is_removed` also checks the `sx.Fanout`
  signature and `Pipeline(optional=True)`; `test_lowering.py` LO-0 adds the identity on 5
  internal node values; `test_band_api.py` docstring names `sf.Gate(..., abstain_if=...)`.
- **Gates:** `run_gates.py screamingface --base e4d44281c --skip-append-only` ALL GATES GREEN;
  `run_gates.py repo` ALL GATES GREEN.

## Unit 7: swap — step 7e

- **Commits:** `f118fea33` feat (src swap), `1f1e93bbb` test (codemod R13 output), `8127d0848` test
  (group F deletions, owner list), `f830a1140` fix (rebuild: a selection whose writer is another
  selection), `42f4e18f8` feat (`sf.Fusion` shortcut), `d5fd9b97c` docs (spec A4 revised),
  `ed7cfd5a7` test (hand fixes), `bae347925` docs (README D7-6 + group H literals), `4fc6b26c1`
  test (public surface snapshot), `4c6444cfb` test (comments), this ledger commit.
- **Src swap:** `sf.*` exports the `_surface` names (`Fanout`, `Synthesize`, `Judge`, `JudgePick`,
  `Rank`, `Filter`, `Concat`, `Vote`, `Median`, `Mean`, `ArgMax`, `ArgMin`, `First`, `Merge`,
  `Gate`, `agreement`, `field`); `sf.Pick`, `sf.Reduce`, the 7a module aliases and `Recipe.then`
  are gone; `screamingface._surface` exports nothing. D7-2: the chain class is the one
  `sf.Pipeline` (`S/pipeline.py` re-exports it); the public `stages` field is gone and the compile,
  the cards, the judge-writer check, `fusion_recipe.py` and the rebuild read `_stage_values()`; the
  lowering of a chain with no block is the chain itself (LO-0), else a `Pipeline` of nodes.
  `Url4.to_python()` = `import screamingface as sf`, blank line, the chain code
  (`render.code`), and the linked `sf.evaluate(...)` lines; U5d lifted. **Multi-line output:** a
  top-level chain longer than 100 characters shows one stage per line (`candidate = (` /
  `    >> step`), a named or optional chain one step per line in `sf.Pipeline([...])`;
  `Rebuilt.python` stays one line.
- **Owner decision 2026-10-20 (A4 revised):** `sf.Fusion` stays public as a function in
  `S/_surface/fusion.py` that returns `sf.Fanout(members, signals=, quorum=, name=, prompt=) >> S`
  (a step as it is, a route/Model/recipe as `sf.Synthesize(...)`, `sf.Judge` refused, a narrow
  step leaves the chain open, `optional=True` → `sf.Pipeline([chain], optional=True)`). New
  `ST/test_fusion_shortcut.py` (23 rows: equality and bytes per kind, frozen S1–S3, the vote and
  the nested docs rows, pass-through, optional, open chain, the refusal, the signature). Spec:
  overview A4 and §1/§2, surface §3b and §10, swap 7e. **7g note:** MSG-1's forbidden list must
  drop `sf\.Fusion\b` (and the plain `\bFusion\b` where it names the shortcut).
- **Src fix (found by 7e):** `to_python()` of `Fanout >> Judge >> Rank >> Synthesize(Fanout >>
  Concat >> Synthesize(w))` failed (the rebuild took `Fusion(concat)` alone as the writer of the
  first selection: an open block). `rebuild._writer_of` groups a selection writer with its own
  writer. Covered by `test_rank_concat_url4_round_trip[two selections in a row]`.
- **Group F deletions (owner list, one commit `8127d0848`):**
  - `test_fusion_recipe.py` (whole file, 23 tests: `test_the_goldens_without_a_block_form_are_exactly_the_unnamed_pipeline_synthesizers`,
    `test_block_form_rewrites_to_fusion_and_compiles_byte_identical`, `test_rewrite_keeps_the_rest_of_the_pipeline`,
    `test_an_unnamed_pipeline_of_one_stage_is_that_stage_and_a_named_one_keeps_its_name`,
    `test_recipe_synthesizer_keeps_the_synthesis_flag_on_its_first_stage_only`, `test_named_pipeline_keeps_its_name_after_the_rewrite`,
    `test_nested_fusion_keeps_its_bindings_in_both_block_forms`, `test_every_recipe_without_a_context_block_is_returned_as_it_is`,
    `test_the_rewrite_is_idempotent`, `test_the_name_rule_infers_again_or_keeps_the_given_name`,
    `test_the_rewrite_reaches_loops_members_and_judges`, `test_the_rewrite_reaches_a_fusion_synthesizer_and_a_fusion_member`,
    `test_a_300_member_block_form_constructs_and_compiles_to_its_golden`, `test_only_the_context_block_skips_the_combine_exclusions`,
    `test_context_misuse_raises_before_spend`, `test_context_misuse_through_a_client_never_spends_or_fetches_operators`,
    `test_a_context_block_compiled_directly_is_the_misuse`, `test_the_synthesizer_operation_is_op_synthesis_n`,
    `test_recovered_fusion_prints_as_fusion`, `test_both_forms_report_the_same_candidate_name_in_a_scripted_run`,
    `test_a_cyclic_value_is_left_for_the_compiler_to_refuse`, `test_the_inferred_name_rule_lives_once_in_recipe_py`,
    `test_a_duplicate_name_made_by_the_rewrite_says_so_and_asks_for_a_name`): it read `Pipeline.stages`.
  - `test_blocks_reduce.py::test_equal_reduce_blocks_are_equal_and_hash_equal` (the `eval(_python())`
    loop over `_one_per_row()`); `test_reduce_to_python_round_trips` rows
    `Reduce('pick_field', field='score', order='min')`, `Reduce('top_k', k=2, by_field='score')`,
    `Reduce('top_k', k=2, by_field='a.b[0]', order='min')` (D7-8 forms: the rebuild refuses them).
  - `test_filter.py::test_reduce_filter_block_canonical_form_equality_and_hash` and
    `::test_filter_fields_repr_and_equality` (the `eval(_python())` loops).
  - `test_filter_judge.py::test_filter_block_and_repr_rebuild_the_judge_filter` (whole test).
  - `test_judge_blocks.py::test_judge_block_canonical_form_equality_and_hash` (the `eval` line).
  - `test_judge_order.py::test_public_surface_lists_judge_order` (JO#13: `Judge(returns=, order=)`).
  - `test_pick_merge_blocks.py::test_pick_and_merge_blocks_canonical_equality_hash_and_errors`
    (`_check_canonical_equality_and_hash`: the `eval(_python())` loop of 3 blocks).
  - `test_pick_output.py::test_url4_to_python_shows_the_output_of_each_pick` (the field order
    pair), `::test_block_forms_round_trip_to_the_named_pick_with_output` (the `pick_field` row),
    `::test_pick_field_block_python_round_trips` (whole test).
  - `test_rank_by_signal.py::test_rank_by_signal_fields_repr_and_equality` and
    `::test_reduce_top_k_block_canonical_form_equality_and_hash` (the `eval(_python())` loops).
  - `test_rank_concat_url4_round_trip.py::test_rank_and_concat_round_trip[rank by field]`,
    `::test_to_python_writes_the_reducers` (the by_field lines),
    `::test_the_recovered_reducers_equal_the_originals` (the 2 by_field shapes),
    `::test_a_followed_selection_inside_a_corrective_loop_round_trips` (the by_field solo loop).
  - Group F rows that still pass on the nodes stay for 7f (the by_field tamper rows of
    `test_rank_concat_url4_round_trip.py` now meet the refusal before the tamper, they still pass).
- **Hand fixes (pinned, owner list):** `_nodes.py` (`lowered()`), `_reducer_fixtures.py`,
  `e2e/test_fusion_golden_contracts.py`, `test_band_api.py`, `test_benchmark_extract_evaluation.py`,
  `test_blocks_reduce.py`, `test_chain_rules_steps.py`, `test_consistency_rebuild.py`,
  `test_consistency_sum_band.py`, `test_declared_signals.py`, `test_duplicate_members_warning.py`,
  `test_entropy_source.py`, `test_filter.py`, `test_filter_judge.py`, `test_gate_api.py`,
  `test_judge_order.py`, `test_judge_quorum.py`, `test_judge_reducer.py`,
  `test_judge_url4_round_trip.py`, `test_judge_weighted_vote.py`, `test_logprob_source.py`,
  `test_lowering.py`, `test_mean.py`, `test_migrate_surface.py`, `test_narrow_compile.py`,
  `test_narrow_steps.py`, `test_pick_by_signal.py`, `test_pick_merge_url4_round_trip.py`,
  `test_pick_output.py`, `test_pipeline_compilation.py`, `test_pipeline_recipes.py`,
  `test_rank_concat_url4_round_trip.py`, `test_reduce_numeric_select.py`,
  `test_reducer_url4_round_trip.py`, `test_signal_sum_api.py`, `test_signal_vote_replay.py`,
  `test_signal_weighted_vote.py`, `test_surface_rebuild.py`, `test_url4.py`, `test_verbalized.py`,
  `test_weighted_median.py`; group H `test_gate_docs.py`, `test_sum_band_docs.py`,
  `test_consistency_docs.py` (`test_combine_recipes_readme.py`, `test_signal_recipes_readme.py`
  pass unchanged); comments only: `test_judge_writer_warning.py`, `test_selection_compile_checks.py`,
  `unit/test_signal_key_conformance.py`; `public_surface_snapshot.json`.
- **Audit** (`migrate_surface.py --audit e0a6018c3`): every lower count is a group F row above or
  one of these rewrites: `test_declared_signals.py::test_fusion_signals_round_trip_through_url4_rebuild_and_repr`
  and `test_url4.py::test_fusion_url4_recovers_editable_topology_names_and_policy` /
  `::test_pipeline_url4_recovers_serial_and_nested_parallel_topology` (several `in` asserts → one
  list equality of the lines); `test_lowering.py::test_lo3_an_unlowered_chain_is_not_a_compile_kind`
  → `test_lo3_an_unlowered_chain_is_a_pipeline_kind_that_lowers_to_its_node` (D7-2);
  `test_narrow_compile.py::test_to_python_of_a_narrow_url4_names_the_new_surface` (raises → the
  output; U5d lifted); `test_reducer_url4_round_trip.py::test_to_python_and_corrective_replay_use_the_reducer_registry`
  (a registry reducer with no step: `to_python` now raises "cannot rebuild"); the two
  `test_surface_rebuild.py::test_rb3_today_*` rows → `test_rb3_to_python_is_the_import_and_the_rebuild_code`,
  `test_rb3_to_python_rebuilds_a_narrow_url4`, plus two layout rows. New: RB-1b
  (`test_rb1b_every_doc_example_round_trips_through_to_python`, `..._every_parity_row_...`,
  `..._a_judge_chain_comes_back_...`), RB-2 (`test_rb2_a_judge_template_v1_scores_url4_is_refused`).
- **README (D7-6):** the six sections keep their headings; code in the Fanout form; "Fusion as a
  named recipe" now shows `Fanout >> Synthesize` and the `sf.Fusion` shortcut (the context block
  form is gone); D5 (the fallback runs on every Case in E4b) kept; O12 note on
  `Vote(weights="score:judge")` with a lower-is-better rubric. Each code block compiles to its
  Engine fixture. `scripts/check_notebooks.py` green (notebooks untouched, unit 8).
- **Spec gaps / choices:** (1) the rebuild bug above; (2) D7-2 side effects: `sf.Pipeline([step])`
  gives CH-1 `ValueError` (was the `TypeError` "is a step"); `_recipe_kind(chain)` is
  `"pipeline"` before the lowering; the chain repr shows `Model(...)` stages; (3) a rebuilt chain
  pins rule ids (`Vote()` → `Vote(over='last_line@1', normalize='text@1')`) and puts a writer's
  prompt on the step (`Synthesize('w', prompt=...)`), so a round trip equals the authored chain
  only when the author wrote that form; those rows compare the steps or the lowered node;
  (4) `Url4.to_python()` of a url4 whose reducer is a custom registry class is "cannot rebuild"
  (before: `sf.FixtureVote(...)`).
- **Follow-ups:** multi-line layout inside a stage (a long `sf.Fanout([...], signals=...)` line, a
  long `sf.Model(...)` or `sf.CorrectiveLoop(...)` stays one line); 7f trims `_render_topology`,
  `_NARROW_PYTHON` and the `_python()` renderers (now unreached by `to_python`); U5e (D7-7).
- **Tests:** SDK suite 5634 passed, 33 skipped (before 7e: 5611 passed, 33 skipped).
- **Gates (HEAD of 7e):** `run_gates.py screamingface-engine --base e4d44281c --skip-append-only`
  ALL GATES GREEN (pyright needed `uv sync --frozen` once: the inspect pitfall);
  `run_gates.py screamingface --base e4d44281c --skip-append-only` ALL GATES GREEN (coverage floor
  95 met, check_notebooks green); `run_gates.py repo --base e4d44281c` ALL GATES GREEN.

## Unit 7: swap — steps 7f–7h

- **Commits:** `555ba0002` test (7f group F deletions + the codemod, owner list), `700c08beb`
  refactor (7f src trims, D7-8), `f646dcb2d` test (7e review fixes 3a, 3b, 4, 5), `5f6761e53` test
  RED + `8286f1aaf` fix (7e review fixes 2, 6, 7, 12), `71f4b326e` docs (spec errata, review 1
  and 2), `d308e9dbe` test RED (MSG-1), `02b007fca` refactor (7g src), `612de2367` test (7g pinned
  messages), `418dcd729` test RED + `2573bc70b` fix + `55ceee454` test (product gaps a–c),
  `3b44475b5` test (LO-P3), `28bfdf77b` test (rg check), `0555abc37` docs (`_surface` comments),
  this ledger commit.
- **7f src (D7-8):** deleted `_evaluation/fusion_recipe.py` and its two call sites (the
  Evaluation-level rewrite name check `_check_rewritten_names` went with it), `CONTEXT_MISUSE`,
  the `context` op and `Reducer._compiles_to_combine`; `ReduceNode` keeps plurality, weighted,
  median and mean (the `_BLOCK_FORMS` registry and the argmax, top_k, filter, pick_field, concat,
  judge, merge block forms are gone, with `_FieldRules`); `RankNode(by_field=)` and the
  `PickNode` field-order form (their url4 is "cannot rebuild", RB-1 rows already pin it);
  `url4._render_topology` and its helpers, `_NARROW_PYTHON`, `python_signals`,
  `SignalSource._python`, every node `_python()` (`Extract`, `matches` and the signal comparisons
  keep theirs: `render._leaf` reads them); `fusion_card_html`, `pipeline_card_html`,
  `FusionNode._repr_html_`, `_synthesizer_fields`; the reader min-judge normalization
  (`_reader_judge`, `_with_overrides`: no public path builds a min judge in a reader since the
  swap); node checks that only the lowering or the url4 rebuild reach became asserts (PickNode
  field/signal checks, RankNode source checks, FilterNode `where` type). `tests/data/
  fusion_recipe_synthesizer.url4` stays: `test_reducer_characterization.py` reads it.
- **7f tests:** one commit for the deletions (owner list): `test_fusion_block_quorum.py` (whole),
  the context rows of `test_judge_writer_warning_stages.py`, the e2e block form
  (`FusionLaneSpec.build_block`, `FORMS` "block", `_refuse_unless_block_matches` and its 4
  contract rows), the trimmed-op rows of `test_blocks_reduce.py`, `test_pick_merge_blocks.py`,
  `test_judge_blocks.py`, `test_filter*.py`, `test_pick_*.py`, `test_rank_*.py`,
  `test_judge_order.py`, `test_judge_template_v2.py::test_a_reader_reads_a_min_judge_as_the_same_judge`,
  the `_python()` asserts, the Fusion card rows; `scripts/migrate_surface.py` and
  `tests/test_migrate_surface.py` (MG-1). Kept node rows moved to the forms that stay (Pick tamper
  rows to the equals form plus a blank-value row; the recovery rows read the repr).
- **7e review fixes:** (1) MSG-1 exempts `S/_surface/fusion.py` (messages and the `sf.Fusion`
  docstring) from `Fusion`/`synthesizer` per module, spec errata in surface §11 and swap §6;
  (2) `sf.Fusion(..., synthesizer=<narrow>, optional=True)` raises "sf.Fusion optional=True needs
  a closed block: give a reducer or a writer as synthesizer=, or close the chain first" (surface
  §3b); (3a) the judge-filter tamper row, exact "filter spec ... cannot rebuild"; (3b) the solo
  rank row on `by="field:s"`; (4) the k tamper rows on the rank-by-signal shape, the `path` row
  deleted; **spec gap:** the `normalizer pin` row has no shape to move to (a rank by signal or by
  judge has no normalize step), so it is deleted too; (5) the `sf.signal is sf.signal` line;
  (6) `Rebuilt.python` is `render.code(..., width=sys.maxsize)`; (7) `_stage_values()` asserts a
  closed chain; `entry_recipe` now lowers before the judge-writer warning, so CH-8 still names an
  open chain first; (11) the stale-comment sweep covers `recipe.py`, `reducer.py`,
  `compilation.py`, `model.py`, `_surface/*`; (12) the shortcut rows: no redundant url4 compare,
  frozen rows for Gate, Merge and JudgePick.
- **7g:** every message site of swap §6 reworded (the scan found 80 message hits and 10 public
  docstrings at the start); GA-2 is "the gate reads 'chosen:conf', but this sf.Fanout does not
  declare 'conf' (declared: ...)"; the report labels member kind `fusion` as `fanout` (wire value
  unchanged); `Reducer._step_name()` gives the runtime sites the step a node lowers from (PickNode:
  First/ArgMax/ArgMin, JudgeNode: Judge/JudgePick, ReduceNode: Vote/Median/Mean); internal-only
  ReduceNode option messages name `ReduceNode`, a block op names its step (`sf.Mean has 2 weights
  for 3 members`). New `tests/test_surface_messages.py` (MSG-1 scan + one row per runtime name
  site + the `fanout` label): the allow list is empty, so U3c holds trivially.
  **Spec gap:** `render.py:180` (`no rendering for sf.<X>`) is `pragma: no cover` and unreachable
  by a public value: no row.
- **Product gaps (7d batches):** (a) `_judge_routes` reads a stage's answer (a chain's last stage,
  a FusionNode's reducer or writer recipe, cycle-safe), so `Fanout(ab) >> Synthesize(<judge
  chain>) >> Model(J)` warns again; (b) an in-block judge and writer warn on "Pipeline 'judged':
  stage N (a fanout block) uses the same model ..." ("Stage N (a fanout block) ..." for an
  unnamed chain), never the inferred block name; (c) `refs.signal_key` applies the `sf.field()`
  path rule (at most 256 characters) to a `field:<path>` key of `by=`/`weights=`; (d) the
  selection guards ("must be followed", "cannot be a member", "cannot feed a corrective loop")
  are reachable through a hand-built url4, so they are reworded ("a sf.Filter must be followed by
  sf.Synthesize", "a sf.Rank block cannot be a sf.Fanout member ..."), not trimmed; the FilterNode
  member and loop-judge rows stay as tests of that guard.
- **7h:** LO-P3 in `test_surface_parity.py` (S5, S7, S10, S10′, S11, S11′ equal their frozen
  rows, which hold the new bytes, with a byte check of the §4.1/§4.2 change, and S5 == S8; the
  doc rows 418/528 now equal their goldens and fold into LO-P1). `rg -n "sf\.(Pick|Reduce)\b|\.then\("`
  over `tests/` finds only the 3 CHANGELOG token pins (`test_pick_output.py:226,233`,
  `test_show_signals_docs.py:29`). **Spec gap:** the README still names `sf.Pick`, `sf.Reduce`
  and `.then(` in README:1–846 (D7-6: unit 8 moves those sections); not touched here.
  `synthesizer=` outside `sf.Fusion(...)` calls and `tests/_nodes.py`: FusionNode repr asserts
  (`test_filter.py:314`, `test_judge_reducer.py:119`, `test_reducer_slot.py:121`), the
  `sf.Fusion` messages in `test_fusion_shortcut.py`, the internal `_RecipeTopology(synthesizer=)`
  in `test_url4.py:497`, and the e2e golden document field `synthesizer` (data schema).
- **Owner list:** `/private/tmp/claude-501/-Users-junior-workspace-screamingface--claude-worktrees-e4b-combine-extensions/f89a8ca0-75f1-48c1-ba44-841df6ae4043/scratchpad/owner-list-unit7.md`
  (147 files: 145 edited, 2 deleted; group F by test id for 7e and 7f).
- **Follow-ups:** 7e review 8–10 (double compile on `to_python` for policy topologies; private
  `Step` in public signatures; the explicit-Pipeline repr of plain models); the stage-to-stage
  judge-writer warning of an unnamed chain still names the chain by its inferred name (member
  routes); `over="field:<path>"` has no 256-character cap (gap c covers `by=`/`weights=`);
  `JUDGE_TEMPLATES`/`JUDGE_PANEL_TEMPLATES` stay (tests read them); U5e (D7-7); multi-line layout
  inside a stage.
- **Tests:** SDK 5573 collected (5650 with the deselected e2e/paid lanes); full suite green, 31
  skipped. Engine unit suite green.
- **Gates (HEAD of 7h):** `run_gates.py screamingface-engine --base e4d44281c --skip-append-only`
  ALL GATES GREEN (pyright needed `uv sync --frozen` once: the inspect pitfall);
  `run_gates.py screamingface --base e4d44281c --skip-append-only` ALL GATES GREEN (coverage floor
  95 met); `run_gates.py repo --base e4d44281c` ALL GATES GREEN.

### Final review fixes (7f–7h)

- **Commits:** `db40f0461` fix (items 1, 2, 4, 6), `cdedd3924` fix (item 3), `bb8a420df` test
  (item 5), this ledger commit.
- **(1) Runtime step names:** `_check_members` of VoteNode/MedianNode/MeanNode and the combine
  spec builder (`_evaluation/combine_spec.py`) write `sf.{_step_name()}`: "sf.Vote has 2 weights
  for 3 members", never the wire name "vote".
- **(2) JU-1 and labels:** a `score:judge` weight on sf.Median / sf.Mean (node and block) raises
  "sf.Median does not read a judge's scores as weights; use sf.Vote(weights='score:judge') or
  sf.ArgMax('score:judge')" (new `_refuse_judge_weights`; `_MEDIAN_JUDGE_USE`,
  `_MEAN_SIGNAL_USE` and the `judge_use` parameter are gone). The quote style is single quotes,
  as in the other messages. Every step label in a message reads `sf.<Step>` (Vote, Median, Mean,
  Rank, Concat, Filter, Merge, Gate, Judge, Fanout, Synthesize; also the internal-only GateNode
  and JudgeNode option messages). The article before `sf.` is "a" in all of `src/screamingface`
  (38 sites, messages, docstrings and comments). README:353 says the new JU-1 rule. `Pipeline`
  and `Model` labels (not steps) are unchanged.
- **(3) Judge-writer warning:** an unnamed chain warns "Stages 1 and 2 use the same model ...";
  "Pipeline '<name>': stages ..." only for a named Pipeline (the `named` value of gap b).
  **Not done (not small):** the fanout-member NIT. The walk does not know where a nested
  Pipeline sits (a block member, a `sf.Synthesize` writer recipe or a corrective-loop member),
  and one Pipeline object can sit in two places; it needs the parent position threaded through
  `_warn_judge_writers`. Follow-up.
- **(4) Field paths:** `refs.extractor` uses `_checked_field_path` ("over= field path 'x' must be
  a JSON path like 'score', 'a.b' or 'a[0].b' (at most 256 characters)"); `sf.Extract("field",
  path=...)` uses `reducer._field_path` ("sf.Extract('field') path ..."; the TypeError is now
  "... path must be a string"); `sf.Filter(where=sf.signal("field:<path>") >= x)` goes through
  `signal_key` ("sf.Filter where= field path ..."). The `test_signal_key_paths.py` docstring now
  says the Engine has no cap and the SDK refuses before the compile for consistency. This closes
  the 7f–7h follow-ups "over= has no 256-character cap" and "the unnamed chain names its
  inferred name".
- **(5) PickNode output:** new tamper row (`"output": "a.b"` → "pick spec ... cannot rebuild",
  cause is the "top-level field name" ValueError).
- **(6) One step-name mechanism:** `_public_name` and `Reducer.__init_subclass__` are gone;
  `Reducer._step_name()` is `type(self).__name__.removesuffix("Node")`; PickNode, ReduceNode
  and JudgeNode override it. `JudgeNode._step_name()` is "JudgePick" for a label judge and
  "ArgMax"/"ArgMin" (by order) for a scores judge. A custom reducer shows its class name
  (`sf.FixtureVote has 1 weights ...` in `test_reducer_slot.py`).
- **New rows:** `test_surface_messages.py` (weight count x6 + combine spec; JU-1 x5; step labels
  x8; the article scan; the candidate type message; `_step_name` x4; no `_public_name`),
  `test_chain_warnings.py` (two-stage unnamed chain shows no member route; named two-stage chain
  keeps its name), `test_signal_key_paths.py` (over=, Filter where=, Extract path),
  `test_pick_output.py` (tamper row).
- **Pre-existing test files edited (owner list):** `test_band_api.py`, `test_blocks_extract.py`,
  `test_blocks_reduce.py`, `test_chain_rules.py`, `test_chain_warnings.py` (the unnamed-chain row
  renamed to `test_wj1_an_unnamed_chain_names_its_stages_only` with the new text),
  `test_corrective_recipes.py`, `test_fanout.py`, `test_filter.py`, `test_gate_api.py`,
  `test_judge_step.py`, `test_judge_weighted_vote.py`, `test_mean.py`, `test_rank_by_signal.py`,
  `test_recipes.py`, `test_reducer_slot.py`, `test_signal_key_paths.py` (labels + docstring),
  `test_signal_sum_api.py`, `test_signal_weighted_vote.py`, `test_surface_extract.py`,
  `test_weighted_median.py`, `test_weighted_vote.py`: each pins a reworded message (the article,
  a `sf.` label, JU-1, the over= path text). Append-only: `test_surface_messages.py`,
  `test_pick_output.py`.
- **Tests:** SDK full suite 5576 passed, 31 skipped.
- **Gates (HEAD `bb8a420df`):** `run_gates.py screamingface --base e4d44281c --skip-append-only`
  ALL GATES GREEN (coverage floor 95 met); `run_gates.py repo --base e4d44281c
  --skip-append-only` ALL GATES GREEN. Engine not touched.

## Owner approval of the unit 7 pinned edits (2026-10-21)

The owner approved all 147 pinned test and data files of unit 7 (145 edited, 2 deleted), and the
group F test deletions by id, as listed in
[2026-10-20-e4b-mapreduce-surface-owner-list-unit7.md](2026-10-20-e4b-mapreduce-surface-owner-list-unit7.md).
The main session writes the blob-exact entries for unit 1 and unit 7 into
`.claude/test-change-approvals/OME-1653.json` when the stack is final (after unit 8).
