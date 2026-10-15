# Test plan: E4b part 2 — evidence completeness

Test ids are `<PREFIX>#<n>`, with the row number from each PRD's §7. Prefixes: `ES` evidence
schema, `EX` member exclusion, `RK` rank and cut, `JM` judge model, `JW` judge-writer warning.

## 1. Strategy

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| A Case answer changes because the evidence changed (part 2 must be record-only) | H×H | property over goldens and evidence cases | EX#3, RK#9, JM#1 |
| An abstain hides which members were left out (the case that matters most) | H×H | unit | EX#5, EX#8, RK#7 |
| Engine and SDK words drift, so the SDK refuses a valid evidence | H×M | cross-side fixture decode | ES#5, ES#10, ES#14 |
| A failure is shown as an exclusion, or an exclusion as a pass | H×M | decision table X1–X6 | EX#4, EX#6–13 |
| Rank and cut disagree with `chosen` | H×M | property | RK#2–5 |
| The compiled bytes of a recipe without a judge change | H×M | CHAR | ES#1, JM#1, RK#9 |
| The judge fixtures drift from the SDK compile | H×M | fixture drift guard | JM#10 |
| A noisy or wrong warning | M×M | unit | JW#1–10 |

## 2. TDD ground rules

- RED first. Run each new test and see it fail on the missing behavior, not on an import error.
- A `CHAR` row pins today's behavior and passes before the change. It is the safety net for an
  existing component. It is not a RED step.
- GREEN is the smallest change. Refactor on green only.
- One behavior for each test. The test name states the behavior.
- Each user decision has a test that fails if the decision breaks:
  Q1 EX#4, RK#2, JW#1 · Q2 JM#2–3, JM#5, JW#1 · Q3 ES#2, ES#12, EX#4–9.
- The oracle for every rank is hand-computed in the PRD (for example RK-1), never copied from the
  code's output.

## 3. Lanes

| Lane | Where | What |
|---|---|---|
| Engine unit | `apps/screamingface-engine/tests/unit/` | endpoint exclusion rule, rank and cut hooks, evidence models, spec check |
| Engine evidence fixture | `ET/data/combine_contract/evidence_cases.json` (regenerated, approved) | new cases X1, X2, rank, cut, judge model |
| Engine runs of SDK fixtures | `_signal_world.run_candidate` | EX#18, RK#13, JM#12 |
| SDK unit | `packages/screamingface/tests/` | words, rows, decoder, `sf.Answer`, the warning, compile bytes |
| Fixture drift guard | SDK generator → `ET/data/combine_contract/*.url4` | JM#10 |
| Schema freeze | `ST/test_frozen_record_fields.py`, the v1 schema snapshots | ES#14 |

No e2e replay lane is added. [proposed]

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [evidence-schema](prd/evidence-schema.md) | 4 / 3 / 6 | 14 |
| [member-exclusion](prd/member-exclusion.md) | 4 / 3 / 8 | 18 |
| [rank-and-cut](prd/rank-and-cut.md) | 3 / 2 / 5 | 13 |
| [judge-model](prd/judge-model.md) | 3 / 3 / 4 | 12 |
| [judge-writer-warning](prd/judge-writer-warning.md) | 2 / 1 / 6 | 11 |
| **Total** | **16 / 12 / 29** | **68** |

## 5. Not tested

| Item | Why | Revisit when |
|---|---|---|
| How a report UI shows `"excluded"`, `rank` and `cut` | part 4 owns the display | part 4 is planned |
| A writer that is a Fusion, or a nested Pipeline, using the judge model | out of scope (JW §5) | a researcher asks |
| Old SDKs reading new evidence | not supported: the engine and the SDK ship together (C3) | the SDK and the engine get separate releases |
