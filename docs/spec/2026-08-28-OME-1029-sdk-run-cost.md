# OME-1029 — Send run_cost_usd on leaderboard submissions

**Ticket:** [OME-1029](https://linear.app/openmined/issue/OME-1029/send-run-cost-usd-on-leaderboard-submissions-from-the-sdk)
· **Ledger:** `docs/work/2026-08-28-OME-1029-sdk-run-cost.md`
· **Stack:** screamingface (SDK) · **Date:** 2026-08-28

The ticket carries the full problem statement. This records what was verified against the code
before building, and the decisions the ticket left to implementation.

## 1. Facts, re-verified 2026-08-28 against `origin/main` at `dd51ea81`

| # | Finding | Evidence |
|---|---|---|
| F1 | The root subtree usage — the whole run's total — is captured | `_engine/contract.py`: `_root_usage` assigned only when `envelope["source"] == self._root_source` **and** `usage_event.scope == "subtree"` |
| F2 | It reaches the result the SDK submits from | `_evaluation/results.py`: `usage=outcome.root_usage or Usage()` |
| F3 | `run_cost_usd` appears **nowhere** in `packages/` or `apps/screamingface-engine` | `git grep -l run_cost_usd` over both returns nothing |
| F4 | `_submission()` builds the payload without it | `_scoreboard/leaderboards.py` — version, benchmark_id, spec_id, url4_expression, score, total_questions, ran_with_providers, ran_at_local, client, metadata |
| F5 | The payload is handed to `json=` on the HTTP call | `Leaderboards.submit` / `AsyncLeaderboards.submit` |
| F6 | The live board confirms the consequence | `GET /v1/leaderboard/draco` → `entries=0, with a cost=0` |

**F5 is the implementation constraint.** `json=` serialises with `json.dumps`, which raises
`TypeError` on a `Decimal`. The value cannot be passed through as-is.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Serialise as a **decimal string**, via `str()` | F5 forbids a raw `Decimal`, and `float` would corrupt money — the column is `DECIMAL(12, 6)`. `str()` is already the SDK's idiom for this exact value: `_report_primitives.py` does `None if self.cost_usd is None else str(self.cost_usd)`. Scoreboard's `ScoreSubmission.run_cost_usd` is `Decimal \| None`, and Pydantic parses a decimal string exactly. |
| D2 | `None` is sent as `null`, **never coerced to `0`** | Absent means "no cost was reported". `0` means "this run genuinely cost nothing", which a fully cache-served run legitimately does. `OME-770` D10 and `OME-923`'s frontier exclusion rule both depend on telling those apart — a null read as zero would put an unpriced run on the cheapest end of the Pareto frontier. |
| D3 | No client-side normalisation | Quantization, sub-quantum rounding and sign-zero already live in Scoreboard's schema. Re-implementing them here would create a second, divergent contract for the same value. |
| D4 | No backfill, and the dedup interaction is left as-is | `content_hash` excludes cost by design (`OME-391`, `OME-770` D8), so a recipe already submitted without a cost cannot gain one — the resubmission dedups and the incoming cost is discarded. This stops the case arising going forward; existing rows keep `null` permanently. |

## 3. Design

One key in `_submission()`:

```python
"run_cost_usd": _cost_text(candidate_result.usage.cost_usd),
```

with a helper returning `None` for `None` and `str(value)` otherwise. Both the sync and async
submit paths share `_submission()`, so both are covered by one change.

## 4. Out of scope

`MemberResult.duration_ms` is declared and hardcoded `None`. Run timing is the other axis
`OME-324` needs, has no Scoreboard column at all, and its definition is an open product question.

Making cost **required** is `OME-822`, which this unblocks rather than performs.

## 5. Acceptance

- A priced run submits a non-null `run_cost_usd` and the stored row is non-null.
- An unpriced run submits successfully with `null` — never `0`.
- A run genuinely costing nothing submits `0`, distinct from absent.
- The value crosses the wire as a decimal string, never a float.
- Every other field of the payload is unchanged.
- Full gates green, including the 95% coverage floor and the notebook determinism check.
