# Test plan: E4b combine extensions

Test ids are `<PREFIX>#<n>`, with the row number from each PRD's §7. Prefixes: `CS` catalog and
schema, `MN` mean, `WM` weighted median, `JO` judge order, `FJ` filter by judge, `PO` pick output,
`SI` selection input, `RC` recipes.

## 1. Strategy

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| A mean returns a wrong or non-deterministic number (precision, float weights, drop rule) | H×H | unit, property, golden | MN#1–9, MN#13–15, MN#24–25 |
| A member dropped for its weight still wins `nearest` (breaks ans:Q2) | H×H | unit | MN#3, WM#5 |
| The writer after a selection still cannot see the Case question | H×H | unit and world integration | SI#3–9, RC#1–3 |
| A Pick with `output` returns a field from the wrong member, or falls back against ans:Q12 | H×H | unit | PO#2–6, PO#8 |
| Judge `order="min"` picks the worst answer, because the template still says higher is better | H×H | unit, integration | JO#3–4, JO#12 |
| Engine and SDK vocabularies drift (catalog, reducer names, abstain reasons, schemas) | H×M | unit pins | CS#1–11 |
| A changed default changes compiled bytes of existing recipes | H×M | CHAR tests | WM#1, JO#2, PO#1, SI#2, MN#10 |
| Weighted median boundary at exactly half the weight | H×M | unit, property | WM#3–6 |
| Judge pairing rules on Filter, Rank and Vote | M×M | unit | FJ#3–5, JO#7 |
| A recipe in the README stops compiling | M×L | doc-example test | RC#13 |

## 2. TDD ground rules

- RED first. Run each new test and see it fail on the missing behavior, not on an import error.
- A `CHAR` row pins today's behavior and passes before the change. It is the safety net for an
  existing component. It is not a RED step.
- GREEN is the smallest change. Refactor on green only.
- One behavior for each test. The test name states the behavior.
- Each user decision has a test that fails if the decision breaks, except where noted:
  Q1 MN#17 · Q2 MN#2, MN#3, WM#5, WM#7 · Q3 MN#23 · Q4 FJ#7, RC#4 · Q5 CS#3–5 ·
  Q6 no test (it places the work in E4b) · Q7 SI#3–4, SI#7 · Q8 RC#1–11 ·
  Q9 MN#11, WM#3, FJ#2, PO#2 · Q10 no test (deferred work) · Q11 JO#4 · Q12 PO#4–5 · Q13 SI#1.
- The oracle for every number is hand-computed in the PRD (for example MN-2 = 37.5), never copied
  from the code's output.

## 3. Lanes

| Lane | Where | What |
|---|---|---|
| Engine unit | `apps/screamingface-engine/tests/unit/` | operators, select rules, evidence, goldens |
| Engine world | `apps/screamingface-engine/tests/unit/test_*_world.py` | writer message after a selection |
| Engine runs of SDK fixtures | `test_sdk_candidate_contracts.py` style, with `_signal_world.run_candidate` | all `engine_runs_*` and `recipe_*` rows |
| SDK unit | `packages/screamingface/tests/` | constructors, compile bytes, rebuild, blocks, public surface |
| Fixture drift guard | SDK generator test → `ET/data/combine_contract/*.url4` | RC#12 |
| Schema freeze | `ET/test_wire_schema_freeze.py` | CS#3–5 |

No e2e replay lane is added. [stated ans:Q8]

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [catalog-and-schema](prd/catalog-and-schema.md) | 4 / 2 / 4 | 11 |
| [selection-input](prd/selection-input.md) | 4 / 2 / 6 | 13 |
| [recipes](prd/recipes.md) | 9 / 3 / 3 | 13 |
| [mean](prd/mean.md) | 5 / 4 / 10 | 25 |
| [judge-order](prd/judge-order.md) | 4 / 2 / 4 | 13 |
| [weighted-median](prd/weighted-median.md) | 4 / 3 / 4 | 15 |
| [filter-judge](prd/filter-judge.md) | 2 / 4 / 4 | 12 |
| [pick-output](prd/pick-output.md) | 5 / 3 / 5 | 17 |
| **Total** | **37 / 23 / 40** | **119** |

## 5. Not tested

| Item | Why | Revisit when |
|---|---|---|
| Live model behavior (does a real model follow the JSON reply format or the `order=min` template?) | ans:Q8: offline only | the user records a replay lane for a recipe |
| Calibration of verbalized confidence | out of scope; a research question, not a correctness one | G2 (free-text signals) is planned |
| Position bias of the one-call panel judge | G4 is deferred (ans:Q10) | results show the judge favors a position |
| Mixed confidence scales across members (mean MN-D9) | the engine cannot detect intent; README guidance only | a scale-declaring signal is designed |
| Prompt injection through the new `input` key (selection-input SI-D6) | no new trust boundary: member texts already reach the writer | a stage gets content from outside the Case |
