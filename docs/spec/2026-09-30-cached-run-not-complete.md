# Stop publishing a cached run's spend as a complete cost

Parent: `OME-1251`. Answers the open question on `OME-1143` ("what does the board publish when
cache hits cannot be priced?") for the interim until `OME-1382`.

## Problem

A cache hit costs nothing upstream, so a cached run's spend (`usage.cost_usd`) is at or near $0.
The SDK derives `run_cost_status = "complete"` whenever that spend is priced
(`_evaluation/results.py:180`), and the board ranks on spend. A fully cached run therefore lands on
the Pareto frontier at ~$0, marked exact. Measured on dev 2026-09-30: 461,697 of 464,234 cache
entries (99.5%) carry no provider-reported price, so a cached run cannot supply a real saving either.

## Decision (owner, 2026-09-30)

| # | Decision |
| -- | -- |
| D1 | **Any cache hit** makes a submission non-`complete`, until `OME-1382` ranks on spend plus saving. Then relax to "any hit without a `reported` price". |
| D2 | Such a submission is `partial` with **no amount**: today's board contract (`schemas.py:547`) refuses an amount beside `partial`. It leaves every cost surface and the frontier. The score still publishes. |
| D3 | **SDK only.** Board-side enforcement for older clients (the SDK sends its hit counts; the board downgrades) is a separate follow-up under `OME-1251`. |
| D4 | **Public addition approved:** read-only `CandidateResult.cache_hits: int`, serialized in `to_dict`. The public-surface snapshot is regenerated for exactly this change. |
| D5 | **Unknown means partial** was approved for reloaded reports, but the SDK has no reload path: a `CandidateResult` is built only by a live run (`_evaluation/results.py:130`), which always knows its count. So the field is `int` with default `0` for hand-built results (keeps every prior test unchanged); a live run always sets it. |

## Design

**Where the rule applies: at submission, not on the result.** `CandidateResult` enforces
"`complete` iff an amount is present" (`report.py`, `_run_cost_status`) and reports what the run
SPENT, which stays true for a cached run. Changing the result would lose the local spend and break
that invariant. Only the published claim changes, so `_submission` applies the rule.

**Where the count comes from.** The engine's run summary log (`ai.url4.log`, emitted whenever the
run touched the cache, `executor.py` `counters.observed`) carries `cache.hits`: every gateway round
trip that hit, counted before any span guard (`cache_counters.record`). That is the authoritative
figure. A span's `cache_status` keeps only its LAST call's outcome (`executor.py:467`), so a span
whose first call hit and whose later call missed reads `miss`; counting spans alone can under-count,
and DRACO candidates run with `web_search=true`, which makes several calls on one span.

The contract therefore takes `cache_hits = max(summary cache.hits, spans with cache_status == "hit")`.
The span count is only a fallback for an engine that sends no summary; the maximum never
under-reports either source. It is carried on `_RunOutcome.cache_hits`, and `CandidateResult`
exposes it read-only.

**Payload rule** (`_scoreboard/leaderboards.py::_submission`):

| `cache_hits` | `run_cost_status` sent | `run_cost_usd` sent | `cache_saved_cost_usd` sent |
| -- | -- | -- | -- |
| 0 | as today | as today | as today |
| > 0 | `partial` | omitted | as today (when present) |

`partial` beside a saving, and `partial` without one, are both accepted by the board today
(`schemas.py:476-505`), so no board change is needed.

## Consequences

- A `no-store` run (all bypasses, zero hits) publishes its real spend as `complete`, unchanged.
- A mostly-uncached run with one hit loses its published amount. Accepted (D2): showing a lower
  bound needs a board contract change, deferred.
- Older SDK versions still publish `complete` at $0 until the follow-up (D3) lands.
- A hit on a retried call is still a hit; it counts.

## Out of scope

- Ranking on spend plus saving (`OME-1382`).
- Board-side enforcement and hit counts on the wire (D3 follow-up).
- Deleting unpriced cache entries.
