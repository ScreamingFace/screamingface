# E4b part 6: signal sums and the abstain band — overview

**Status:** draft, written headless from the owner answers of 2026-10-16 (Q1, Q2). Waiting for
owner review. **Epic:** E4b (OME-1290). **Leaf:** filed at PR-open.
**Base:** branch `e4b-gate-record` (E4b part 5, on parts 2–4) at `633fec3a1`. Branch
`e4b-signal-sums`, worktree `.claude/worktrees/e4b-signal-sums`. Part 7 (`consistency@N`, branch
`e4b-consistency`) is built in parallel from the same base; the two parts are stacked later
(contracts C10).

## 1. Summary

Parts 3–5 give declared signals (`sf.Verbalized`, `sf.Logprob`, `sf.Entropy`), a report that shows
them, and a vote gate that keeps the majority or takes a fallback. A rule reads ONE name. Epic
OME-1290 behavior 1 (CodeX-Verify) asks for more than one signal in one step: "four specialists
each emit a severity score. The scores are summed with fixed coefficients. If the total is in a
borderline band, the system abstains instead of returning a verdict. The sum is this behavior. The
abstain band is behavior 4."

This part adds:

- `sf.Sum({"sev_a": 0.5, "sev_b": 0.3})`: a DECLARED DERIVED SIGNAL (ans:Q1). In
  `signals={"risk": sf.Sum(...), "sev_a": ..., "sev_b": ...}` each member gets
  `risk = 0.5 × sev_a + 0.3 × sev_b`. Any rule or gate reads it by name: a vote weight, `sf.Pick`,
  `sf.Rank`, `sf.Filter`, and a gate `chosen:risk` or `mean:risk`. The evidence records it like any
  declared signal (`declared`, `members[].signals`).
- `sf.Gate(..., abstain_band=(lo, hi))` (ans:Q2). When the observed number is inside the closed
  band `[lo, hi]`, the Case abstains with the NEW reason `in_band`. Outside the band the gate
  compares as in part 5. The gate record holds the band and the new branch word `band`.
- The part 4 surfaces show both: the sum is one more signal column whose header names its formula;
  the gate chip shows the band; the run summary counts the Cases in the band.

Wire changes, all additive in the v1 schemas (no new schema id): one new member of the `signals`
union (`{"source": "sum", "coefficients": {...}}`), the optional key `abstain_band` on the spec
`gate` and on the evidence gate record, the branch word `band`, and the abstain reason `in_band`.
No new failure code, no new combine route, no new operation kind, no new model call, no new url4
grammar.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `633fec3a1`.

**Epic map** (OME-1290 items that this part closes):

| Epic item | Status after this part |
|---|---|
| Behavior 1, CodeX-Verify: "The scores are summed with fixed coefficients" | done for the declared signals of one member ([signal-sum](prd/signal-sum.md), [sum-api](prd/sum-api.md)); a sum across members is deferred (D2, N1) |
| Behavior 4, CodeX-Verify: "borderline severity band abstains to a human instead of forcing a verdict" | done ([abstain-band](prd/abstain-band.md), [band-api](prd/band-api.md)) |
| Behavior 4: "Abstain is a distinct outcome ... Coverage counts it separately" | done: `in_band` is an abstain result; the Case is `candidate_abstained` through the existing final-operation rule |
| Behavior 4, Multi-agent oracles: "a composite of confidence and disagreement can escalate ... The score it reads is this behavior" | partly: a composite of member signals (for example a verbalized confidence and a logprob `prob`) is a sum; the panel agreement is a gate input, not a member signal, so it cannot be a sum component (D1) |
| "The weight formula is fixed and documented, not an arbitrary function upload (that would be E4e)" | kept: a sum is linear with fixed coefficients in the recipe |
| Part 5 D4: "Several signals in one gate, sums with coefficients, an abstain band" | done (a gate reads a sum by name) |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| SDK user API (`S/signal_sources.py`, `S/fusion.py`, `S/gate.py`, `S/__init__.py`) | `sf.Sum`, the Fusion sum rules, `abstain_band=` | sum-api, band-api |
| SDK rebuild (`S/signal_sources.py` `_SOURCES`, `S/reducer.py` `_rebuilt_gate`) | `Url4.to_python` of a sum and a band | sum-api, band-api |
| SDK evidence (`S/answer.py`, `S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`) | `in_band`, `band`, `CombineGate.abstain_band`, decoder | abstain-band |
| Engine combine core (`E/combine/spec.py`, `E/combine/ports.py`, `E/combine/evidence.py`, `E/combine/gate.py`, `E/combine/endpoint.py`, new `E/combine/signal_sum.py`) | parse, compute, decide, record | signal-sum, abstain-band |
| SDK display (`S/_ui/combine_view.py`) | sum header title, band chip, summary counter | sum-band-display |
| Contract data (`ET/data/combine_contract/`, `ST/data/schemas/`) | schema snapshots, evidence cases, url4 fixtures | signal-sum, sum-api, abstain-band, band-api |
| Docs (`packages/screamingface/README.md`, `CHANGELOG.md`) | user guidance | docs |

