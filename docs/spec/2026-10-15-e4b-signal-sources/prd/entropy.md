# PRD: Entropy signal (`sf.Entropy(top_logprobs=5)`)

**Source:** ans:Q1, ans:Q2, ans:Q8 · **Priority:** P1
**Lifecycle:** planned
**Owner:** unassigned
Paths: [erd §1, §3](../erd.md) · components: [declared-signals](declared-signals.md),
[logprob-capture](logprob-capture.md)

## 1. Summary and user story

As a researcher whose method reads the model's uncertainty, I want each member answer to carry the
mean entropy of its token distribution, so that I can pick the most certain member, or record how
uncertain a small model was before a cascade decides.

## 2. Background and constraints

- Arithmetic on the same logprobs: the uncertainty of the token distribution. Mean entropy is enough
  for v1. Same provider requirement as `logprob`. [stated prompt] (epic sources table)
- `top_logprobs` is 5 by default; the author can set up to 20; the evidence records k. [stated ans:Q8]
- OpenRouter only. [stated ans:Q2]

**Delta.** `sf.Entropy(top_logprobs=5)` is a declared source. Its member calls get
`top_logprobs: k`. The engine computes the mean entropy in `reply_logprobs`
([logprob-capture](logprob-capture.md)). The evidence `declared` entry holds `top_logprobs`.

## 3. Scenarios and acceptance criteria

**Definition [proposed].** At each content position t, take the first k entries of
`top_logprobs`, with probabilities `p_i = exp(l_i)`. Let `r = max(0, 1 − Σ p_i)` be the mass that the
provider did not list. The position entropy is `H_t = −Σ p_i ln p_i − r ln r` (with `0 ln 0 = 0`), in
nats. The value is the mean of `H_t` over the positions that have at least one top entry. With no such
position, the value is None.

WHY the residual term `r`: without it, the entropy of a truncated list is computed as if the listed
tokens held all the mass. The residual term treats the unlisted mass as one more outcome. It is
deterministic and needs no guess about the tail. [proposed]

### 3.1 Happy path

- **EN-1** Given one position with top probabilities 0.5 and 0.3 (so r = 0.2), then
  `H = 0.5 ln 2 + 0.3 ln(1/0.3) + 0.2 ln 5 = 1.0296530140645737` nats. [proposed]
- **EN-2** Given two positions with H = 0.2 and H = 0.6, then the value is 0.4. [proposed]
- **EN-3** Given `sf.Pick(by_signal=sf.signal("ent"), order="min")`, then the member with the lowest
  mean entropy is picked, and its text is copied. [stated prompt] (behavior 2)
- **EN-4** Given `sf.Entropy()`, then each member call body has `logprobs: true` and
  `top_logprobs: 5`, and the evidence `declared.ent.top_logprobs` is 5. [stated ans:Q8]

### 3.2 Error paths

- **EN-E1** Given `top_logprobs` of 0, 21, a bool or a float, then `sf.Entropy` raises `ValueError`.
  [stated ans:Q8]
- **EN-E2** Given `sf.Vote(weights=sf.signal("ent"))` (or Median or Mean weights), then the Fusion
  constructor raises `ValueError`: higher entropy means LESS confidence, so use
  `Pick` or `Rank` with `order="min"`. [proposed]
- **EN-E3** Given a non-OpenRouter member or a Recipe member, then the Fusion constructor raises
  `ValueError` (as LP-E2, LP-E3). [stated ans:Q2]

### 3.3 Derived scenarios (risk-ordered)

- **EN-D1** (H×M) [proposed] Given rounding, so that `Σ p_i > 1`, then `r = 0` and the value stays
  finite and ≥ 0.
- **EN-D2** (H×M) [implied] Given a position with an empty `top_logprobs` list, then that position is
  skipped.
- **EN-D3** (M×M) [proposed] Given one position with top probability 1.0 (`logprob` 0), then H = 0.
- **EN-D4** (M×M) [implied] Given a declaration of `sf.Logprob` and `sf.Entropy` together, then the
  calls ask once (`logprobs: true`, `top_logprobs: k`), and both values come from the same reply.
- **EN-D5** (M×L) [proposed] Given k = 20 and a long reply, then the reply may pass the 1,000,000-byte
  cache cap or the 2,000,000-byte frozen-copy cap; the README says to keep k small for a reproducible
  replay. (ans:Q8 tradeoff)
- **EN-D6** (H×M) [proposed] Given a position whose chosen token is absent from its top-k list, then
  the position entropy uses the top list only. This is valid.
- **EN-D7** (H×M) [proposed] Given one top entry that is not a finite number ≤ 0, then the entropy is
  None, and the logprob values of the same reply stay (LC-D2).
- **EN-D8** (M×M) [proposed] (review M1) Given a Fusion with a `sf.Entropy` declaration, then its url4
  rebuilds to Python with `top_logprobs` in the declaration, and the members carry no injected
  `logprobs` or `top_logprobs` param.

## 4. Non-functional requirements

- O(n × k) per reply. [proposed]
- The value is in nats, ≥ 0. The README states the unit. [proposed]

## 5. Out of scope

- Other summaries (max entropy, entropy of the answer span only). [stated prompt] ("mean entropy is
  enough for v1")
- Two entropy sources with different k on one Fusion (DS-I2). [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: core-out. The formula first, with hand-computed oracles.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `entropy_with_residual_mass` (EN-1 oracle) | unit | EN-1 | H×M | in `reply_logprobs` |
| 2 | `entropy_is_the_mean_over_positions` | unit | EN-2 | H×M | — |
| 3 | `entropy_clamps_residual_at_zero` | unit | EN-D1 | H×M | `max(0, …)` |
| 4 | `entropy_skips_positions_without_top_entries` | unit | EN-D2 | M×M | — |
| 5 | `entropy_of_a_certain_token_is_zero` | unit | EN-D3 | M×M | `0 ln 0 = 0` |
| 6 | `entropy_refuses_bad_k` | unit | EN-E1 | M×M | 1..20, int, not bool |
| 7 | `vote_weight_refuses_entropy_with_an_order_min_hint` | unit | EN-E2 | H×M | in the `sf.Fusion` constructor |
| 8 | `entropy_compiles_top_logprobs_on_each_member_call`, and refuses a non-OpenRouter or Recipe member | unit | EN-4, EN-E3 | H×M | member params; the LP#5 check |
| 9 | `pick_min_by_entropy` | integration | EN-3 | H×M | `run_candidate`, fake top lists |
| 10 | `logprob_and_entropy_share_one_reply` | integration | EN-D4 | M×M | — |
| 11 | `entropy_with_the_chosen_token_outside_the_top_list` | unit | EN-D6 | H×M | — |
| 12 | `bad_top_entry_gives_none_entropy_and_keeps_logprob` | unit | EN-D7 | H×M | LC#17 |
| 13 | `entropy_fusion_rebuilds_from_url4_without_injected_params` | unit | EN-D8 | M×M | `to_python`; DS#16 |
