# E4b part 1: combine extensions — overview

**Status:** approved (2026-10-13), built on 2026-10-13 and 2026-10-14, in review as PR #1409.
**Epic:** E4b (OME-1290). **Leaf:** OME-1601.
**Base:** written on branch `e4a-integrated` (the full E4a stack OME-1578..OME-1593 on origin/main
`3cf66b545`). E4a merged into main on 2026-10-13 (`d0ec10795`). The build is on `origin/main`.

## 1. Summary

E4a lets a Fusion end in a deterministic reducer instead of a model synthesizer. E4b part 1 extends
that pattern so that 11 combine scenarios from the prompt all have a tested recipe. Most scenarios
already work on E4a. This part adds the missing pieces:

- a mean and a weighted mean (`mean@1`, `weighted_mean@1`, `sf.Mean`), also usable as a picker;
- a weighted median (`weighted_median@1`, `sf.Median(weights=...)`);
- a judge that picks the lowest score (`sf.Judge(..., order="min")`);
- a Filter by judge score (`sf.Filter(..., judge=...)`);
- a Pick that outputs one JSON field (`sf.Pick(..., output="answer")`);
- the Case input in the output of Rank and Filter, so that the writer after them sees the question;
- offline recipe tests and a README section for all scenarios.

No url4 change, no gateway change, no new failure code, and no new schema id.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `e5523a20d`.

**Scenario map** (prompt lines 5 and 6 are the same, named S5):

| S | Status on E4a | E4b work |
|---|---|---|
| S1 median → number | works | recipe test |
| S2 median → member answer | works | recipe test |
| S3 weighted average, static weights | missing | [mean](prd/mean.md) |
| S4 weighted average by confidence | missing | [mean](prd/mean.md) (block form for the JSON field) |
| S5 max confidence → response | works (JSON replies) | recipe test; optional [pick-output](prd/pick-output.md) |
| S7 confidence top-N → writer | works, writer cannot see the question | [selection-input](prd/selection-input.md), recipe |
| S8 confidence argmax → response | works (JSON replies) | recipe test; optional [pick-output](prd/pick-output.md) |
| S9 confidence > value → writer | works, writer cannot see the question | [selection-input](prd/selection-input.md), recipe |
| S10 judge scores → top-N → writer | works, writer cannot see the question | [selection-input](prd/selection-input.md), recipe; threshold variant [filter-judge](prd/filter-judge.md) |
| S11 judge scores → argmax / argmin | argmax works; argmin missing | [judge-order](prd/judge-order.md), recipe |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| Engine combine core (`E/combine/`) | operators, spec rules, evidence | mean, weighted-median, pick-output, selection-input, catalog-and-schema |
| SDK reducers (`S/reducer.py`, `judge.py`, `selection.py`, `fields.py`, `blocks.py`) | user API, compile, rebuild | all PRDs except selection-input |
| Contract data (`ET/data/combine_contract/`) | v1 schema snapshots, url4 fixtures | catalog-and-schema, recipes |
| Docs (`packages/screamingface/README.md`, `CHANGELOG.md`) | user guidance | recipes, selection-input |

## 3. Reading order

1. [erd.md](erd.md)
2. [prd/catalog-and-schema.md](prd/catalog-and-schema.md) (component, used by all)
3. [prd/selection-input.md](prd/selection-input.md) (P0, unblocks S7, S9, S10)
4. [prd/recipes.md](prd/recipes.md) (P0, proves the scenarios that already work)
5. [prd/mean.md](prd/mean.md), [prd/judge-order.md](prd/judge-order.md) (P1)
6. [prd/weighted-median.md](prd/weighted-median.md), [prd/filter-judge.md](prd/filter-judge.md),
   [prd/pick-output.md](prd/pick-output.md) (P2 extras)
7. [contracts.md](contracts.md), [test-plan.md](test-plan.md)

## 4. PRD index

