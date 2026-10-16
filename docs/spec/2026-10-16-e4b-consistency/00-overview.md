# E4b part 7: consistency@N — overview

**Status:** draft, written headless from the owner answers of 2026-10-16 (Q3, Q4). The spec review
fixes of 2026-10-16 are applied (ledger, "Spec review"). Waiting for owner review. **Epic:** E4b (OME-1290). **Leaf:** filed at PR-open.
**Base:** branch `e4b-gate-record` (E4b part 5, on parts 4, 3 and 2) at `633fec3a1`.
Branch `e4b-consistency`, worktree `.claude/worktrees/e4b-consistency`. Part 6 (signal sums and
the abstain band, branch `e4b-signal-sums`) builds in parallel from the same base; one of the two
parts is later rebased onto the other (contracts C8).

## 1. Summary

Parts 3–5 give declared signals that come from the member's own reply: a stated confidence
(`sf.Verbalized`), a log-probability (`sf.Logprob`) and an entropy (`sf.Entropy`). The epic's
sources table has one more row: "`consistency@N` | Call that member N more times with different
seeds. Extract and normalize each answer the same way as E4a. The number is the fraction of those
N that match this answer. | N extra calls per member. Uses E4a's sampler and normalizer."
A logprob works only where the provider returns logprobs (DB-7: OpenRouter); consistency works on
every model that takes `seed` and `temperature`.

This part adds:

- `sf.Consistency(n, *, temperature=1.0)`, declared like `sf.Logprob`:
  `signals={"cons": sf.Consistency(n=5)}`; rules read `sf.signal("cons")` (a weight, `sf.Pick`,
  `sf.Rank`, `sf.Filter`, a part 5 gate `"chosen:cons"`).
- The compile adds n extra calls for each member: the member's route, prompt and other params,
  with the stated temperature and distinct, fixed seeds (ans:Q3). Each member's extra calls form
  one broadcast panel with `quorum=0` and optional slots, so a failed extra call never fails the
  Case (ans:Q4). The free preflight checks `seed` and `temperature` per model before any spend.
- The combine step reads the panels from a new context key `samples` and computes, for each
  member, `matched / succeeded` over its successful extra calls, after the step's own extract and
  normalize (or `last_line` and `text` for a step without an extract). When every extra call
  fails, the value is missing, and a rule that reads it excludes the member (part 2). The extra
  answers never vote.
- The evidence records the value in `members[].signals`, the declaration (with its match
  operators) in `declared`, and a new optional record `consistency` with `matched`, `succeeded`
  and `failed` for each member (ans:Q4: "the count of failed samples is recorded").
- The part 4 surfaces show the value, the failed extra calls per member, a step chip and a run
  summary line. The url4 rebuild gives back `sf.Consistency(...)` and drops the extra calls.

Wire changes, all additive in the v1 schemas (no new schema id): a new source word in the optional
`signals` map, a new optional context key `samples`, a new optional evidence key `consistency`, a
new optional topology key `samples`, and a new operation kind `sample`. No new failure code, no new
combine route, no new binding prefix, no url4 grammar change.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `633fec3a1`.

**Epic map** (OME-1290 items that this part closes):

| Epic item | Status after this part |
|---|---|
| Sources table row `consistency@N` ("N more times with different seeds ... the fraction of those N that match") | done ([consistency-api](prd/consistency-api.md), [consistency-value](prd/consistency-value.md)); the fraction is over the successful calls (ans:Q4). "Uses E4a's sampler": this part uses the sampler idea (distinct integer seeds, one seed-keyed cache entry per call), not the `sf.samples()` function; P5 gives the reason |
| "Each member gets a value for each declared name, or an explicit missing. Missing is not zero." | done: every failed extra call → missing, never 0 ([consistency-value](prd/consistency-value.md) CV-4) |
| "The value is a number stored on that member's answer. The report shows it and the source." | done ([consistency-record](prd/consistency-record.md), [consistency-display](prd/consistency-display.md)) |
| "The same source name means the same procedure everywhere (a vote, a cascade gate, a debate stop)" | done for the vote weight, Pick, Rank, Filter and the part 5 gate (CV-5, CV-2, CV-D6) |
| Open question: "whether a missing logprob fails the run or forces the author to pick `consistency@N`" | a logprob still fails visibly (part 3); `consistency@N` is now there to pick |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| SDK user API (`S/signal_sources.py`, `S/fusion.py`, `S/__init__.py`) | `sf.Consistency`, the Fusion rules, the seed rule | consistency-api |
| SDK compile (`S/_evaluation/candidate.py`, `S/_evaluation/combine_spec.py`, `S/_evaluation/topology.py`, `S/_evaluation/corrective.py`) | the extra calls, the panels, the context key, the spec `match`, the topology encode | consistency-api |
| SDK rebuild and replay (`S/url4.py`, `S/_evaluation/topology.py` decode, `S/_evaluation/url4.py`, `S/signal_sources.py` `_from_spec`) | `to_python`, the replayed operations | consistency-rebuild |
| SDK evidence (`S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`, `S/report.py`) | `CombineSampleCount`, the decoder | consistency-record |
| SDK accounting and warnings (`S/accounting.py`, `S/_evaluation/runner.py`) | the `sample` stage, the fixed-seed warning | consistency-api |
| Engine combine core (`E/combine/spec.py`, `E/combine/evidence.py`, `E/combine/endpoint.py`, new `E/combine/consistency.py`) | parse, compute, record | consistency-record, consistency-value |
| SDK display (`S/_ui/combine_view.py`) | the chip, the cell note, the summary line | consistency-display |
| Contract data (`ET/data/combine_contract/`) | schema snapshots, the new evidence cases file, two url4 fixtures | consistency-record, consistency-value, consistency-api |
| Docs (`packages/screamingface/README.md`, `CHANGELOG.md`) | user guidance | docs |

