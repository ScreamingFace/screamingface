# Plan — E4a gap closure (OME-1289)

**Spec:** [docs/spec/2026-10-02-e4a-gap-closure/](../spec/2026-10-02-e4a-gap-closure/00-overview.md) ·
**Ledger:** [docs/work/2026-10-02-e4a-gap-closure.md](../work/2026-10-02-e4a-gap-closure.md)

## 1. Approach

The work **folds into the existing 15 local stack units** `[stated ans:Q8]`. Each change goes into
the lowest unit that owns the code it touches, and each test goes into the first unit where the
reducer it uses exists. After a unit changes, every unit above it is cascade-rebased before the next
unit starts, and every branch is gated on its own. Nothing is pushed and no PR opens until the user
says so.

Per unit: Opus writes the unit spec from the PRD rows below → a Sonnet implementer works TDD (RED
first) in that unit's worktree → an Opus design-reviewer checks it against the spec → one fix round →
cascade rebase → gates per branch.

**Fold rule for tests.** A test file the stack added is not on `origin/main`, so the fold may change
it in place. A test file on `origin/main` stays append-only. The two owner-approved edits to `main`'s
tests stay the only ones: owner-approved edit #1 (`test_failure_classes.py`, the new codes) now pins
three new codes instead of four (G6); this is the same approved edit, not a new one.

**Unit 1 has no operators yet** (the registry is empty until unit 2), so unit 1's core tests use
test-only operators defined in the test module, as the existing core tests do.

## 2. Fold map (stack order)

Row ids are `<prefix>#<n>` from each PRD's TDD table (AR answer-record, SG signals, BK block-api,
AB abstain, RX extract-rules, GP grader-parity, SR signal-reduce, FL filter, FR fusion-recipe,
RT report-trace, BU budget-schema). Every row appears once; BK#4, SR#9 and SR#11 are parametrized rows split across
units by their parts.

| # | Unit (branch) | Gap work folded in | Rows |
|---|---|---|---|
| 1 | `e4a-combine-core` | Answer status/reason, `result`, `dropped`, `signal` in core and evidence; `NoVotes(reason)` → abstain; field-path walk written in `ports.py`; core signal resolution; `context.sources` parse; adapter exact-one fingerprint lookup + recorder accessor in `operation_calls.py`; `SignalAccounting` computed in `connector.py` `_observed_round_trip` and combined at both record sites; abstain output `""`; remove `combine_no_votes` (engine + SDK mirror) | AR#1–8, AR#15; SG#1–3, SG#7–8, SG#10–12, SG#14, SG#16–19; AB#1–2, AB#5–8, AB#16, AB#19–20 |
| 2 | `e4a-answer-operators` | `regex@1` (ban, window, timed golden), `set@1`; vendored `_inspect_vendor.py`; `inspect_number@1`, `inspect_aime@1`, `inspect_numeric@1`; parity corpus + drift guard (Inspect lane); `json_field@1` imports the path walk from `ports.py`; `weighted_mode@1` reads a signal weight | RX#1, RX#1b, RX#2–9, RX#12; GP#1–7, GP#13; SR#1–4 |
| 3 | `e4a-engine-wiring-evidence` | catalog entries for the new ops; `answer_rule` on `BenchmarkSpec`/`Benchmark` + catalog; abstain mark in `invocation.py` carried through the invocation decoder, `CandidateAnswer`, Case records, `CandidateFields`; score replacement in `BenchmarkAggregation`; Case wire `abstained` | RX#10; GP#8, GP#16; AB#9–15, AB#18, AB#21–22 |
| 4 | `e4a-sdk-reducer-slot` | `ReducerPlan` seam (no named reducer yet); `sf.Extract`, `sf.Reduce`, `sf.signal`, `sf.matches`, `sf.Answer` construction and validation; Answer decode; `CaseResult.abstained` + count; `case.trace()`, `Report.trace_dict()` over fixture evidence | BK#5–7, BK#9–11, BK#13; SG#4; AR#9, AR#12–14, AR#16; AB#17; RT#5–15, RT#17; RX#11; BU#8 |
| 5 | `e4a-vote-median` | `sf.Vote`/`sf.Median` build a `ReducerPlan`; `plurality`, `median` rows; recovery prefers the named class; `case.answers()` join; vote trace; `extract="benchmark"` resolution before spend; per-benchmark url4 | BK#1–3, BK#4 (plurality, median), BK#8, BK#14; AR#10–11; RT#1, RT#4; GP#9–12, GP#14–15 |
| 6 | `e4a-samples` | self-consistency in block form | BK#12 |
| 7 | `e4a-weighted-vote` | `sf.Vote(weights=sf.signal(…))`, `weighted` row; Median rejects signal weights; compile emits `sources` (expression-wide claimant count, canonical params) | BK#4 (weighted); SR#9 (median part), SR#10; SG#5–6, SG#9, SG#20 |
| 8E | `e4a-judge-pick-engine` | `parse_scores` moved into `ports.py`; `score:judge` signal | SG#13; SR#11 (engine part) |
| 9E | `e4a-pick-merge-engine` | Merge / projection / `by_field@1` abstain reasons | AB#4 |
| 10E | `e4a-rank-concat-engine` | `by_signal@1`, `best_holder@1`, `top_k@1` arg `order`, `filter@1`, `kept@1`, reducer `filter`; top-k cut abstain; evidence `signal` | SR#5–8, SR#12; FL#1–5, FL#10; AB#3 |
| 8S | `e4a-judge-pick-sdk` | `judge` row; `sf.Vote(…, judge=…)` with `score:judge` weights | BK#4 (judge); SR#11 (SDK part) |
| 9S | `e4a-pick-merge-sdk` | `pick_field`, `merge`, `argmax` rows; `sf.Pick(by_signal=…, order=…)` | BK#4 (pick_field, merge, argmax) |
| 10S | `e4a-rank-concat-sdk` | `top_k`, `concat`, `filter` rows; `sf.Rank(by_signal=…)`; `sf.Filter`; the Fusion rewrite; README/public-docs Fusion goldens first (CHAR) | BK#4 (top_k, concat, filter); SR#9 (rank part); FL#6–9; FR#1–12 |
| 11 | `e4a-e2e-replay` | Fusion regression replay lane next to EV-12 (skips until recorded); cached-replay signal and trace checks | FR#13; SG#15; RT#16 |
| 12 | `e4a-combine-hardening` | schema snapshots + freeze tests; `budget.v1` records (engine pydantic + SDK dataclasses) and the pure charge rule over `SignalAccounting`; regenerated shared evidence fixture (I-E5); CHANGELOG, README (signals replay note SG-D13, HealthBench abstain note) | RT#2–3; BU#1–7, BU#9–10 |