| PRD | Lifecycle | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|
| [catalog-and-schema](prd/catalog-and-schema.md) | existing | 4 / 2 / 4 | 11 |
| [selection-input](prd/selection-input.md) | existing | 4 / 2 / 6 | 13 |
| [recipes](prd/recipes.md) | existing | 9 / 3 / 3 | 13 |
| [mean](prd/mean.md) | planned | 5 / 4 / 10 | 25 |
| [judge-order](prd/judge-order.md) | existing | 4 / 2 / 4 | 13 |
| [weighted-median](prd/weighted-median.md) | existing | 4 / 3 / 4 | 15 |
| [filter-judge](prd/filter-judge.md) | existing | 2 / 4 / 4 | 12 |
| [pick-output](prd/pick-output.md) | existing | 5 / 3 / 5 | 17 |
| **Total** | | **37 / 23 / 40** | **119** |

## 5. Interview ledger

The prompt is the list of 11 scenarios and "how the following scenarios/use cases could be achieved
using its pattern or extending its patterns in a compatible way" (2026-10-13).

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | D1: one mean operator with optional weights, or a `mean` / `weighted_mean` split? | "d1 - split" | recommended |
| Q2 | D2: a member with a missing or ≤ 0 weight in a weighted mean — drop it or fail the Case? | "d2 - drop it" | recommended |
| Q3 | D3: free-text confidence — JSON-reply prompts first, or derived text signals (G2) now? | "d3 - recommended" (JSON replies first; G2 deferred) | recommended |
| Q4 | D4: an empty Filter — abstain (today) or fall back? | "d4 - today`s behavior" | recommended |
| Q5 | D5: a new reducer kind — additive edit to `combine-spec.v1` or a new v2? | "d5 - additive edit, no need to care abour versions for now" | recommended |
| Q6 | D6: E4b or a new epic? | "d6 - yeah, it`s part of e4b" | — |
| Q7 | G5: how does the stage after a Rank/Filter see the Case question? | "Always, automatically" | recommended |
| Q8 | Phase 0: how far to prove the working recipes? | "Offline tests + README" | recommended |
| Q9 | Which small extras? | "Mean as a picker, Weighted median, Pick outputs one field, Filter by judge score" | all four |
| Q10 | G4: one judge call per answer — now or later? | "Defer" | recommended |
| Q11 | Judge `order="min"`: what is the judge told? | "Lower score = better" | recommended |
| Q12 | Pick output field missing on the winner? | "Abstain" | against the recommendation ("take the next best") |
| Q13 | G5 for Concat too? | "Rank and Filter only" | recommended |

## 6. Global decisions [proposed]

| # | Decision | Where |
|---|---|---|
| P1 | The division of a mean is rounded to 34 significant digits (`ROUND_HALF_EVEN`). The sums stay exact. | [mean](prd/mean.md) MN-D1 |
| P2 | The weight check lives in the weighted operators (Vote precedent): `weighted_*` without spec weights is `combine_spec_invalid`; `mean@1` and `median@1` ignore weights (CS-I1). | [erd §2](erd.md) |
| P3 | The weighted median takes the mean of the two neighbors at exactly half the weight, so equal weights give `median@1`. | [weighted-median](prd/weighted-median.md) |
| P4 | G5 is done in the engine envelope (option C), not in the SDK compile (option A). `top_k@1` and `kept@1` change in place, with no `@2`. This reads ans:Q5 ("no need to care abour versions for now") as covering operator output too, not only the reducer enum. | [selection-input](prd/selection-input.md) §2 |
| P5 | `output` is an optional arg on `by_field@1` and `best_holder@1` (same id, additive under ans:Q5). | [pick-output](prd/pick-output.md) |
| P6 | A Judge with `order="min"` is refused inside Rank, Vote and Filter. | [judge-order](prd/judge-order.md) JO-D1 |
| P7 | No new failure code. New empty results are abstains, and new refusals are `combine_spec_invalid`. | [catalog-and-schema](prd/catalog-and-schema.md) CS-D2 |
| P8 | The evidence gets an optional `mean` field, and `median` is `null` for the `mean` reducer. The weighted median uses `median`. | [erd §7](erd.md) |
| P9 | `Reduction.participants` keeps weight-dropped members out of `nearest` (ans:Q2). | [erd §5](erd.md) |
| P10 | `sf.Mean` takes `extract` as an operator name, like `sf.Median`. A JSON-field extract (S4) uses the block form `sf.Reduce("mean", extract=sf.Extract("field", path=...))`. | [mean](prd/mean.md) §2 |
| P11 | The `median` and `mean` blocks take `select="nearest" \| "value"`, the word of `sf.Median` and `sf.Mean`, as a second name for `mode` (playground fix, 2026-10-14). The block keeps only the mode, so no url4 changes. `sf.Median` and `sf.Mean` keep `extract` as an operator name (P10). | [weighted-median](prd/weighted-median.md) WM-5, [mean](prd/mean.md) §3 |
| P12 | An abstained Rank or Filter step (ans:Q4) still hands the next stage the input (ans:Q7): its output is the empty envelope `{"input":"...","selected":[]}`, and the abstain stays in its evidence. When the step is the last step of a url4, the Case abstains with the empty answer, as before. The 8 MiB result cap applies (SI-E2). Playground fix, 2026-10-14. | [selection-input](prd/selection-input.md) SI-E1 |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | G2: confidence and other signals read from free text (an extract → normalize pair as a signal) | deferred by ans:Q3; build after the JSON-reply recipes prove the need |
| D2 | G4: one judge call per member | deferred by ans:Q10; revisit if position bias shows in results |
| D3 | logprob signals (E4a D3) | stays in E4b, later part |

