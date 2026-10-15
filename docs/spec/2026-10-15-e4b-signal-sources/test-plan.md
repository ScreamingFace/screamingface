# Test plan: E4b part 3, signal sources v1

Test ids are `<PREFIX>#<n>`, with the row number from each PRD's §7. Prefixes: `DS` declared signals,
`LC` logprob capture, `VB` verbalized, `LP` logprob, `EN` entropy, `RC` recipes.

## 1. Strategy

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| A rule reads a name that no one declared, and the run spends money before it fails (breaks ans:Q1) | H×H | unit | DS#4, DS#10 |
| A raw logprob is used as a vote weight and every member is dropped (breaks ans:Q11) | H×H | unit | LP#4, EN#7 |
| Token text leaks into logs or evidence (OME-990) | H×H | unit, log capture | LC#5 |
| A model without logprobs fails with a generic code, or the signal is invented (breaks ans:Q5) | H×H | integration on the recorded refusal | LC#9–11, RC#9 |
| A cache hit gives other numbers than the original call (breaks reproducible replay) | H×M | integration | LC#8 |
| An existing recipe changes bytes, digest or cache key | H×M | CHAR | DS#1, LC#1, RC#1 |
| The E4a refusal pins for `logprob_mean` stop passing | H×M | CHAR | DS#2, DS#3 |
| A wrong number from the formulas (sum, mean, prob, entropy) | H×M | unit with hand-computed oracles | LC#3, LP#1–3, EN#1–5 |
| A hostile text or pattern stalls the engine | M×M | unit, generous CPU bound | VB#4, VB#10 |
| The README recipe stops compiling | M×L | doc-example test | RC#7 |

## 2. TDD ground rules

- RED first. Run each new test and see it fail on the missing behavior, not on an import error.
- A `CHAR` row pins today's behavior and passes before the change. It is not a RED step.
- GREEN is the smallest change. Refactor on green only.
- One behavior for each test. The test name states the behavior.
- The oracle for every number is hand-computed in the PRD (LP-1, EN-1), never copied from the code.
  Floats that come from a division compare with `pytest.approx(rel=1e-12)`; sums use `math.fsum`.
- A timing test uses a generous bound and runs in the serial lane if one exists (OME-1619).
- Each user decision has a test that fails if the decision breaks, except where noted:
  Q1 DS#4, DS#9, DS#10 · Q2 LP#5, EN#3 (via LP#5), RC#8 · Q3 no test (it places work in part 8) ·
  Q4 DS#5 (`cost_usd` cannot be a declared name) · Q5 LC#9, LC#10, RC#9 · Q6 LC#3, LP#11 ·
  Q7 DS#11, DS#12 · Q8 EN#6, EN#8 · Q9 VB#1–3 · Q10 no test (it shapes the plan) · Q11 LP#1, LP#4.

## 3. Lanes

| Lane | Where | What |
|---|---|---|
| Engine unit | `apps/screamingface-engine/tests/unit/` | `reply_logprobs`, spec parse, reader, evidence, failure code |
| Engine connector | `apps/screamingface-engine/tests/unit/test_*connector*` style, with a fake gateway | call body, terminal round, cache hit, refusal mapping |
| Engine runs of SDK fixtures | `test_sdk_candidate_contracts.py` style, `_signal_world.run_candidate` with fake logprobs | all `recipe_*` and engine-run rows |
| SDK unit | `packages/screamingface/tests/` | constructors, name rules, compile bytes, weight refusals, decoder, public surface |
| Fixture drift guard | SDK generator → `ET/data/combine_contract/*.url4` | RC#2–6 |
| Schema freeze | `ET/test_wire_schema_freeze.py` | the two v1 schema snapshots (approved edit) |
| Paid | `packages/screamingface/tests/paid/` | RC#8, RC#9 with the pinned model |

The fake gateway replies use the shape that unit 1 records, with synthetic token text.

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [declared-signals](prd/declared-signals.md) | 4 / 3 / 9 | 15 |
| [logprob-capture](prd/logprob-capture.md) | 4 / 3 / 8 | 14 |
| [verbalized](prd/verbalized.md) | 3 / 3 / 7 | 10 |
| [logprob](prd/logprob.md) | 5 / 4 / 6 | 11 |
| [entropy](prd/entropy.md) | 4 / 3 / 5 | 10 |
| [recipes](prd/recipes.md) | 3 / 2 / 3 | 9 |
| **Total** | **23 / 18 / 38** | **69** |

## 5. Not tested

| Item | Why | Revisit when |
|---|---|---|
| Logprobs from providers other than OpenRouter | ans:Q2 | a provider is added to v1 |
| Calibration of verbalized confidence and of token probability | a research question, not correctness | a calibration report is planned |
| Live logprobs on every model in the catalog | one pinned model only (ans:Q2) | the gateway catalog reports logprob support per model |
| Replays of replies over 1,000,000 bytes | the gateway does not cache them; documented (LC-D7) | the cache cap changes |