## 3. Reading order

1. [erd.md](erd.md)
2. [prd/consistency-record.md](prd/consistency-record.md) (component, P0)
3. [prd/consistency-value.md](prd/consistency-value.md) (P0)
4. [prd/consistency-api.md](prd/consistency-api.md) (P0)
5. [prd/consistency-rebuild.md](prd/consistency-rebuild.md) (P1)
6. [prd/consistency-display.md](prd/consistency-display.md) (P1)
7. [prd/docs.md](prd/docs.md) (P2)
8. [contracts.md](contracts.md), [test-plan.md](test-plan.md)

## 4. PRD index

| PRD | Lifecycle | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|
| [consistency-record](prd/consistency-record.md) | existing | 5 / 4 / 4 | 15 |
| [consistency-value](prd/consistency-value.md) | existing | 5 / 2 / 8 | 14 |
| [consistency-api](prd/consistency-api.md) | existing | 7 / 4 / 8 | 14 |
| [consistency-rebuild](prd/consistency-rebuild.md) | existing | 3 / 6 / 5 | 9 |
| [consistency-display](prd/consistency-display.md) | existing | 4 / 1 / 5 | 7 |
| [docs](prd/docs.md) | existing | 2 / 0 / 2 | 5 |
| **Total** | | **26 / 17 / 32** | **64** |

## 5. Interview ledger

The prompt is the E4b roadmap ("Part 7. `consistency@N`") and the owner brief of 2026-10-16. The
owner answered the part 6 and part 7 interviews on 2026-10-16 and asked to build both parts in
parallel. The part 7 answers are verbatim option labels. Do not ask them again.

| Id | Question | Answer | Note |
|---|---|---|---|
| Q3 | Which temperature do the extra calls use? | "Source sets temperature (Recommended)" | `sf.Consistency(n=5, temperature=1.0)`: the extra calls use distinct seeds and the stated temperature (default 1.0), the member's other params unchanged. Explicit and reproducible. |
| Q4 | What happens when an extra call fails? | "Fraction over successes (Recommended)" | value = matches / successful samples; the count of failed samples is recorded; if all fail, the value is missing (the rule then excludes the member, as in part 2). The Case does not fail. |

(Q1 and Q2 of the same interview belong to part 6.)

Epic text that sets the scope (OME-1290, verbatim): "Call that member N more times with different
seeds. Extract and normalize each answer the same way as E4a. The number is the fraction of those
N that match this answer." "N extra calls per member. Uses E4a's sampler and normalizer."
"Each member gets a value for each declared name, or an explicit missing. Missing is not zero."

No point of this spec contradicts an owner answer. There is no owner blocker.

## 6. Global decisions [proposed]

Each item below is an engineering decision made without the owner, from the answers above. The
owner approves or changes them at review (plan §6).

