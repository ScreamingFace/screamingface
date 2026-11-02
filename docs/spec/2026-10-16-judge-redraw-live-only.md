---
ticket: OME-1646
status: approved-direction (owner, 2026-10-16)
date: 2026-10-16
related: OME-1642 (score denominator report), OME-1527 (local Task migration, PRs #1321 #1324 #1395)
---

# A recorded judge reply is final: redraw only after a live reply

## 1. Problem

The Engine must reproduce a Benchmark's reference score exactly when it replays recorded
answers and verdicts. DRACO is the check for this, because we hold the raw data of the
reference run (`20260806-170633-251a`: per-row answers, per-criterion verdicts for each pass,
and the published per-model scores).

Since 2026-10-14 the Engine no longer reproduces DRACO. The cause is not the score average.
The cause is the judge redraw.

## 2. What the raw data says (measured 2026-10-16)

1. A model call that completes is an answer, also when its text is empty. The judge grades
   it, and the row counts in the model's mean (claude-fable-5: 8 empty answers, each 0.0,
   in the count of 100).
2. A model call that fails gets no score and the mean leaves it out (gpt-5.6-sol: 6 error
   rows; published 0.6481 is the mean of 94 rows; with the 6 rows as 0 it would be 0.6092).
3. The judge is asked once per criterion per pass. A criterion with no verdict in a pass
   leaves that pass. Nothing asks the judge again (gemini-3.1-pro case `4f36f602`:
   `verdict_coverage` 0.9603, score 0.4116).

The Engine's score average already follows rules 1 and 2. It does not follow rule 3 since
PR #1395.

## 3. Root cause

A **redraw** is the Engine asking the judge the same question again because its reply had
no usable verdict (`screamingface_engine_inspect/judge_redraw.py`, `judge_until_parsed`, at
most 2 redraws, each outside the gateway cache). It was added in PR #1321 for live runs: a
garbled live reply is a successful call, and the cache would hand it back on every re-ask.

PR #1395 moved DRACO onto this helper. In a replay, every judge reply comes from the gateway
cache, including the seed rows that record "no verdict" on purpose. The helper treats each
of them as a garbled reply and sends a fresh, paid, live call. When that call gives a
verdict, the criterion (or the whole Case) is counted, and the score no longer matches the
recording.

## 4. Rule (owner decision, 2026-10-16; applies to every judge call)

- **R1.** A redraw happens only after a **live** reply: one the gateway got from the
  provider in this call.
- **R2.** A reply served from the gateway cache, or from a frozen-copy replay, is final. If
  it has no verdict, the item has no verdict: no redraw, no other call.
- **R3.** Retries after a failed call (a 429 or 5xx) do not change. A failure is never
  cached, so such a call is always live.
- **R4.** When the Engine cannot tell where a reply came from (no cache outcome reported),
  the reply counts as live, which is today's behaviour.

The Engine already knows the origin of each round trip: the connector reads the gateway's
cache outcome (`CacheOutcome.status`, `hit` = served from the cache) and knows when it
replays a frozen copy (`replay_frozen_copy`). This change carries that fact from the
connector to the judge step.

Scope of "every judge call": all four scorers that call `judge_until_parsed` today (DRACO,
GDPval-text, HealthBench, FRAMES). The url4 `;retry=` path in `world/fresh_judge_retry.py`
has no raise site that retries today (the combine Judge's `judge_reply_invalid` is
permanent); its docstring states R2 for a future raise site.

## 5. Effect on a replay of the DRACO reference

- A seed row with no verdict (`fill_pass_gap`) → that criterion leaves that pass, as in the
  reference.
- A Case whose seed rows all have no verdict (`fill_answer_absent`, the 7 error rows) → the
  Case fails as `judge_reply_invalid` and the mean leaves it out, as in the reference.
- No paid call.

A live DRACO run still redraws a garbled live reply (R1).

## 6. Out of scope

- The score denominator (OME-1642). The reference leaves error rows out, and the Engine does
  the same. A gap on another Benchmark (FrontierScience) needs that Benchmark's own raw data.
- Storing a live redraw's good reply in the cache. A redraw opts out of the cache in both
  directions (`participate=False`), so a later replay of a live run that needed a redraw
  sees the first, garbled reply, and under R2 keeps "no verdict". The fix needs a gateway
  "refresh" control (aigateway + url4 `CachePolicy`) and is a separate unit.
- Cache seed contents and existing leaderboard rows.

## 7. Verification

- **V1 — connector.** A round trip records its origin: `live` on a miss, `cache` on a hit,
  `replay` for a frozen-copy replay; nothing is recorded outside a watch.
- **V2 — judge provider.** The provider reports the origin of each reply, also on a blank
  reply (`JudgeReplyBlank`).
- **V3 — redraw helper.** A cached or replayed reply without a verdict → exactly 1 call and
  `JudgeReplyUnparseable`; a live one → today's redraws; unknown origin → today's redraws;
  a 502 is still retried.
- **V4 — DRACO reference replay (committed test).** Real DRACO cases from the reference run
  (rubric plus the recorded verdict of each criterion in each pass), replayed by a judge
  whose replies are all marked `cache`. The Case score equals the reference
  `normalized_score` to 4 places, with exactly one call per criterion per pass; the
  all-missing case fails as `judge_reply_invalid`.
- **V5 — full replay (manual, recorded in the ledger).** draco-3pass on the local stack from
  the v3 cache, with no provider key, so a miss fails instead of spending money. Expected:
  0 live calls; each lineup compared with `stats/by_model.csv`. Known older gaps (before PR
  #1395, OME-1501/OME-1526): pareto_lean 0.5456 vs 0.5431, pareto_cross 0.6192 vs 0.6186,
  best_open_source 0.5677 vs 0.5659; each remaining gap is recorded with its cause.
