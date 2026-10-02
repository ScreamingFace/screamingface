# PRD: Weighted vote, argmax and top-k over a named signal

**Source:** PRD Reduce ops `weighted` ("weight = a named signal"), `argmax` ("over a named
signal"), `top_k`; criterion A3 · ans:Q4 · **Priority:** P1
**Lifecycle:** existing (characterize + delta) — fixed weights, judge/field argmax and Rank exist
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md). Uses [signals](signals.md),
[block-api](block-api.md), [answer-record](answer-record.md).

## 1. Summary and user story

As a researcher, I want to weight a vote by a signal, and to pick the best one or best k members by
a signal (for example the cheapest correct-looking answer, or the highest self-reported
confidence), so that I can rerun confidence- and cost-aware joins without code.

## 2. Background and constraints

- "`weighted` (weight = a named signal), `argmax` (over a named signal), `top_k` … Every op
  records its tally and the chosen `member_id`s." `[stated prompt]`
- E4a sources: member JSON fields, judge scores, per-call accounting `[stated ans:Q4]`
  ([signals](signals.md)).
- Weights must keep the summed score finite: each weight ≤ `sys.float_info.max / 256`
  `[existing E/combine/spec.py:45]`.

### 2.1 Current behavior

- `sf.Vote(weights=[2, 1, 1])`: fixed positive weights per member → `weighted_mode@1` +
  `max_weight_holder@1` `[existing E/combine/operators/reduce.py:68]`.
- Argmax exists only over judge scores (`sf.Judge(returns="scores")` → `max_score@1`) and over a
  JSON field (`sf.Pick(field, order="max")` → `by_field@1`) `[existing E/combine/operators/judge.py:144]`
  `[existing E/combine/operators/fields.py:201]`.
- `sf.Rank(k, by=… | by_field=…)` → `top_k@1`, highest first; k > 1 returns a selection envelope
  `[existing E/combine/operators/selection.py:50]`.

