# Send the archive cache saving; submit a fully priced cached run as complete

Ticket `OME-1463`, parent `OME-1251`. SDK half of decision D7. Board half: `OME-1382` (PR #1227).

## Problem

`OME-1441` (#1187) sends any run with a cache hit as `partial` with no amount, because the board
ranked on spend alone and D3 kept archive-matched money off the board. D7 reverses D3, and the
board now sums spend + reported saving + archive saving. Under the old rule, a run served from the
draco-cache-seed archive can never publish a cost, although every one of its hits is priced.

## Decision (owner, 2026-10-02: D7 on OME-1251)

| # | Decision |
| -- | -- |
| D1 | Archive-matched money is published. The SDK sends it as `cache_saved_cost_archive_usd`, beside the spend and the reported saving, never added to either. The board sums. |
| D2 | A run with cache hits is `complete` (with the spend as `run_cost_usd`) when every hit carries a price, reported or archive. |
| D3 | It is `partial` with no amount when any hit has no price, and also when the SDK cannot prove that none lacks one. A missing price is never counted as $0. |
| D4 | Runs with no hits are unchanged. |

## Where the proof comes from

The engine's run summary log carries `cache.saved_cost.unpriced_hits` (and `reported_hits`,
`archive_hits`), counted per round trip (`runner/cache_counters.py`). It is the authority, but the
engine may drop log events under backpressure (OME-1251 comment of 2026-09-21). Spans carry each
call's prices but keep only their last call's cache outcome, so they cannot prove "no unpriced
hit". Hence:

- summary arrived: `unpriced_hits` from it;
- no summary: unknown (`None`), and any hit sends `partial`.

**Amended in review round 1 (2026-10-03): the summary is the authority for the money too.** The
first version took the proof from the summary but the saving amounts from span frames. The engine
tallies a hit's saving on the summary before checking that the span exists
(`executor._fold_response`), so an unknown span keeps the run-level money and produces no span
total; a run could then claim `complete` with no saving and be ranked at its bare $0 spend. Now:

- with a summary carrying its coverage counts, BOTH savings are the summary's own totals
  (`cache.saved_cost_usd`, `cache.saved_cost_archive_usd`, exact decimal strings; any other
  carrier stops the run);
- `unpriced_hits` is published only when the summary agrees with itself and with the run: every
  coverage count present, `reported + archive + unpriced == hits`, a total present exactly when its
  provenance had hits, and the run's final hit count equal to the summary's. Otherwise `None`, so
  the submission sends `partial`;
- without coverage counts, the span totals are the only amounts, and nothing is proven complete.

The SDK already reads this summary for `cache.hits` (`_engine/contract.py:207`, root source only).

## Published pair (`_scoreboard/leaderboards.py::_published_cost`)

| cache_hits | unpriced_hits | spend priced | `run_cost_status` | `run_cost_usd` |
| -- | -- | -- | -- | -- |
| 0 | any | yes / no | as today | as today |
| > 0 | 0 | yes | `complete` | the spend |
| > 0 | 0 | no | `partial` | omitted |
| > 0 | > 0 | any | `partial` | omitted |
| > 0 | unknown | any | `partial` | omitted |

Both savings are sent whenever present, decimal strings, omitted when absent (never null).

## Public surface

`CandidateResult` gains `cache_saved_cost_archive_usd: Decimal | None` and
`cache_unpriced_hits: int | None` (None = no run summary), both keyword-only with default None,
both in `to_dict`. Public-surface snapshot and CHANGELOG updated. The local `run_cost_status` keeps
describing the spend, as today.

## Tests that change

Planned: `tests/test_cached_run_not_complete.py`. In practice it needed no change: its results
never set `cache_unpriced_hits`, so every hit case is "unknown" and still `partial`.

Actually changed (owner approval 2026-10-02): the prior tests that encode D3, "archive money is
never published / never evidence", in `tests/test_cache_saved_cost_submission.py` and
`tests/test_run_cost_status.py`. Under D7 an archive-only unpriced run is `partial` (the board
refuses `unavailable` beside any saving), and the archive amount appears in exactly its own field.

## Rollout

The board refuses unknown fields (`extra="forbid"`). This PR merges only after the board half of
`OME-1382` is live on dev, confirmed in `/openapi.json`.

## Out of scope

The board half (PR #1227). Board-side enforcement for old clients (`OME-1442`). Replacing the
stored draco-3pass rows (`OME-1384`).
