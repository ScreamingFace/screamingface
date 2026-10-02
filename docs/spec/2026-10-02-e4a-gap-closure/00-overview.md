# E4a gap closure — meet the Method support PRD's E4a criteria (OME-1289)

**Status:** approved by the user on 2026-10-02 · **Branch:** `e4a-deterministic-combine` (docs) ·
**Plan:** [docs/plan/2026-10-02-e4a-gap-closure.md](../../plan/2026-10-02-e4a-gap-closure.md) ·
**Ledger:** [docs/work/2026-10-02-e4a-gap-closure.md](../../work/2026-10-02-e4a-gap-closure.md)

## 1. Summary

The E4a stack (15 local branches, tip `e4a-combine-hardening`) built a deterministic combine
engine from the 2026-09-30 spec. The Method support v1 PRD (2026-10-01) sets E4a acceptance
criteria that the stack meets only in part. Before this spec: 2 met (A5, A6), 2 partial (A3, A4),
2 not met (A1, A2), S1 partial. This spec closes them:

- **A1** a versioned `Answer` record (member_id, text, value, status, reason, signals) on the
  evidence and on the SDK Report; url4 stage hand-offs stay text.
- **A2** the benchmark declares its answer rule; vendored Inspect rules make a vote and a grade
  agree, proven by a parity test against the real scorer on GSM8K and AIME; plus `regex` and set
  equality.
- **A3** the PRD block syntax (`sf.Extract`, `sf.Reduce(op, mode)`) over the same combine call;
  `weighted`, `argmax`, `top_k` over a named signal; a `filter` op. Accounting signals read the
  original call's values, so a cached replay is identical.
- **A4** `sf.Fusion` is the named recipe Fan-out → `Reduce.compute(context)` → Model; the block form
  rewrites to today's url4 bytes.
- **A6 / S1** a per-Case trace exported as `screamingface.report-trace.v1` beside the unchanged
  `report.v1`, and frozen v1 schemas, including the shared Budget schema (method-owner side).
- **V4** a reducer with no usable value **abstains**: the Case scores 0 instead of failing.

No url4 change and no gateway change. Engine files touched: the combine core (`combine/*`) and its
plugins; the adapter `world/combine.py`; `operation_calls.py` (a recorder accessor);
`world/connector.py` (signal accounting per round); `benchmarks/invocation.py` (the abstain mark);
the invocation codec in `benchmarks/contract.py`; `benchmarks/grading_endpoints.py`,
`benchmarks/case_records.py` and `benchmarks/shared_grading/benchmark_aggregation.py` (carry the mark,
replace the score); the benchmark catalog (`benchmarks/definition.py`,
`screamingface_engine_inspect/benchmarks.py`, `rest/benchmarks.py`).

## 2. Subsystems and ownership

| Subsystem | Landing | PRDs |
|---|---|---|
| Combine core, operators, adapter, accounting, invocation record, catalog, Case-result hook | `apps/screamingface-engine` | answer-record, signals, abstain, extract-rules, grader-parity, signal-reduce, filter (engine halves), report-trace (wire snapshots) |
| Blocks, Answer join, trace export, Fusion rewrite, benchmark rule resolution | `packages/screamingface` | block-api, fusion-recipe, report-trace, and the SDK halves of the rest |
| url4, aigateway | — | no change |

## 3. Reading order

1. [erd.md](erd.md) — the records.
2. Component PRDs: [answer-record](prd/answer-record.md) → [signals](prd/signals.md) →
   [block-api](prd/block-api.md).
3. Flow PRDs, risk order: [abstain](prd/abstain.md) → [grader-parity](prd/grader-parity.md) →
   [fusion-recipe](prd/fusion-recipe.md) → [signal-reduce](prd/signal-reduce.md) →
   [filter](prd/filter.md) → [extract-rules](prd/extract-rules.md) →
   [report-trace](prd/report-trace.md) → [budget-schema](prd/budget-schema.md).
4. [contracts.md](contracts.md), then [test-plan.md](test-plan.md), then the plan.

## 4. PRD index