Scope notes from [proposed] items (the user can change them before the build):

- **N1** A "lower is better" judge rubric works only with the judge pick. Rank, Vote and Filter
  refuse a Judge with `order="min"` (P6). Rank can still keep the lowest scores with its own
  `order="min"`, but the judge is then told that higher is better.
- **N2** The `input` in the selection envelope is the input of that Fusion. When the Fusion is not
  the first Pipeline stage, that is the previous stage's output, not the Case question
  ([selection-input](prd/selection-input.md) SI-D2).
- **N3** A Case input of more than about 8 MiB makes a Rank or Filter call fail on the result cap
  (SI-E2), also when the call abstains (P12). Benchmark inputs today are far smaller.

## 8. What changes for related epics

- **E4a (OME-1289).** Nothing in its PRs changes. E4a merged into main on 2026-10-13
  (`d0ec10795`), and E4b moved onto `origin/main` with its content unchanged.
- **E4a docs.** The README rule "the next stage does not receive the original question" is
  replaced for Rank and Filter in this part (selection-input docs commit).

## 9. Build errata

Each ledger in `docs/work/2026-10-13-e4b-*.md` and `docs/work/2026-10-14-e4b-playground-fixes.md`
records its own deviations. These change the spec:

| # | Erratum | Record |
|---|---|---|
| ER1 | RC-E1 and contracts C2 said that an empty Filter makes the Case abstain before the next stage runs. In fact, the next stage ran with an empty text. P12 replaces both: the next stage gets the empty envelope. | [contracts](contracts.md) C2, playground-fixes ledger |
| ER2 | P11 and P12 were added after the build, from a live test on 2026-10-14. | playground-fixes ledger |
| ER3 | `ST/test_frozen_record_fields.py` needed an owner-approved edit (two new evidence scenarios, 26 to 28). The plan did not list it. The owner approved it with the other 18 files. | pick-output ledger Q-B, `.claude/test-change-approvals/OME-1601.json` |
| ER4 | The dedup step left the engine copies of the field-name regex (F7-engine). `ST/tests/unit/test_signal_key_conformance.py` reads the literal regex in `E/combine/operators/fields.py`, so removing them needs an owner-approved test edit. | dedup ledger |
| ER5 | A writer call after a Rank or a Filter misses the request cache once, because its input now carries the envelope. | selection-input ledger, review note 5 |
| ER6 | The README recipe table gets three extra rows: "S4, median form", "S10, threshold form" and "S11, min form". They are not edits of the S4, S10 and S11 rows. | filter-judge and judge-order ledgers |
| ER7 | The erd §2 rows "`reduce.op` for `mean`" and "`reduce.op` for `median`" were not enforced: a `median` reducer with `mean@1` ran and wrote the mean into `evidence.median`. The spec parser now ties each statistic operator to its reducer by name: `median` and `weighted_median` only under `median`, `mean` and `weighted_mean` only under `mean`. Any other pair is `combine_spec_invalid`, and the message names no operator id. Other reduce operators stay free, so this is a per-operator rule, not a `ReducerRule` row (CS-I1 is unchanged). | review P1 #4, `E/combine/spec.py` `_STATISTIC_REDUCERS` |
