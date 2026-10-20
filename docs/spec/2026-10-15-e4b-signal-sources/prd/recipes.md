# PRD: Signal recipes, README and the pinned live model

**Source:** ans:Q1, ans:Q2, ans:Q9, ans:Q11 · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: components: [declared-signals](declared-signals.md), [verbalized](verbalized.md),
[logprob](logprob.md), [entropy](entropy.md)

## 1. Summary and user story

As a researcher who reads the README, I want a tested recipe for each paper shape that part 3
unlocks, so that I can copy a recipe and know it compiles and runs.

## 2. Background and constraints

- Part 1 added a README "Combine recipes" table, with an offline test per recipe and a url4 fixture
  that the SDK and the engine both read. [existing packages/screamingface/README.md] ("Combine
  recipes"); [existing docs/spec/2026-10-13-e4b-combine-extensions/prd/recipes.md]
- v1 pins one named OpenRouter model in a test. [stated ans:Q2]
- No recorded OpenRouter reply with `logprobs` exists in the repo. Unit 1 records one on the local
  stack and keeps a trimmed copy with synthetic text as a test fixture. [proposed]

**Delta.** Five new recipe rows (S12 to S16), each with an offline test and a url4 fixture; a README
section "Signal sources"; a CHANGELOG entry; one paid test with the pinned model.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

| Row | Paper shape | Recipe | Source |
|---|---|---|---|
| S12 | Multi-agent oracles: a vote weighted by stated confidence | `signals={"conf": sf.Verbalized(r"Confidence: ([0-9]+)")}`, `sf.Vote(weights=sf.signal("conf"))` | [stated prompt] (behavior 1) |
| S13 | A vote weighted by token probability | `signals={"p": sf.Logprob("prob")}`, `sf.Vote(weights=sf.signal("p"))` | [stated ans:Q11] |
| S14 | Pick the member with the highest mean logprob | `signals={"lp": sf.Logprob("mean")}`, `sf.Pick(by_signal=sf.signal("lp"), order="max")` | [stated prompt] (behavior 2) |
| S15 | Pick the member with the lowest entropy | `signals={"ent": sf.Entropy()}`, `sf.Pick(by_signal=sf.signal("ent"), order="min")` | [stated prompt] (behavior 2) |
| S16 | STEER shape: record a small model's confidence against a threshold | `signals={"lp": sf.Logprob("mean")}`, `sf.Filter(where=sf.signal("lp") >= -0.3)`, then a writer | [stated prompt] (behavior 5) |

- **RC-1** Given each row, then its recipe compiles, its url4 equals the fixture byte for byte, and the
  engine runs the fixture over fake replies to the hand-computed answer. [implied]
- **RC-2** Given the README code blocks, then each one compiles (the part 1 doc-example test).
  [existing ST/test_combine_recipes_readme.py]
- **RC-3** Given the paid test with the pinned model, then one live call returns `logprobs`, and the
  member's `lp` value is finite and ≤ 0. [stated ans:Q2]

### 3.2 Error paths

- **RC-E1** Given the paid test and a model that refuses logprobs and that the gateway catalog does
  NOT mark unsupported (unit 1 names one), then the run passes the SDK preflight, reaches the call,
  and the call fails with `logprobs_unsupported`. [stated ans:Q5]; [proposed] (orchestrator decision:
  a catalog-marked model is refused earlier by the preflight, LC-E4)
- **RC-E2** Given a recipe that uses `sf.Logprob("mean")` as a vote weight, then the README shows the
  compile error and the `prob` fix. [stated ans:Q11]

### 3.3 Derived scenarios (risk-ordered)

- **RC-D1** (H×M) [implied] Given the part 1 recipes S1 to S11, then their fixtures do not change
  (CHAR).
- **RC-D2** (M×M) [proposed] Given S16, then the README states that the larger model still runs; the
  skip is E4c.
- **RC-D3** (M×L) [stated ans:Q9] Given S12, then the README states: ask every member for the same
  scale, and put the confidence line within the last 64 KiB of the reply.
- **RC-D4** (M×L) [existing G/config.py:158-162] Given S14 or S15 with a frozen copy, then the README
  states the 2,000,000-byte entry cap (request plus reply) and the 1,000,000-byte cache cap, and says
  to keep `top_logprobs` small.

## 4. Non-functional requirements

- The paid test runs only in the paid lane, not in the default gates. [existing ST/paid/]
- The fixtures hold synthetic text only; no provider text is copied into the repo. [proposed]

## 5. Out of scope

- Replay lanes (as part 1, ans:Q8 of part 1). [proposed]
- UniTE and the span ensemble. They are not in E4b (owner, 2026-10-20; ans:Q3 first placed them in part 8).

## 6. Open questions

None.

## 7. TDD plan

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `recipes_s1_to_s11_fixtures_are_unchanged` | unit | RC-D1 | H×M | passes today |
| 2 | `recipe_s12_verbalized_vote` | integration | RC-1 | H×M | builder + fixture + engine run |
| 3 | `recipe_s13_logprob_prob_vote` | integration | RC-1 | H×M | — |
| 4 | `recipe_s14_logprob_argmax` | integration | RC-1 | H×M | — |
| 5 | `recipe_s15_entropy_argmin` | integration | RC-1 | M×M | — |
| 6 | `recipe_s16_logprob_threshold_records_values` | integration | RC-1, RC-D2 | M×M | — |
| 7 | `readme_signal_sources_blocks_compile_and_carry_the_guidance` | unit | RC-2, RC-E2, RC-D3, RC-D4, VB-D4, LP-D3, EN-D5 | M×L | doc-example test; the guidance sentences (one scale, 64 KiB window, `sum` favors short replies, keep k small, the two caps) are checked by text |
| 8 | paid `pinned_openrouter_model_returns_logprobs` | E2E (paid) | RC-3 | H×M | named model from unit 1 |
| 9 | paid `uncatalogued_refusing_model_fails_logprobs_unsupported` | E2E (paid) | RC-E1 | M×M | a model the catalog does not deny, so the runtime path runs |