| PRD | Kind | Criterion | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|---|
| answer-record | component | A1 | 3 / 2 / 9 | 16 |
| signals | component | A3 | 3 / 2 / 15 | 20 |
| block-api | component | A3, V1 | 3 / 3 / 7 | 14 |
| abstain | flow | V4 | 3 / 2 / 11 | 22 |
| grader-parity | flow | A2 | 4 / 3 / 8 | 16 |
| fusion-recipe | flow | A4 | 3 / 2 / 9 | 13 |
| signal-reduce | flow | A3 | 4 / 2 / 7 | 12 |
| filter | flow | A3 | 3 / 2 / 5 | 10 |
| extract-rules | flow | A2 | 2 / 3 / 7 | 13 |
| report-trace | flow | A6, S1 | 4 / 2 / 9 | 17 |
| budget-schema | component | S1 | 3 / 2 / 6 | 10 |
| **Total** | | | **35 / 25 / 93** | **163** |

A5 (self-consistency) is already met; the block form is BK-3, and the live proof is the EV-12
recording (U5).

## 5. Interview ledger

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | SDK surface: PRD blocks vs the shipped reducer classes | "Add blocks, keep sugar": `sf.Reduce(op, mode)` and `sf.Extract(rule, normalize)` over the same combine call; `sf.Vote` etc. stay | recommended |
| Q2 | How far "no block boundary carries a string" goes in E4a | "Typed record, text wire": a versioned Answer on the combine input, evidence and SDK Report; url4 stays text | recommended |
| Q3 | No usable value | "Abstain Answer": the combine returns an abstain Answer; the Case is graded, not failed | recommended |
| Q4 | Which signals E4a reducers read | "Seam + E4a sources": `sf.signal(…)`; member JSON fields, judge scores, per-call accounting; logprob with E4b | recommended |
| Q5 | Grader parity | "Vendor rule + benchmark": vendored Inspect rule operators, benchmark-declared rule, `extract="benchmark"`, parity test on GSM8K and AIME; MATH waits | recommended |
| Q6 | Fusion migration | "Recipe lowers to same url4": Fan-out → `Reduce.compute(context)` → Model, lowered to today's url4 | recommended |
| Q7 | How an abstained Case counts | "Counts as wrong": score 0 in the denominator; abstain count shown | recommended |
| Q8 | Where the work lands | "Fold into existing units": change the matching units and cascade-rebase | **not** the recommendation (new units on the tip) |
| Q9 | Accounting signals on a cache hit (review blocker) | "Original call's value": read the cost/latency/tokens the gateway stored with the cache entry | recommended |
| Q10 | Where an abstained Case gets score 0 (review blocker) | "Replace grade at result": graders still run; two Case-result hooks overwrite the grade | recommended |
| Q11 | Trace in the Report | "On by default, report.v2" — **superseded by Q13** (the option text wrongly said report.v1 was unreleased) | recommended |
| Q12 | Per-benchmark url4 with `extract="benchmark"` | "Accept per-benchmark url4" | recommended |
| Q13 | Trace in the Report, with the correct facts (report.v1 released, 5 main tests pin it) | "Separate trace export": `Report.trace_dict()` emits `report-trace.v1`; `report.v1` byte-identical | recommended |
| Q14 | O2: the shared Budget schema | "define it then for our side (method owners)" | E4a defines and freezes `budget.v1` and the charge rule; E4c enforces |
| Q15 | O1: HealthBench abstain score | "yeah, that`s right": keep 0.0 and document it | recommended |
| Q16 | O3: the Fusion recipe uses `Reduce.compute(context)`, not the PRD's `concat` | "ok, that`s fine. consider it approved." | approved by the user |
| Q17 | How `regex@1` is made safe against catastrophic backtracking (the static ban let `(a+){10}$` run 56 s) | "Linear-time engine RE2 (Recommended)": `regex@1` runs on `google-re2`; the deny-list is removed | recommended |
| — | Spec and plan approval | "1 - Approved" (2026-10-02) | code may start |

## 6. Global decisions `[proposed]`

- The fold edits unreleased v1 records and operators in place, then freezes them (erd §10).
- `context.sources` carries each member's model-call fingerprints and appears only when the spec reads
  an accounting signal; the adapter reuses the engine's fingerprint and one-claimant rule.
- The core resolves every signal before reduce; two pure parsers move into `combine/ports.py`.
- argmax returns one member's text (`best_holder@1`); top_k and filter return the selection envelope.
- A Case abstains only when its **final** node is an abstained combine; the invocation record carries
  the mark; abstain is detected only from `result.status`; the abstained Case keeps the grader's
  metrics and checks, and only `score` becomes 0.0.
- Accounting signals use the final successful attempt on a miss and the cache reference on a hit;
  fingerprint claimants are counted over the whole expression.
