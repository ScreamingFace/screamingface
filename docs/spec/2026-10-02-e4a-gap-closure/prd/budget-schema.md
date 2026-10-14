# PRD: Budget schema, method-owner side (component)

**Source:** PRD "Budget and Report", "Shared (before any block ships)" · ans:Q14 · **Priority:** P1
(the PRD makes the freeze a gate for week-3 work)
**Lifecycle:** planned (schema and charge rule only; enforcement is E4c)
**Owner:** Ionesio (E4a/E4b) defines and freezes; Sergey (E4c) enforces; Dmitry (E13) supplies
cost estimates for bring-your-own models.

Paths: see [erd.md](../erd.md).

## 1. Summary and the flows it serves

The PRD's Budget is a counter on the request: a unit, a cap, the remaining amount, and the calls it
refused. This PRD defines and freezes the **records** and the **charge rule** for the method blocks
`[stated ans:Q14]`. It does not enforce a cap, estimate a cost, or add a request field; E4c does that
on top of these records.

Flows that use it: E4c cascades and cost-aware compares (read `remaining`), the E4c call layer
(writes charges and refusals), [report-trace](report-trace.md) (the `budget` entry kind).

## 2. Background and constraints

- "Budget is a counter on the request. `unit`: tokens or usd, declared on the request; `cap`;
  `remaining`: decremented by the call layer after every call, cache hits included at their recorded
  cost; `refused[]`: calls not sent because they would exceed the cap: member, estimated cost,
  stage." `[stated prompt]`
- "Enforcement is in the call layer, not in recipes … `budget.remaining` is readable by any compare
  classifier." `[stated prompt]`
- "Report … Budget: spend per call and running remaining; refused calls." `[stated prompt]`
- "Define it then for our side (method owners)." `[stated ans:Q14]`
- `SignalAccounting` already gives each call's **original** cost and tokens, also for a cache hit
  ([erd.md §4.3](../erd.md)) `[proposed]`, which is the PRD's "recorded cost".

## 3. Records (`screamingface.budget.v1`) `[proposed]`

| Record | Fields | Rules |
|---|---|---|
| `Budget` (declared on the request) | `unit: "usd" \| "tokens"`, `cap: float` | `cap` finite and > 0; for `tokens` an integer |
| `BudgetCharge` (one per sent call) | `operation_id`, `member_id \| None`, `stage` (the operation kind: `model`, `synthesis`, `judge`, `writer`), `amount: float \| None`, `source: "live" \| "cache_reference" \| "unpriced"`, `remaining_after: float` | `amount` from the charge rule (§3.1); `None` only when `source == "unpriced"` |
| `BudgetRefusal` (one per call not sent) | `operation_id`, `member_id \| None`, `stage`, `estimated: float`, `reason: "would_exceed_cap"` | written by the E4c call layer |
| `BudgetState` (readable by compares) | `unit`, `cap`, `spent`, `remaining`, `unpriced_charges: int`, `charges: list[BudgetCharge]`, `refused: list[BudgetRefusal]` | `remaining = max(cap − spent, 0)`; `spent` = sum of priced `amount`s |

### 3.1 Charge rule `[proposed]`

`charge(signal_accounting, unit)` is a pure function:

| `unit` | Amount | Source |
|---|---|---|
| `usd` | `cost_usd` | `live` on a miss, `cache_reference` on a hit; `unpriced` when `cost_usd` is `None` |
| `tokens` | `tokens_in + tokens_out` | same; `unpriced` when either is `None` |

An unpriced charge adds 0 to `spent` and 1 to `unpriced_charges`, so `remaining` is then an upper
bound and a compare can see that (`unpriced_charges > 0`).

### 3.2 Readable key

`budget.remaining` is a request-level value for E4c compares, **not** an Answer signal
`[stated prompt]`. `sf.signal("budget.remaining")` is rejected in E4a with a message that names E4c.

## 4. Scenarios and acceptance criteria

### 4.1 Happy path

- **BU-1** Given `Budget(unit="usd", cap=0.01)` and three calls that cost 0.002, 0.003, 0.001, when
  the charges are applied, then `spent == 0.006`, `remaining == 0.004`, and each charge records
  `remaining_after`. `[stated prompt]`
- **BU-2** Given a cache hit whose original cost was 0.002, then its charge is `amount=0.002`,
  `source="cache_reference"` (not 0). `[stated prompt]` ("cache hits included at their recorded cost")
- **BU-3** Given `unit="tokens"`, then a call with 120 input and 30 output tokens charges 150.
  `[stated prompt]`

### 4.2 Error paths

- **BU-E1** Given `cap=0`, a negative, `NaN` or infinite cap, or a non-integer token cap, then the
  record rejects it. `[proposed]`
- **BU-E2** Given `sf.signal("budget.remaining")`, then `ValueError` naming E4c. `[stated prompt]`

### 4.3 Derived scenarios (risk-ordered)

- **BU-D1** Unpriced hit (H×M): `amount=None`, `source="unpriced"`, `spent` unchanged,
  `unpriced_charges` +1.
- **BU-D2** Overrun (M×M): an actual cost above the remaining amount (a wrong E4c estimate) gives
  `remaining == 0`, never negative; `spent > cap` stays visible.
- **BU-D3** Replay (H×M): a cached replay gives the same charges as the first run (same
  `SignalAccounting`), so a budget-gated route replays the same way.
- **BU-D4** Trace (M×M): each charge and each refusal is one `budget` trace entry
  ([report-trace](report-trace.md)); E4a writes none, because no E4a request declares a Budget.
- **BU-D5** Freeze (H×M): `screamingface.budget.v1` is pinned by a `model_json_schema()` snapshot and
  an SDK field-set snapshot; a change needs `v2`.
- **BU-D6** Decimal exactness (M×L): sums use the combine core's decimal context, so 0.1 + 0.2
  gives `0.3` exactly `[existing E/combine/ports.py:44]`.

## 5. Non-functional requirements

- Pure records and a pure function; no I/O; no new dependency `[proposed]`.

## 6. Out of scope

- Enforcing the cap, estimating a call's cost, the request field that declares a Budget, a retry cap
  on the Budget (CorrectiveLoop) — all E4c `[stated prompt]`. BYOM price tables (E13).

## 7. Open questions

None.

## 8. TDD plan

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `budget_rejects_invalid_caps` | unit (engine + SDK) | BU-E1 | M×M | pydantic validators / dataclass checks |
| 2 | `usd_charges_decrement_remaining` | unit | BU-1 | H×H | `charge()` + `BudgetState.apply()` |
| 3 | `cache_hit_charges_original_cost` | unit | BU-2 | H×H | reads `SignalAccounting` |
| 4 | `token_budget_charges_in_plus_out` | unit | BU-3 | M×M | — |
| 5 | `unpriced_charge_counts_but_does_not_spend` | unit | BU-D1 | H×M | — |
| 6 | `overrun_keeps_remaining_at_zero` | unit | BU-D2 | M×M | — |
| 7 | `cached_replay_gives_same_charges` | unit | BU-D3 | H×M | — |
| 8 | `budget_remaining_is_not_an_answer_signal` | unit (SDK) | BU-E2 | M×M | reserved key in `sf.signal` |
| 9 | `budget_schema_matches_snapshot_unless_id_changes` | unit (engine + SDK) | BU-D5 | H×M | snapshots |
| 10 | `charges_sum_exactly_in_decimal` | unit | BU-D6 | M×L | decimal context |
| — | BU-D4 is pinned by the trace kind snapshot ([report-trace](report-trace.md) RT#3) | — | — | — | — |