## 3. Reading order

1. [erd.md](erd.md)
2. [prd/signal-sum.md](prd/signal-sum.md) (component, P0)
3. [prd/sum-api.md](prd/sum-api.md) (P0)
4. [prd/abstain-band.md](prd/abstain-band.md) (component, P0)
5. [prd/band-api.md](prd/band-api.md) (P0)
6. [prd/sum-band-display.md](prd/sum-band-display.md) (P1)
7. [prd/docs.md](prd/docs.md) (P2)
8. [contracts.md](contracts.md), [test-plan.md](test-plan.md)

## 4. PRD index

| PRD | Lifecycle | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|
| [signal-sum](prd/signal-sum.md) | existing | 5 / 2 / 6 | 14 |
| [sum-api](prd/sum-api.md) | planned on existing | 5 / 4 / 5 | 14 |
| [abstain-band](prd/abstain-band.md) | existing | 4 / 3 / 8 | 18 |
| [band-api](prd/band-api.md) | existing | 4 / 2 / 3 | 9 |
| [sum-band-display](prd/sum-band-display.md) | existing | 5 / 1 / 4 | 10 |
| [docs](prd/docs.md) | existing | 2 / 0 / 2 | 5 |
| **Total** | | **25 / 12 / 28** | **70** |

## 5. Interview ledger