- `regex@1` bans three backtracking shapes, scans the last 1024 characters, and has a timed golden.
- `extract="benchmark"` may not be combined with an explicit `normalize` in v1.
- No new test dependency: schema freeze uses pydantic `model_json_schema()` snapshots and SDK
  field-set snapshots; property tests use a seeded `random.Random`.
- The PRD's `concat` in the Fusion recipe becomes a structured `context` op (approved, ans:Q16).

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| O1 | ~~HealthBench abstain score~~ | decided ans:Q15: 0.0, documented |
| O2 | ~~Budget schema~~ | decided ans:Q14: [budget-schema](prd/budget-schema.md); E4c enforces, E13 estimates BYOM cost |
| O3 | ~~`concat` → `context` wording~~ | decided ans:Q16: approved |
| D1 | MATH parity | when a MATH benchmark is imported (ans:Q5) |
| D2 | Answer rules for multiple-choice and yes/no benchmarks | follow-up, same mechanism |
| D3 | logprob and other declared signals; the key suffix rule | E4b |

## 8. What changes for related epics

- **E4b** plugs declared signals into `Answer.signals` through the same `sf.signal` seam and adds the
  suffix rule.
- **E4c** reads `Answer.status` (`abstain`) for cascade fallback, enforces `budget.v1` at the call
  layer (charges, refusals, `budget` trace entries), and adds the `branch` trace kind through
  `report-trace.v2`.
- **E14** pins `report.v1`, `report-trace.v1` and the evidence schema with a submission.

## 9. Build errata (2026-10-02)

Found while writing the unit specs. The code follows this list.

| # | Was | Is now | Why |
|---|---|---|---|
| GE1 | I-A1: `value is None` ⇔ `status != "answered"` | one direction: `status != "answered"` ⇒ `value is None`; the core rejects an answered member with no value only when the spec has an extract step | judge and concat members have no extract step, so they answer with no value |
| GE2 | AR-3: a computed Answer's `value` is the built text | `result.value` is the built text for evidence kinds `answer` and `projection`, and `None` for `selection` | a selection (Rank envelope, Concat) contains member text, which evidence never carries (I-E1) |
| GE3 | plan: the `weights: {"signal": key}` grammar is unit 2 work | unit 1 (it owns `combine/spec.py`); the core sets each member's weight from the signal; unit 2's `weighted_mode@1` treats a missing weight as "does not vote" | fold rule: the lowest unit that owns the code |
| GE4 | signals delta 3: `CombineInput.accounting` | the adapter passes an `AccountingReader` port into `run_combine`; values land in `Answer.signals` | the adapter would otherwise parse a context of up to 64 MiB twice |
| GE5 | "keys the spec reads" | an optional `OperatorDescriptor.signal_read` hook declares a reduce op's signal; at most one signal per spec | the core cannot know plugin argument meanings (`by_signal@1` arrives in unit 10E) |
| GE6 | G5 / erd §9: "a grader error on an abstained Case is ignored and logged" | ignored only when the grader still returned grade material (metrics or checks): scored 0.0 with that material. When the grading step left no material (the ladder grading-failure rung, or a hook failure with no metrics and no checks), the Case stays failed and the log says it was abstained | a scored Case with empty metrics breaks `mean_scorer` and `draco_scorer`, and makes a ContractEval positive row a false positive |
| GE7 | erd §9: the mark is `abstained` on every record | the wire keys stay `abstained` (`CandidateInvocation`, `CaseResult`); intermediate url4 records and hoisted `row["case"]` use `candidate_abstained` | ContractEval's check record already has a benchmark verdict key `abstained` |
| GE8 | erd §9: "final node" | the root intent is exactly `$name` and exactly one attributed `op_<name>` exists whose evidence `result.status == "abstain"`; prose intents, other roots and unattributed names are never marked | the design did not define "final node" |
| GE9 | extract-rules RX-D1: a static ban over three backtracking shapes + timed golden; RX-D3: Python `re` Unicode rules | `regex@1` runs on RE2 (`google-re2`, one new engine dependency, the only third-party module a combine plugin may import): linear time, so no ban. RE2 has no lookarounds or backreferences, its repeat limit is 1000, and `\d`/`\w` are ASCII (`\p{L}`/`\p{N}` for Unicode). The SDK pre-spend check (RX#11) adds no dependency: it rejects the RE2-unsupported constructs visible in the stdlib parse tree; the engine's RE2 compile stays authoritative | ans:Q17; a deny-list is never complete (review measured 56 s, 2 s, 3 s bypasses) |