## 3. Order and dependencies

```mermaid
flowchart LR
  U1[1 core: Answer, abstain, signals] --> U2[2 operators: regex, set, inspect]
  U2 --> U3[3 wiring: catalog, answer_rule, abstain score]
  U3 --> U4[4 SDK slot: blocks, Answer, trace]
  U4 --> U5[5 vote + benchmark rule] --> U6[6 samples] --> U7[7 weighted + sources]
  U7 --> U8E[8E judge eng] --> U9E[9E pick eng] --> U10E[10E rank/filter eng]
  U10E --> U8S[8S judge sdk] --> U9S[9S pick sdk] --> U10S[10S rank/filter sdk + Fusion rewrite]
  U10S --> U11[11 replay lanes] --> U12[12 freeze + hardening]
```

Units run one at a time in stack order. Units 1, 3 and 4 are the largest.

## 4. Gates per branch

- `uv run .claude/scripts/run_gates.py <stack> --base <parent branch>` for each touched stack
  (`screamingface-engine`, `screamingface`, `repo`); `--skip-append-only` only for the known offenders
  (the two owner-approved test edits and the regenerated public-surface snapshot).
- Inspect lane: `uv run --extra inspect pytest apps/screamingface-engine/tests/unit/inspect` on units
  2 and 3.
- The tip: every stack green; merges cleanly with the current `origin/main`.

## 5. Exit criteria (E4a)

| Criterion | Closed by | Status after the fold |
|---|---|---|
| A1 Answer | answer-record | met (typed record; url4 stays text by ans:Q2) |
| A2 Extract = grader | grader-parity, extract-rules | met for the benchmark rule on GSM8K and AIME; MATH waits (ans:Q5); built-in rules differ by design |
| A3 Reduce ops replay | block-api, signal-reduce, filter, signals | met (7 ops; cached replay identical, ans:Q9) |
| A4 Fusion byte-identical | fusion-recipe | met (`context`, not `concat`; needs Irina's sign-off) |
| A5 self-consistency | already met; BK#12 | met; live proof at the EV-12 recording (U5) |
| A6 Report entries | report-trace | met (separate `report-trace.v1`, ans:Q13) |
| S1 schemas frozen | report-trace RT-D1, budget-schema, erd §10–11 | met for Answer, spec, evidence, trace, Budget (method-owner side; E4c enforces) |

## 6. User actions

1. ~~Approve the spec and this plan~~ — approved 2026-10-02.
2. ~~O1, O2~~ — decided (ans:Q15, ans:Q14).
3. Record the two replay lanes (EV-12 and Fusion), under $0.10 each, when the unit 11 PR opens (U5).
4. Irina signs off the `concat` → `context` deviation ([fusion-recipe §2](../spec/2026-10-02-e4a-gap-closure/prd/fusion-recipe.md)).