| # | Decision | Where |
|---|---|---|
| P1 | **The API.** `sf.Consistency(n, *, temperature=1.0)` in `S/signal_sources.py`, a `SignalSource` like `sf.Logprob`, exported as `sf.Consistency`. The wire word is `consistency` (already a reserved name prefix, S/_signals.py:23). `repr` always shows both: `Consistency(n=5, temperature=1.0)`. | [consistency-api](prd/consistency-api.md) delta 1 |
| P2 | **The ranges.** `n` is an int from 1 to 32 with NO default (the author chooses the cost). `temperature` is finite and `>= 0`, default 1.0 (ans:Q3); its upper bound is the model's own, checked by the preflight. WHY 32: 256 members × 32 = 8192 calls is already above the P4 cap; 32 samples give a step of 1/32 in the fraction. | erd §1 |
| P3 | **The match operators are in the spec.** The entry holds `match: {extract, normalize}`, pinned: the step's own extract and normalize when the step has an extract (a vote, a median, a Filter with `extract=`), else `last_line@1` and `text@1` (the E4a vote default) for a step with none (`sf.Pick(by_signal=...)`, `sf.Rank(by_signal=...)`). WHY: "the same way as E4a"; the operator versions are recorded, so a replay is exact, and the SDK pins them against the Engine catalog before any spend. The source writes its full entry with `Consistency._entry(match)`; `combine_spec_text` gives it the step's `match` (only the compile sees the step) through one `isinstance` branch. | erd §1, C1 |
| P4 | **The Fusion rules.** At most one `sf.Consistency` per Fusion (checked in `_declaration`, beside the one-`sf.Entropy` rule); each member is one `sf.Model` (any provider); `members × n <= 1024`; a reducer synthesizer (DS-I3). WHY: one panel per member keeps the context simple; a nested Recipe member has no one call to repeat; the cap bounds the url4 and the context. | erd §1 CN-I1..I4 |
| P5 | **The extra-call params and seeds (ans:Q3).** Params in order: `binding=model_N`, the member's author params without `seed` and `temperature` (author order), `temperature=<t>`, `seed=<s(k, j)>`. `s(k, j)` = the first 31 bits of `sha256(f"consistency:{k}:{j}")` (the `derive_attempt_seed` idea). The 8192 seeds of k ≤ 256, j ≤ 32 are distinct and never in 0..255 (the `sf.samples()` defaults). A member whose own `seed` equals any sample seed of the Fusion (of any member) is refused: else a member call and a sample call of the same route could send one gateway body and share one cached reply (the gap across two Fusions is N7). WHY not the `sf.samples()` function and not `derive_attempt_seed` in code: `sf.samples()` refuses a base Model that sets `seed` (`_SEED_PARAM_ERROR`, S/_samples.py:18), its default seeds 0..n-1 are the same for every member (two same-route members would share their samples), and `derive_attempt_seed` is Engine code that the SDK does not import. This part uses the idea of both: distinct integer seeds from a 31-bit sha256. The `logprobs` and `top_logprobs` params that `sf.Logprob` or `sf.Entropy` add are NOT sent on the extra calls. | erd §2, CA-2, CA-7, CA-E2 |
| P6 | **The url4 shape.** Each extra call is a `model_N` source (the next model number after the members) with the binding param first, in an optional slot `sample_j` of one broadcast panel `panel_M` per member with `quorum=0`. WHY: no new binding prefix (the vocabulary is pinned in three places), the Engine attributes the calls inside a `panel_N` as today, and the binding param keeps every extra call's fingerprint apart from the member calls, so the member reader (E/world/combine.py:82-120, "several matches make numbers unknown") is never confused. | erd §2–3, C2, C6 |
| P7 | **The operations.** One operation per extra call: `op_model_N`, kind `sample`, label `"{member name} sample"`, `depends_on` = the Fusion's input dependencies. The combine call depends on the members, then the signal calls, then the samples. WHY this order: `_operation_answers` (S/_case_views.py:41-45, through `_producers`) and `_member_ids` (:277) take `depends_on[:len(evidence.members)]` as the member producers, so the members must stay first; the signal calls keep their existing place; the samples go last. A later reorder would attach the wrong text to the member answers (CA#8 pins the order). `S/accounting.py` maps `sample` to the `generation` stage (the owner chooses between `generation` and `synthesis`, plan §6). | CA-4, CA-D4 |
| P8 | **The topology.** The reducer node gets an optional `samples` list (one entry per member, n nodes with `role: "sample"`). The walker visits the samples before the signals, so the replay gives the compile's operation order. The reducer's context dependencies follow the context key order (P9: samples before signals); its operation dependencies follow the P7 order (signals before samples). The two orders are different on purpose. | erd §7 |
| P9 | **The context key.** `samples: {member_k: "$panel_M"}` for every member, written after `outputs` or `panel` and before `signals`, so the replay rule `_CONTEXT_SIGNALS` (S/url4.py:86) still finds `signals` at the end. The Engine requires it exactly when the spec declares consistency. `parse_context` parses each member's rows with the same row helper as the quorum panel (`_panel_rows`, E/combine/spec.py), so the url4 row contract has one home. | erd §4, C3 |
| P10 | **The match rule.** A sample matches when its match value is not None and equals the member's match value (text equality after normalize). A sample with nothing extracted, or over the 1 MiB read cap, is a SUCCESSFUL sample that does not match. WHY: the call answered; the answer does not agree. Only a failed call is a failed sample (ans:Q4). | erd §5, CV-D3 |
| P11 | **The denominator and the missing value.** `value = matched / succeeded` over the successful extra calls only; the member's own answer is not a sample (ans:Q4). The value is missing when `succeeded == 0` (ans:Q4), and also when the member itself has no match value (it failed, a quorum panel left it out, or nothing was extracted): there is no answer to compare. | erd §5, CV-1, CV-D4, CV-D7 |
| P12 | **The extra answers never vote.** They are not in `outputs`, the member panel, the tally or `chosen`. | SC-I3, CV-D2 |
| P13 | **The evidence record.** Optional top-level key `consistency: {name: [{member_id, matched, succeeded, failed}, ...]}` after `cut` and before `declared`, written only when the spec declares consistency, so every existing evidence keeps its bytes. The value stays in `members[].signals[name]` (part 3 EV-I2). Invariants CS-I1..CS-I5. WHY a separate record and not a field of `AnswerRecord`: the member record is in every evidence and part 6 may also change it; a separate key is local. WHY between `cut` and `declared`: ET/test_combine_gate_words.py:667 pins the fields from `declared` to `result` as `[gate, verifier]`, and ET/test_combine_evidence_words.py:354 pins `cut` directly after `signal`; this place keeps both tests green with no pinned edit. | erd §6, C4 |
| P14 | **The SDK mirror.** `sf.report.CombineSampleCount` and `CombineEvidence.consistency` (a public type, like `sf.report.CombineGate`). | [consistency-record](prd/consistency-record.md) |
| P15 | **The display (part 4 surfaces).** A step chip `samples · {name} · {n} per member · failed {F} of {T}`; in the member cell, the value and `{f} failed` when `f > 0`; the reasons `every sample failed` and `no answer to compare`; a run summary line `samples · {name} · failed {F} of {T}`. The export holds the record in `operations[].combine.consistency` with no export change. The report-trace.v1 field set does not change. | [consistency-display](prd/consistency-display.md) |
| P16 | **The rebuild and the replay.** `to_python` writes `sf.Consistency(n=..., temperature=...)` and leaves out the extra calls; the optional sample slots make every consistency url4 take the byte-for-byte recompile check, so a hand edit fails with an existing error. `spec_operator_pairs` adds the match operators. | [consistency-rebuild](prd/consistency-rebuild.md) |
| P17 | **The preflight and the cost.** The extra calls' params (without `binding`) are in `parameter_assignments`, so the free preflight refuses a model that does not take `seed` or `temperature` with `unsupported_model_parameter` before any spend (part 3 P12). The README states the cost: M × n extra calls on every Case. | CA-E3, [docs](prd/docs.md) |
| P18 | **The run seed.** The sample seeds are fixed by the recipe; they do not follow the run seed. The extra calls are left out of the `FixedSeedSittingWarning` (Recipe path and replay path), because the author cannot drop those seeds. | CA-D3, CB-D2 |
| P19 | **Corrective loops.** A corrective loop whose Recipe declares `sf.Consistency` is refused at compile in this version. | CA-E4, D2 |
| P20 | **Contract data, local to this part.** The Engine and SDK consistency cases go into a NEW file `ET/data/combine_contract/consistency_evidence_cases.json` (three scenarios), not into the 37-case `evidence_cases.json`. WHY: part 6 builds in parallel; the shared file and its count pins (`ST/test_frozen_record_fields.py:184`, `_EXPECTED_NAMES`) stay untouched. New url4 fixtures: `consistency_pick_candidate.url4`, `consistency_median_candidate.url4`. | CV#13, CV#14, CA#6 |
| P21 | **The core stays pure, and the log line does not change.** The counting is a new pure module `E/combine/consistency.py` (`SampleCount`, `count_samples`; standard library only); the rows parse is in `E/combine/spec.py` (`_panel_rows`, shared with the quorum panel); the endpoint passes the match steps in as a `read` function. The layering gate (`COMBINE_CORE_FORBIDDEN`) checks the imports. | C7 |
| P22 | **Part 6 in parallel.** Every change to a shared file is additive; the endpoint carries the sample counts inside `recorded` (a `_Recorded` mapping), so no exit function gets a new keyword; the docs tests check order, not fixed indexes; snapshots are regenerated after the rebase. | C8 |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | Sample seeds that follow the run seed (a new sample set per sitting) | not planned; an additive option later |
| D2 | `sf.Consistency` inside a corrective loop | refused (P19); a later part if asked |
| D3 | More than one `sf.Consistency` per Fusion (two n or two temperatures) | not planned |
| D4 | A nested Fusion or Pipeline member (repeat a whole Recipe) | not planned |
| D5 | A custom match (its own extract or normalize, a semantic match) | not planned; a later additive `match=` keyword |
| D6 | A paid live smoke of one consistency recipe | may be WRITTEN later under `ST/paid/`; never run in the build |
| D7 | The budget stage of an extra call | E4c (the budget ledger is not wired) |
| D8 | Skip the extra calls when no rule reads the value | not planned: part 3 Q7 records every declared name |
| D9 | Group the sample rows in the Case pane and the trace | not planned in this version (N8) |