**Delta.**
1. Spec `weights` accepts `{"signal": "<key>"}` ([erd.md §5](../erd.md#5-changes-to-combinespec-screamingfacecombine-specv1-edited-in-place)).
   `weighted_mode@1` reads each voter's weight from `Answer.signals[key]`.
2. New reduce op `by_signal@1` (`key`, `order`): member scores from a signal (the core resolved
   the values before reduce, [signals](signals.md) delta 4). `top_k@1` gains the arg `order` (`max`
   default, `min`).
3. **argmax** compiles to `by_signal@1` + a new select `best_holder@1` (`order`) that returns **one
   member's original text** with `output=None`, like `max_score@1`
   `[existing E/combine/operators/judge.py:110]`. It is an answer, so it can be the last stage.
   (`top_k@1` always returns the selection envelope `[existing E/combine/operators/selection.py:68]`,
   so `sf.Rank(k=1)` is not an argmax.)
4. SDK: `sf.Vote(weights=sf.signal(key))`; `sf.Pick(by_signal=sf.signal(key), order="max"|"min")`
   (argmax); `sf.Rank(k, by_signal=sf.signal(key), order=…)` (top_k). Blocks:
   `sf.Reduce("weighted", weights=…)`, `sf.Reduce("argmax", by_signal=…, order=…)`,
   `sf.Reduce("top_k", k=…, by_signal=…)`.
5. Evidence `signal = {"key", "order"}`; each member row carries the signal value it was read with.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **SR-1** Given members that reply JSON with `answer` and `confidence` (0.9, 0.3, 0.4) and
  answers `"A"`, `"B"`, `"B"`, when `sf.Reduce("weighted", extract=sf.Extract("field",
  path="answer", normalize="text"), weights=sf.signal("field:confidence"))` runs, then `"A"` wins (0.9 > 0.7) and the tally shows
  scores 0.9 and 0.7. `[stated prompt]`
- **SR-2** Given 3 members with costs 0.004, 0.001, 0.002, when
  `sf.Reduce("argmax", by_signal=sf.signal("cost_usd"), order="min")` (= `sf.Pick(by_signal=…,
  order="min")`) runs as the last stage, then member_2's original text is the Case output and
  `chosen == ["member_2"]`. `[stated prompt]` `[stated ans:Q4]`
- **SR-3** Given `sf.Rank(k=2, by_signal=sf.signal("field:score"))`, then the 2 highest members
  are kept in score order. `[stated prompt]`
- **SR-4** Given the same url4 replayed, then the output and the tally are the same (A3 replay).
  `[stated prompt]`

### 3.2 Error paths

- **SR-E1** Given `weights=sf.signal("cost_usd")` on `sf.Median`, then `TypeError` (weights are
  only for vote) `[existing S/reducer.py:218]`.
- **SR-E2** Given `sf.Rank(k=2, by=…, by_signal=…)` (two sources), then `ValueError`. `[implied]`

### 3.3 Derived scenarios (risk-ordered)

- **SR-D1** Missing weight `[proposed]` (H×M): a voter whose weight signal is `None`, ≤ 0, not
  finite, or > `sys.float_info.max / 256` does not vote. Its row keeps `weight: null`. If no voter
  is left → abstain `no_votes` ([abstain](abstain.md)).
- **SR-D2** Missing argmax signal `[proposed]` (H×M): a member with `None` is not ranked; all
  `None` → abstain `no_votes`; fewer than k ranked → abstain `cut_not_met`.
- **SR-D3** Ties `[existing E/combine/operators/selection.py:50]` (M×H): equal signal values →
  author order decides; `tie: true` in evidence.
- **SR-D4** `order="min"` with negative values `[proposed]` (M×L): the smallest value wins; the
  tally shows the raw values, not negated ones.
- **SR-D5** Cost on a cache hit `[stated ans:Q9]` (M×M): a replay from cache reads the original
  call's cost from the cache reference ([signals](signals.md) SG-D1), so SR-4 holds on a cached
  replay.
- **SR-D6** Fixed weights unchanged `[existing E/combine/operators/reduce.py:68]` (H×M): every
  existing weighted-vote golden case stays green.
- **SR-D7** Judge signal as weight `[stated ans:Q4]` (M×L): `sf.Vote(weights=sf.signal("score:judge"),
  judge=sf.Judge(…, returns="scores"))` weights each voter by its judge score; the judge call is
  one call, as today.

## 4. Non-functional requirements

- No new model call (accounting and fields are already there; a judge is declared explicitly)
  `[implied]`.
- p99 budget unchanged (E4a K4) `[implied]`.

## 5. Out of scope

- `logprob`-weighted votes (E4b) `[stated ans:Q4]`.
- A weight transform (inverse, log) `[proposed]` (future; `order="min"` covers "cheapest").

## 6. Open questions

None.

## 7. TDD plan

Risk-first: missing-signal behavior before the happy path.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: fixed-weight goldens stay green | unit | SR-D6 | — | passes today |
| 2 | `voter_with_missing_or_invalid_weight_signal_does_not_vote` | unit | SR-D1 | H×M | `weighted_mode@1` reads `signals[key]` |
| 3 | `all_weights_missing_abstains` | unit | SR-D1 | H×M | abstain path |
| 4 | `vote_weighted_by_field_signal_picks_heaviest_answer` | unit | SR-1 | H×H | spec `weights: {"signal": key}` |
| 5 | `argmax_min_returns_cheapest_member_text_as_answer` | unit | SR-2, SR-D4 | H×H | `by_signal@1` + `best_holder@1(order=min)` |
| 6 | `missing_argmax_signal_is_not_ranked_and_short_cut_abstains` | unit | SR-D2 | H×M | — |
| 7 | `signal_ties_go_to_author_order` | unit | SR-D3 | M×H | existing tie rule |
| 8 | `rank_by_signal_keeps_top_k_in_order` | unit | SR-3 | M×M | — |
| 9 | `median_rejects_signal_weights` / `rank_rejects_two_sources` | unit (SDK) | SR-E1, SR-E2 | M×M | — |
| 10 | `signal_reduce_replays_identically_from_cache` | integration | SR-4, SR-D5 | H×M | — |
| 11 | `judge_score_signal_weights_a_vote` | integration | SR-D7 | M×L | — |
| 12 | `evidence_records_signal_key_order_and_values` | unit | delta 4 | M×M | evidence `signal` |
