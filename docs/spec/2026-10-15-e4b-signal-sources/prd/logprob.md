# PRD: Logprob signal (`sf.Logprob("mean" | "sum" | "prob")`)

**Source:** ans:Q1, ans:Q2, ans:Q6, ans:Q11 · **Priority:** P0
**Lifecycle:** planned
**Owner:** unassigned
Paths: [erd §1, §3](../erd.md) · components: [declared-signals](declared-signals.md),
[logprob-capture](logprob-capture.md)

## 1. Summary and user story

As a researcher whose method weights or picks answers by the model's own token probability, I want
each member answer to carry its log-probability, so that a vote, a pick, a rank or a filter can use
it, and a report can show it.

## 2. Background and constraints

- From the token log-probabilities that the provider returned, compute the answer's mean
  log-probability or the sum, as the author selects. If the provider did not return them, the run
  fails this signal; it does not invent a confidence. [stated prompt] (epic sources table)
- The forms are `mean`, `sum` and `prob`. `prob = exp(mean)`, in (0, 1]. `mean` or `sum` as a vote
  weight fails at compile, with a hint to use `prob`. Pick, Rank and Filter accept all three.
  [stated ans:Q11]
- All reply tokens count. [stated ans:Q6]
- OpenRouter only. [stated ans:Q2]
- Vote weights must be greater than 0; part 1 drops the others. [existing E/combine/endpoint.py:427]

**Delta.** `sf.Logprob(form)` is a declared source. The engine reads the member's `ReplyLogprobs`
([logprob-capture](logprob-capture.md)) and computes the form.

## 3. Scenarios and acceptance criteria

**Definition [stated ans:Q11].** With `n = tokens` and `s = logprob_sum`: `sum = s`; `mean = s / n`;
`prob = exp(s / n)`. With `n = 0`, every form is None.

### 3.1 Happy path

- **LP-1** Given content logprobs `-0.1, -0.2, -0.3`, then `sum = -0.6`, `mean = -0.2` (the float is
  `-0.19999999999999998`; tests compare with `pytest.approx(rel=1e-12)`) and
  `prob = 0.8187307530779818`. [stated ans:Q11]
- **LP-2** Given `sf.Pick(by_signal=sf.signal("lp"), order="max")` with `lp = sf.Logprob("mean")`
  and member means `-0.9, -0.2, -0.5`, then member 2 is picked, and its text is copied.
  [stated prompt] (behavior 2)
- **LP-3** Given `sf.Vote(weights=sf.signal("p"))` with `p = sf.Logprob("prob")` and members A
  (prob 0.8), B (0.7), A (0.1), then A = 0.9, B = 0.7, and A wins. [stated ans:Q11]
- **LP-4** Given `sf.Filter(where=sf.signal("lp") >= -0.5)`, then the members with mean ≥ -0.5 are
  kept. [stated ans:Q11]
- **LP-5** (STEER shape) Given one member and `sf.Filter(where=sf.signal("lp") >= -0.3)` before a
  writer, then the evidence records the member's mean and whether it passed. The skip of the larger
  model is E4c. [stated prompt] (behavior 5)

### 3.2 Error paths

- **LP-E1** Given `sf.Vote(weights=sf.signal("lp"))` where `lp` is `mean` or `sum`, then the Fusion
  constructor raises `ValueError` that says to use `sf.Logprob("prob")`. The same for
  `sf.Median(weights=...)` and `sf.Mean(weights=...)`. [stated ans:Q11]
- **LP-E2** Given a member on a route that is not `openrouter/...`, then the Fusion constructor raises
  `ValueError` ("sf.Logprob supports OpenRouter models in v1"). [stated ans:Q2]
- **LP-E3** Given a Recipe member (a nested Fusion or Pipeline), then the Fusion constructor raises
  `ValueError` (DS-I4). [proposed]
- **LP-E4** Given a model that cannot return logprobs, then the member call fails with
  `logprobs_unsupported` (LC-E1). [stated ans:Q5]

### 3.3 Derived scenarios (risk-ordered)

- **LP-D1** (H×H) [stated ans:Q11] Given `prob`, then every value is in (0, 1], so a vote never
  drops a member for a 0 weight unless the value is None.
- **LP-D2** (H×M) [implied] Given a member whose reply has 0 content tokens (an empty answer), then
  each form is None, and the member is left out of a pick, a rank, a vote or a filter.
- **LP-D3** (H×M) [implied] Given `sum`, then a longer reply has a lower value. The README warns
  that `sum` favors short replies, and that `mean` and `prob` do not depend on length.
- **LP-D4** (M×M) [implied] Given `exp` of a very negative mean (`-800`), then `prob` underflows to
  `0.0`. Then the value is None (a weight must be > 0, I-S2 keeps finite values only). [proposed]
- **LP-D5** (M×M) [implied] Given members of `sf.samples(model, n=5)`, then each sample has its own
  value, because each call has its own seed and fingerprint.
  [existing S/_samples.py:21-48]
- **LP-D6** (M×L) [proposed] Given a reasoning model, then only the content tokens count, not the
  reasoning tokens (ans:Q6 "reply tokens").

## 4. Non-functional requirements

- No extra model call. The cost of the logprobs is in the response size only (see
  [logprob-capture](logprob-capture.md) §4). [implied]
- `exp` and the division use Python floats; the value goes into the evidence as a finite float.
  [proposed]

## 5. Out of scope

- Perplexity as a form (`exp(-mean)`). [stated ans:Q11] ("prob" was chosen, not "perplexity")
- Answer-span-only tokens. [stated ans:Q6]
- Other providers. [stated ans:Q2]
- The cascade skip. E4c. [stated prompt]

## 6. Open questions

None.

## 7. TDD plan

Order: core-out. The form arithmetic first, then the compile checks, then engine runs.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `logprob_forms_mean_sum_prob` (LP-1 oracle) | unit | LP-1 | H×M | pure function over `ReplyLogprobs` |
| 2 | `logprob_of_zero_tokens_is_none` | unit | LP-D2 | H×M | — |
| 3 | `logprob_prob_underflow_is_none` | unit | LP-D4 | M×M | — |
| 4 | `vote_weight_refuses_logprob_mean_and_sum_with_a_prob_hint` | unit | LP-E1 | H×H | check in Vote, Median, Mean weight paths |
| 5 | `logprob_refuses_non_openrouter_and_recipe_members` | unit | LP-E2, LP-E3 | H×M | route prefix, member kind |
| 6 | `logprob_compiles_logprobs_true_on_each_member_call` | unit | LC-2 | H×M | member params |
| 7 | `pick_max_by_logprob_mean` | integration | LP-2 | H×M | `run_candidate`, fake logprobs |
| 8 | `vote_weighted_by_logprob_prob` | integration | LP-3, LP-D1 | H×M | — |
| 9 | `filter_by_logprob_threshold_records_the_values` | integration | LP-4, LP-5 | M×M | — |
| 10 | `samples_members_get_their_own_logprob` | integration | LP-D5 | M×M | — |
| 11 | `logprob_counts_content_tokens_only` | unit | LP-D6 | M×L | ignore reasoning fields |