Scope notes:

- **N1** The extra calls run and cost money on every Case: a Fusion of M members makes M × n extra
  calls. They also run when the member call fails. The README says so.
- **N2** A value of 0.0 is a weight of 0: in `sf.Vote(weights=sf.signal("cons"))`, that member has
  no weight and is excluded with `no_weight` (the existing weight rule, E/combine/endpoint.py:800-806).
- **N3** With `temperature=0`, many providers give the same answer for every seed, so the value is
  near 1.0. It is allowed; the README names the default 1.0.
- **N4** The context cap is 64 MiB. Very long replies × many samples can pass it; the step then
  fails with `combine_input_too_large`. That is a size limit, not a sample failure.
- **N5** The extra calls read the member's input, not the member's answer, so they run in parallel
  with the members.
- **N6** Distinct seeds give distinct gateway cache keys, so a replay returns the same samples and
  the same value. A provider that ignores `seed` still gives a fixed replay (the cache), but its
  first-run samples are not reproducible.
- **N7** The seed check (CN-I5) covers the members of one Fusion. A member of ANOTHER Fusion in the
  same Recipe with the same route, prompt and context, `temperature=t` and a seed equal to a sample
  seed would share one cached reply with that sample. That needs a hand-chosen 31-bit seed, so the
  check does not cover it in this version.
