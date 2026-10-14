# Test plan — E4a gap closure (OME-1289)

## 1. Strategy

The gap closure changes **wire shapes** (evidence, spec, context, Case), **a Case outcome**
(abstain), **compiled bytes** (the Fusion rewrite) and **replay behavior** (signals on cache hits).
These are the expensive mistakes, so most rigor goes there:

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| Fusion migration changes outputs (leaderboard entries do not reproduce) | H×M | goldens frozen **before** the refactor + byte-identical replay lane | FR#1–3, FR#13 |
| A cached replay changes a signal-based result | H×H | final-attempt values on a miss, cache-reference values on a hit; expression-wide claimant count | SG#2, SG#9, SG#15, SG#19, SR#10 |
| Engine and SDK disagree on a frozen record | H×M | shared fixture from real engine output + schema snapshots | AR#8–9, RT#2–3 |
| Abstain hides a real failure, or breaks a benchmark score | H×M | spec and transport errors stay failures; score replaced per family; grader metrics kept (ContractEval F1) | AB#5–6, AB#11–13, AB#18, AB#22 |
| A vote and a grade disagree (A2) | H×H | parity corpus against the **real** Inspect scorer + drift guard | GP#2–6 |
| ReDoS blocks the worker loop | H×M | three-shape ban, 1024-character window, timed golden | RX#1, RX#1b, RX#6 |
| A missing signal crashes or silently votes | H×M | missing-signal tests before happy paths | SG#9–11, SR#2–3, SR#6, FL#2 |
| Block syntax drifts from the named reducers | M×H | byte-identical url4 per op-table row | BK#3–4 |
| Existing goldens change by accident | H×M | `sources` only when an accounting signal is read | SG#5–6 |

Levels follow the pyramid: unit tests for operators, core rules and decoders (most rows);
integration tests for the adapter, the Case-result hooks and the SDK join; e2e only for the two
replay lanes (EV-12 and the Fusion regression lane).

## 2. TDD ground rules (inherited by every PRD)

- **RED first:** write the test, run it, see it fail on the missing behavior (an assertion, not an
  import error). A test that passes at once proves nothing; fix the test.
- **GREEN minimally;** **REFACTOR on green only.** One behavior per test; the name states the
  behavior.
- **CHAR rows** pin today's behavior and pass on today's code by design.
- **Fold rule** `[stated ans:Q8]`: a test file the stack added may change in place (it is not on
  `origin/main`); a test file on `origin/main` stays append-only. The two owner-approved edits stay
  the only edits to `main`'s tests.
- Golden fixtures: a behavior change is a new `@version`, never an edit — except that the fold edits
  unreleased v1 operators and records in place `[stated ans:Q8]`, and then freezes them.

## 3. Lanes

| Lane | Runs | Command |
|---|---|---|
| Engine unit | every gate | `uv run .claude/scripts/run_gates.py screamingface-engine --base <parent>` |
| Engine Inspect | units 2, 3 | `uv run --extra inspect pytest apps/screamingface-engine/tests/unit/inspect` (GP#1–7, AB#12) |
| SDK unit | every gate | `uv run .claude/scripts/run_gates.py screamingface --base <parent>` |
| Replay lanes | skip until recorded | EV-12 and the Fusion lane (FR#13), recorded together by the user (U5) |
| Repo | every gate | `uv run .claude/scripts/run_gates.py repo` (layering, path filters) |

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [answer-record](prd/answer-record.md) | 3 / 2 / 9 | 16 |
| [signals](prd/signals.md) | 3 / 2 / 15 | 20 |
| [block-api](prd/block-api.md) | 3 / 3 / 7 | 14 |
| [abstain](prd/abstain.md) | 3 / 2 / 11 | 22 |
| [extract-rules](prd/extract-rules.md) | 2 / 3 / 7 | 13 |
| [grader-parity](prd/grader-parity.md) | 4 / 3 / 8 | 16 |
| [signal-reduce](prd/signal-reduce.md) | 4 / 2 / 7 | 12 |
| [filter](prd/filter.md) | 3 / 2 / 5 | 10 |
| [fusion-recipe](prd/fusion-recipe.md) | 3 / 2 / 9 | 13 |
| [report-trace](prd/report-trace.md) | 4 / 2 / 9 | 17 |
| [budget-schema](prd/budget-schema.md) | 3 / 2 / 6 | 10 |
| **Total** | **35 / 25 / 93** | **163** |

## 5. Not tested (with owner and revisit condition)

| Item | Why | Owner | Revisit when |
|---|---|---|---|
| MATH parity | no MATH benchmark in the engine `[stated ans:Q5]` | Ionesio | a MATH benchmark is imported |
| Multiple-choice and yes/no answer rules | out of scope (grader-parity §5) | Ionesio | a vote on MMLU/ARC/BoolQ is asked for |
| Live paid behavior of the two replay lanes | the user records them (U5) | user | the unit 11 PR opens |
| Live (uncached) latency stability | latency differs on a fresh live rerun by nature (SG-D13) | Ionesio | a recipe depends on live latency |
| Regex worst cases outside the three banned shapes | bounded by window + timed golden | Ionesio | p99 combine time > 50 ms on regex specs (RX-D1 tripwire) |