The prompt is the E4b roadmap ("Part 6. More than one signal per step: a sum with fixed
coefficients and a borderline band that abstains") and the owner brief of 2026-10-16. The owner
answered two questions (multiple choice). The answers are verbatim option labels. Do not ask them
again.

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | How does a recipe sum signals? | "Declared derived signal (Recommended)" | `signals={"risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3})}`; each member gets `risk = 0.5*sev_a + 0.3*sev_b`. Any rule or gate reads it by name (weights, Pick/Rank/Filter, Gate `chosen:`/`mean:`). Recorded like any declared signal. |
| Q2 | Where does the abstain band live? | "Band on sf.Gate (Recommended)" | `sf.Gate(..., abstain_band=(lo, hi))`: if the observed number is inside `[lo, hi]` the Case abstains with a NEW reason; outside the band the gate compares as today. Recorded in the gate record. |

Epic text that sets the scope (OME-1290, verbatim): "Each member gets a value for each declared
name, or an explicit missing. Missing is not zero." "Abstain is a distinct outcome, not an empty
string that looks like a wrong answer. Coverage counts it separately." E4c (OME-1291, verbatim):
"`fail_closed` versus abstain. Abstain is a scored decline. Fail-closed is an error. They must not
share a status code."

## 6. Global decisions [proposed]

Each item below is an engineering decision made without the owner, from the answers above. The
owner approves or changes them at review (plan §6). The letters (a)–(h) are the decision points of
the planning brief.

| # | Decision | Where |
|---|---|---|
| P1 | **(a) The wire.** A sum is one entry of the existing optional `signals` map of the combine spec: `{"source": "sum", "coefficients": {name: number}}`, a fourth member of the `DeclaredSource` union (E/combine/spec.py:166-169). The Engine core computes it (new pure module `E/combine/signal_sum.py`); it is not a registry source plugin, because it reads other declared values, not the member text. WHY: ans:Q1 says "declared derived signal"; the `signals` map is where declared signals live, and the evidence `declared` map then records it with no schema change. | [erd §1](erd.md), C1 |
| P2 | **(a) `sf.Sum`.** `sf.Sum(coefficients)` takes a mapping; it stores the terms sorted by name, as floats (an int becomes a float, a bool is refused), so the url4 has one spelling and the rebuild gives the same `repr`. `sf.Sum` is a `SignalSource`; it is unhashable (it holds a mapping). | [sum-api](prd/sum-api.md) §2 |
| P3 | **(b) Components.** A component is a name that the SAME Fusion declares and that is not an `sf.Sum`. An E4a key (`cost_usd`, `score:judge`, `field:<path>`) is refused (D1): the Engine records an E4a key only when a rule reads it, and its source (the reader call, the judge reply) would have to run for the sum alone. A sum of sums (and a sum of itself) is refused for v1, so there is no cycle and no order rule (D3). Both sides check: the SDK at construction, the Engine at spec parse. | [signal-sum](prd/signal-sum.md) SM-E1, [sum-api](prd/sum-api.md) SA-E2, SA-E3 |
| P4 | **(a) Coefficients.** 1 to 7 terms (a sum and its components share the 8 names of a Fusion). Each coefficient is finite and not zero; a negative coefficient is allowed (for example `risk = sev - 0.5 × conf`). No normalization: the author writes the weights. | erd §1 |
| P5 | **(b) Arithmetic and missing values.** A member's sum is computed after its component values exist. It is None when any component is None ("Missing is not zero"). The value is the EXACT rational sum of `coefficient × value` (`fractions.Fraction`), rounded ONCE to a float. An exact sum outside the float range is None, as `finite_float` treats any number a float cannot hold (E/combine/ports.py:519-526). WHY not `math.fsum` of the float products (the brief's first idea): the products are rounded before the sum, so `0.1 × 3 + 0.1 × 0.1` gives `0.31000000000000005` and not `0.31`; one exact rule has no fallback path and no order effect. The part 5 erratum E6 (Fraction fallback for a mean) is the precedent. | [signal-sum](prd/signal-sum.md) SM-D1, SM-D2 |
| P6 | **(c) One signal per rule.** `_signal_read` (E/combine/endpoint.py:732-750) does not change: a rule reads ONE name, and that name may be a sum. A step that reads `risk` as a weight and `sev_a` in its reduce args is still refused. | SM-E2 |
| P7 | **(e) Band shape.** `abstain_band` is two finite numbers `lo <= hi` (one point, `lo == hi`, is valid); for an `agreement` gate, `0 <= lo <= hi <= 1`. An explicit null is refused. The SDK stores a tuple of floats; the wire holds a list. | [abstain-band](prd/abstain-band.md) AB-E1, [band-api](prd/band-api.md) BA-E1 |
| P8 | **(e) Band order.** The band is a CLOSED interval and is checked BEFORE the comparison. No rule ties the band to the threshold: "outside the band the gate compares as today" (ans:Q2). A missing number skips the band and takes the fallback, as in part 5 P10. | AB-D1, AB-D3 |
| P9 | **(e) The band wins over every fallback.** Inside the band the Case abstains with `in_band` also when `otherwise` is a judge or a writer. The band branch never reads a `fallback_*` reply (FB-I1 holds), so E4c can skip that call with no wire change. The fallback call still runs in this part (part 5 ans:Q1). | AB-D2, C8 |
| P10 | **(e) Record of the band branch.** `branch: "band"` (a new `GateBranch` word), `passed: null` (no comparison was made), `observed`: the number inside the band. GR-I1 and GR-I4 of part 5 are restated (erd §4: GR-I1', GR-I4'); the part 5 cases keep their messages. New invariants GB-I1 to GB-I5 let a reader replay the decision from the record alone. | erd §4 |
| P11 | **(e) Record key.** The record gets the optional key `abstain_band` (`[lo, hi]`) after `otherwise`, written only when the spec has a band, so every part 5 gate record keeps its bytes. The record of a gate that did not run also keeps the band. | AB-D4, AB-D5 |
| P12 | **(e) The new reason `in_band`.** Appended after `gate_not_met` to `AbstainReason` and `AnswerReason` on both sides. It is a scored decline, not a failure code, and it is distinct from `gate_not_met` (the comparison failed) and from E4c's `fail_closed` (an error). The other name considered: `gate_in_band`. | erd §5, C7 |
| P13 | **(d) A sum as a vote weight.** The part 3 Q11 rule extends to sums: a vote weight that reads a sum is refused when the sum adds an `sf.Logprob("mean")`, an `sf.Logprob("sum")` or an `sf.Entropy` (the `sf.Fusion` constructor, part 3 P14). Other sums may be weights; a member whose sum is not a usable weight (zero or less, or above `MAX_WEIGHT`, E/combine/spec.py:67; the existing `_weight` rule, E/combine/endpoint.py:800-806) is excluded with `no_weight`. The Engine needs no change for this. | [sum-api](prd/sum-api.md) SA-E4 |
| P14 | **(f) Display.** The sum is one more signal column with no column code change; its header title (Case pane and run summary) is `source: sum of 0.5 × sev_a + 0.3 × sev_b`. The gate chip shows ` · band [lo, hi]` and the verdict `in band · abstain`. The run summary gate line adds ` · in band {b} of {N}` when `b > 0`. The verdict and the counters read `branch`, not `passed`. The run summary mean gets the exact fallback for an overflow (a sum makes large means likely). The export carries the record with no change. The report-trace.v1 field set does not change. | [sum-band-display](prd/sum-band-display.md) |
| P15 | **(g) Rebuild.** `Url4.to_python()` rebuilds `sf.Sum` through `_SOURCES` and `Sum._from_spec`, and the band through `_rebuilt_gate`. The repr writes `abstain_band=(lo, hi)` after `otherwise=`. A hand-edited sum or band fails with the existing "cannot rebuild" errors. | SA-4, BA-3, C3, C6 |
| P16 | **Additive Engine edits (part 7 runs in parallel).** The union gets one member; `_declared` gets one branch before the registry lookup; `_signal_values` computes the non-sum columns first (today's code), then the sums; the sum arithmetic lives in its own pure module. Generated files are regenerated after a rebase, never merged by hand (C10). | C10 |
| P17 | **Contract data.** Two new evidence contract cases (`pick_sum_min` in unit 1, `vote_gate_band` in unit 4): 37 → 39 cases. Two SDK-compiled url4 fixtures (`sum_pick_candidate.url4`, `gate_band_vote_candidate.url4`), each with a drift guard; the Engine runs each offline. | SM#12, AB#16, SA#12, BA#7 |
| P18 | **No log change.** The one combine log line keeps its format; a band abstain logs `outcome=abstain_in_band` through the existing rule (E/combine/endpoint.py:256). | AB-D7 |
| P19 | **(h) Pinned files.** Each unit lists its exact pinned files (§8, plan §6). The build reports them; the owner approves after the build. | §8 |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | An E4a key (`cost_usd`, `score:judge`, `field:<path>`) or the panel `agreement` as a sum component | not planned in part 6; a `field:` number can be read with an `sf.Verbalized` pattern; an additive change later |
| D2 | A sum ACROSS members with a coefficient per member (CodeX-Verify's exact form: four specialists, each one severity) | not planned in E4b; see N1 |
| D3 | A sum of sums | not planned (no use case, and it needs an order rule) |
| D4 | A band on `sf.Median`, `sf.Mean`, `sf.Pick` or a Filter threshold | not planned (the band is on `sf.Gate`, ans:Q2; the gate is on `sf.Vote` only, part 5 P1) |
| D5 | The skip of the fallback call on the band branch | E4c (OME-1291) |
| D6 | A different fallback inside the band (for example a judge only in the band) | not planned; an additive `otherwise` form later |
| D7 | A non-linear formula | E4e |

Scope notes:

- **N1** ans:Q1 sums the declared signals of ONE member. In CodeX-Verify each of four specialists
  emits one severity, and the paper sums across the specialists. With this part an author can (a)
  ask one member for the four severities (four `sf.Verbalized` names and one `sf.Sum`), or (b) run
  the four specialists as members and gate on `mean:<name>`: the mean is the sum divided by the
  number of members with a value, so a band on the mean is a band on the sum with scaled ends, but
  with ONE coefficient for all specialists. Per-specialist coefficients across members are D2. The
  owner sees this at review (plan §6).
- **N2** A judge or writer fallback still runs and costs money on every Case, also when the number
  is in the band (part 5 N1). Its reply is not read in the band.
- **N3** A sum can be negative. As a Pick or Rank key it orders as any number; as a vote weight a
  value of zero or less, or above `MAX_WEIGHT`, excludes the member (`no_weight`).
- **N4** A declared sum is computed and recorded on every Case, also when no rule reads it (part 3
  ans:Q7 "Record every declared").
- **N5** A sum of a logprob or entropy name needs the same OpenRouter members as that name (part 3
  P3); the sum adds no member call param.

## 8. Owner-approved test edits (needed at build)

The build lists each file below as a pinned edit. The owner approves them after the build (plan
§6). No approval manifest is written by the build.

| File | Unit | Why |
|---|---|---|
| `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json` | 1, 3 | the `SumSource` union member (unit 1); `GateSpec.abstain_band` (unit 3) |
| `ET/data/combine_contract/evidence_cases.json` | 1, 4 | the new cases `pick_sum_min` (unit 1) and `vote_gate_band` (unit 4); every existing case keeps its bytes |
| `ST/test_frozen_record_fields.py:184` | 1, 4 | the case count 37 → 38 (unit 1), 38 → 39 (unit 4) |
| `ST/public_surface_snapshot.json` | 2, 4, 5 | `sf.Sum` (unit 2); `CombineGate.abstain_band` (unit 4); `Gate` `abstain_band` (unit 5) |
| `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` | 4 | `GateRecord.abstain_band`, the branch word `band`, `in_band` in the two reason enums |
| `ST/data/schemas/screamingface.answer.v1.json` | 4 | `in_band` in `abstain_reason` and `reason` |
| `ET/test_combine_gate_words.py:645`, `:761`, `:765` | 4 | the branch enum gains `band`; the exact abstain word tuple and the last `AnswerReason` gain `in_band` |
| `ET/test_combine_pick_output.py:341-343`, `:352` | 4 | the exact `AbstainReason` and `ABSTAIN_REASONS` tuples, the last `AnswerReason`, the last word of each `no_votes` enum list |
| `ET/test_combine_evidence_words.py:310-322` | 4 | the exact `AnswerRecord.reason` enum list gains `in_band` after `gate_not_met` (line 321) |
| `ST/test_gate_words.py:524`, `:567`, `:582-589` | 4 | the word set, the count 13 → 14, the last words of the two enum lists, the `answer.v1` abstain list |
| `ST/test_evidence_words.py:373`, `:460-475` | 4 | the count 13 → 14; the exact `answer.v1.json` dict |
| `ST/test_pick_output.py:250-265` | 4 | the exact sorted reason lists of `answer.v1.json` gain `in_band` |
| `ST/test_gate_api.py:472` | 5 | the exact `sf.Gate` parameter list gains `"abstain_band"`: `["observe", "cmp", "threshold", "otherwise"]` → `["observe", "cmp", "threshold", "otherwise", "abstain_band"]` |

Units 1 and 4 also change two test files that are append-only. The append-only check does not flag
them (a new module-level statement between or after the protected ranges is not inside a range),
so they need no approval unless the gate names them:

- `ET/test_combine_evidence_contract_fixture.py`: one scenario builder and one `SCENARIOS[...]`
  line per unit, INSERTED directly after line 418 (the part 5 gate block) and before
  `def canonical_evidence` (line 421 on base). Unit 1 inserts the `pick_sum_min` block; unit 4
  inserts the `vote_gate_band` block after the unit 1 block. Never append at the end of the file:
  the file ends with `if __name__ == "__main__": write_fixture()` (lines 491-492), so a line after
  it does not run when the file runs as a script (test-plan §2), and
  `@pytest.mark.parametrize("name", sorted(SCENARIOS))` (line 442) reads `SCENARIOS` when the
  decorator runs, so a later scenario gets no byte test. Part 5 inserted its block the same way
  (lines 378-418).
- `ST/test_combine_evidence_contract.py`: one `_EXPECTED_NAMES |= {...}` line per unit, appended
  after line 61.

The word `in_band` and its pinned edits are in unit 4 with the contract case that uses it:
`ET/test_combine_evidence_contract_fixture.py:461-463` needs every `AbstainReason` in the contract
scenarios (the part 5 lesson, part 5 overview §10).

How to regenerate: test-plan §2.

Unit 3 pins only the spec v1 snapshot. Units 6 and 7: no pinned file. If the append-only gate names another file, the unit stops and the
ledger records it as a deviation.

## 9. What changes for related work

- **E4c (OME-1291).** E4c reads the spec `gate` with its optional band, checks the band first, and
  skips the fallback call on the majority, band and "not run" branches. The evidence keeps its bytes
  (C8). `in_band` and `fail_closed` never share a status code.
- **E4b part 7 (`consistency@N`).** Built in parallel. A `consistency` name can be a sum component
  with no change. The shared files are listed in C10; the second part to land regenerates the
  generated files.
- **E4b part 8 (token-level methods).** No interaction.
- **E4e.** A non-linear formula or an uploaded function stays E4e (D7).

## 10. Spec review

Run on 2026-10-16 (commit `docs(e4b): review fixes for the E4b part 6 spec`). 15 findings: 3
MAJOR, 12 MINOR (1 STRUCTURAL, plan shape only). All are fixed in the spec and the plan; the ledger
"Spec review" note lists each finding and its fix. The main changes:

- §8 and plan §6: `ST/test_gate_api.py:472` is a pinned edit of the band-api unit.
- band-api: a hand-edited `"abstain_band": null` fails to rebuild (no pass-through of a non-list).
- §8, signal-sum §7, abstain-band §7: the contract scenarios are INSERTED before
  `def canonical_evidence`, not appended after the `__main__` block.
- The plan splits the old unit 3 (band-record) into unit 3 (band-spec) and unit 4
  (band-record). Old units 4, 5 and 6 are now units 5, 6 and 7.

## 11. Build errata

- **E1 (unit 1).** `ET/test_combine_gate.py:566-567` pins the exact case set and the last five
  cases of `evidence_cases.json`, so each new contract case needs a pinned edit there. Unit 1:
  `sorted((*L32, *GATE_CASES, "pick_sum_min"))` and `list(cases)[32:37]`. Unit 4: add
  `"vote_gate_band"` to line 566. Not in §8 or plan §6 when the spec was written.

The build appends E1, E2, ... here, one line group per deviation from this spec.