- **N8** Each extra call is one operation: one `model_call` trace entry and one step row with no
  member in the Case pane. At the cap, that is up to 1024 more rows per Case. This version accepts
  these rows; a grouped view is deferred (D9).

## 8. Owner-approved test edits (needed at build)

The build lists each file below as a pinned edit. The owner approves them after the build (plan §6).
No approval manifest is written by the build.

| File | Unit | Why |
|---|---|---|
| `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json` | 1 | the `ConsistencySource` and `ConsistencyMatch` defs in the `signals` union (frozen by `ET/test_wire_schema_freeze.py`) |
| `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` | 1 | the optional `consistency` property and the `SampleCountRecord` def |
| `ST/public_surface_snapshot.json` | 1, 3 | `sf.report.CombineSampleCount`, `CombineEvidence.consistency` (unit 1); `sf.Consistency` (unit 3) |

Units 2, 4, 5, 6 and 7: no pinned file (unit 3 is consistency-api-source, unit 4
consistency-api-compile; plan §2). The evidence field order (P13) keeps
`ET/test_combine_gate_words.py:667` green, so that file is not pinned. New test and data files are not in the append-only check. If
the append-only gate names another file, the unit stops and the ledger records it as a deviation.

How to regenerate: a schema snapshot is deleted, then written once with
`UPDATE_SCHEMA_SNAPSHOT=1` (the run fails), then checked by a plain run; the public surface
snapshot is rewritten with `UPDATE_SURFACE_SNAPSHOT=1` (the run fails), then checked by a plain run
(test-plan §2).

## 9. What changes for related work

- **E4b part 6** (built in parallel). It may extend the same shared files (contracts C8). A sum
  of signals can read `cons` like any declared name.
- **E4b part 8** (token-level methods) does not touch the extra calls.
- **E4c** (OME-1291) can read `chosen:cons` in a cascade gate. Skipping the extra calls is not in
  E4c's scope today (D8).

## 10. Build errata

None yet. The build appends one item per deviation from this spec.
