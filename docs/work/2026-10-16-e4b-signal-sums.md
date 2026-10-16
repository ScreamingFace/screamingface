---
ticket: unfiled   # epic OME-1290 is the parent; the leaf is filed at PR-open
stack: screamingface-engine, screamingface, repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-16
finished:
---

# e4b-signal-sums — E4b part 6, signal sums and the abstain band

One ledger for the whole part. The plan is
[docs/plan/2026-10-16-e4b-signal-sums.md](../plan/2026-10-16-e4b-signal-sums.md). The spec is
[docs/spec/2026-10-16-e4b-signal-sums/](../spec/2026-10-16-e4b-signal-sums/00-overview.md).
Branch `e4b-signal-sums`, base `633fec3a1` (part 5, on parts 2–4). Part 7 (`consistency@N`) is built
in parallel on branch `e4b-consistency` from the same base; this part never touches it. Each unit
gets its own section below, in the order of plan §2.

## Spec

### Intent

Give a Fusion a declared derived signal `sf.Sum({"sev_a": 0.5, "sev_b": 0.3})`: each member gets
one number, the fixed linear sum of other declared signals of the same member, missing when a
component is missing. Any rule or gate reads it by name (a vote weight, `sf.Pick`, `sf.Rank`,
`sf.Filter`, a gate `chosen:` / `mean:`), and the evidence records it like any declared signal
(ans:Q1). Give `sf.Gate` an abstain band `abstain_band=(lo, hi)`: inside the closed band the Case
abstains with the new reason `in_band`; outside it the gate compares as in part 5; the gate record
holds the band and the new branch word `band` (ans:Q2). The part 4 surfaces show the sum and the
band. E4c can still add the skip with no wire change, because the band branch never reads a
fallback reply.

### Owner decisions (verbatim)

- Q1 sum: "Declared derived signal (Recommended)".
- Q2 band: "Band on sf.Gate (Recommended)".

### Spec files (commit `docs(e4b): spec and plan for E4b part 6 (signal-sums)`)

- `docs/spec/2026-10-16-e4b-signal-sums/00-overview.md` (P1–P19, N1–N5, D1–D7)
- `docs/spec/2026-10-16-e4b-signal-sums/erd.md`, `contracts.md` (C1–C10), `test-plan.md`
- `docs/spec/2026-10-16-e4b-signal-sums/prd/`: `signal-sum.md` (SM, 14 rows), `sum-api.md` (SA,
  14), `abstain-band.md` (AB, 18), `band-api.md` (BA, 9), `sum-band-display.md` (SD, 10),
  `docs.md` (DC, 5). 70 rows.
- `docs/plan/2026-10-16-e4b-signal-sums.md`

### Units

Plan §2 is the source.

| # | Slug | PRD rows | Stacks | Pinned files |
|---|---|---|---|---|
| 1 | sum-engine | SM#1–14 | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`, `ET/data/combine_contract/evidence_cases.json`, `ST/test_frozen_record_fields.py` (:184); append-only, not flagged: `ET/test_combine_evidence_contract_fixture.py`, `ST/test_combine_evidence_contract.py` |
| 2 | sum-api | SA#1–14 | screamingface-engine, screamingface, repo | `ST/public_surface_snapshot.json` |
| 3 | band-spec | AB#1–3, AB#15 (spec v1 half) | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json` |
| 4 | band-record | AB#4–14, AB#15 (evidence v1 and answer.v1 half), AB#16–18 | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`, `ST/data/schemas/screamingface.answer.v1.json`, `ET/test_combine_gate_words.py` (:645, :761, :765), `ET/test_combine_pick_output.py` (:341-343, :352), `ET/test_combine_evidence_words.py` (:310-322), `ST/test_gate_words.py` (:524, :567, :582-589), `ST/test_evidence_words.py` (:373, :460-475), `ST/test_pick_output.py` (:250-265), `ET/data/combine_contract/evidence_cases.json`, `ST/test_frozen_record_fields.py` (:184), `ST/public_surface_snapshot.json`; append-only, not flagged: the two contract test files |
| 5 | band-api | BA#1–9 | screamingface-engine, screamingface, repo | `ST/public_surface_snapshot.json`, `ST/test_gate_api.py` (:472) |
| 6 | sum-band-display | SD#1–10 | screamingface, repo | none |
| 7 | docs | DC#1–5 | screamingface, repo | none |

`ET/` = `apps/screamingface-engine/tests/unit/`, `ST/` = `packages/screamingface/tests/`.

### Facts checked on `633fec3a1` (intake)

- No `.codegraph/` in this worktree; the facts were checked with grep and read.
- Signals union: `VerbalizedSource` E/combine/spec.py:133-142, `LogprobSource` :145-153,
  `EntropySource` :156-163, `DeclaredSource` :166-169, `CombineSpec.signals` :196, `_quiet_signals`
  :199-206, `_check_signals` :227-235, `declares_reply_sources` :304-308. `MAX_DECLARED_SIGNALS = 8`
  and `RESERVED_NAME_PREFIXES` (no `sum` prefix) E/combine/ports.py:490-491; SDK twins
  S/_signals.py:22-24.
- Gate: `GateSpec` E/combine/spec.py:172-182, `_check_gate` :238-252, `_check_agreement_gate`
  :255-259. `E/combine/gate.py`: `observed_number` :39-58, `_mean` with the Fraction fallback :61-70
  (part 5 erratum E6), `passes` :73-75.
- Endpoint: `_Declared` E/combine/endpoint.py:150-156, `_ReplyDeclared` :159-168, `_Plan` :175-198,
  `_combine` :260-289, `_signal_values` :292-309 (one column per key, no column reads another),
  `_column` :339-351, `_recorded_keys` :354-356, `_gated` :491-533 (observed, then passes, then the
  record), `_not_run` :592-596, `_gate_record` :599-609, `_abstain` :612-639, `_plan` :683-707,
  `_declared` :710-729, `_signal_read` :732-750 (the one-signal rule), `_weight` :800-806,
  `_evidence` :914-973, `_declared_record` :985-991. The log line `outcome=abstain_{reason}` :256.
- Evidence: `GateRecord` E/combine/evidence.py:113-140, `_gate_reason_holds` :168-174,
  `CombineEvidence.declared` (free JSON per entry) :205, `_check_gate` :245-275.
- Words: `AbstainReason` E/combine/ports.py:55, `AnswerReason` :56-69, `ABSTAIN_REASONS` :70-75,
  `GateBranch` :80. SDK: `AbstainReason`, `AnswerReason` S/answer.py:29-46; `GateBranch`
  S/combine_evidence.py:41; `CombineGate` :197-246; `_check_gate` :486-516; `_declared_map`
  :519-530 (accepts any entry with a `source` text); `_gate_reason` :629-634.
- SDK decoder: `_OPTIONAL_EVIDENCE_KEYS` S/_evaluation/combine_evidence.py:69, `_GATE_KEYS` :73,
  `_gate` :200. Spec: `_OPTIONAL_SPEC_KEYS` S/_evaluation/combine_spec.py:24, signals written
  :77-78, gate :79-80.
- SDK sources: `SignalSource` S/signal_sources.py:21-38, `Verbalized` :40-82, `Logprob` :91-122,
  `Entropy` :125-162, `injected_member_params` :169-183, `_SOURCES` :188-190,
  `declared_from_spec` :193-209, `python_signals` :212-216. Fusion: `_declared` S/fusion.py:108-121,
  `_declaration` :124-142 (sorted), `_check_reads` :167-183, `_check_gate_name` :186-198,
  `_check_logprob_sources` :201-219, `_check_weight_source` :222-237 (part 3 Q11 rule).
- SDK gate: `Gate` S/gate.py:36-113 (`_spec` :68-75, `_render` :107-110, `_check_agreement`
  :148-157); `_rebuilt_gate` S/reducer.py:513-537 (exact key set).
- Display: `number_html` S/_ui/combine_view.py:59-66, `_chips` :179-197, `_gate_chip` :223-230,
  `_gate_verdict` :233-237 (`passed is None` → "not run"), `_signal_head` :240-250,
  `_StepSummary` :317-358, `_summary_html` :361-375, `_gate_line` :378-389, `_mean_cell` :401-408
  (`math.fsum` raises `OverflowError` for `[1e308, 1e308]`).
- Abstain to coverage: `final_operation_abstained` E/benchmarks/operation_outputs.py:94-111 reads
  only `combine.result.status`.
- Tests that enumerate the words or the branch (pinned in unit 4): ET/test_combine_gate_words.py:645
  (branch enum), :761-766; ET/test_combine_pick_output.py:341-352; ET/test_combine_evidence_words.py:310-322;
  ST/test_gate_words.py:524, :567, :582-589; ST/test_evidence_words.py:373, :460-475;
  ST/test_pick_output.py:250-265. ET/test_combine_evidence_contract_fixture.py:461-463 needs every
  `AbstainReason` in the contract scenarios, so `in_band` comes with its contract case in unit 4.
- Contract data on base: 37 evidence cases (list L37), 47 url4 files (list L47);
  ST/test_frozen_record_fields.py:184 counts 37. `ET/test_combine_gate_words.py:618` pins the
  `GateSpec` required list (an optional key keeps it), and :634-642 the `GateRecord` required list.
- Docs constraints: ST/test_gate_docs.py:100 (no heading between Signal sources and Fusion except
  Gate), :133 (one code block in the Gate section), :150 (Browse to Accounting), :161-168 (bullets
  0–2 of the first Features list). README headings: Signal sources :930, Gate :1048, Fusion :1135,
  `## Install` :1172, Combine steps :1450.
- Brief check: every fact of the owner brief holds on this branch. One engineering change to the
  brief's first idea: the brief names `math.fsum` for the sum; the spec uses the exact rational sum
  rounded once (P5), because `math.fsum` of float products can differ (`0.31000000000000005`
  against `0.31`).

### Spec review

Run on 2026-10-16, before unit 1. 15 findings: 3 MAJOR, 12 MINOR (one of them STRUCTURAL, plan
shape only). All are fixed in commit `docs(e4b): review fixes for the E4b part 6 spec`. No finding
conflicts with an owner answer.

| # | Sev | Finding | Fix |
|---|---|---|---|
| R1 | MAJOR | `ST/test_gate_api.py:472` pins the exact `sf.Gate` parameter list; the new keyword turns it red. It was missing from the pinned list. | Added to spec §8, plan §2 and §6 (unit 5), band-api §7 row 9, and the units table. Smallest edit: append `"abstain_band"` to the list. The keyword kind and default go in the new BA#2 test. |
| R2 | MAJOR | `_rebuilt_gate` passed a non-list band to the constructor, so a hand-edited `null` rebuilt as a gate with no band. | band-api delta: a present key with a non-list value raises `_cannot_rebuild("vote")` directly (null included); only a list goes to the constructor. `null` stays in BA-E2. |
| R3 | MAJOR | The spec said to APPEND the contract scenarios to `ET/test_combine_evidence_contract_fixture.py`. A line after `if __name__ == "__main__": write_fixture()` (:491-492) is not run by the script, and `parametrize(sorted(SCENARIOS))` (:442) is read at decoration time. | Spec §8, signal-sum §7, abstain-band §7, test-plan §3 and plan §2/§6: INSERT the block after line 418 and before `def canonical_evidence` (:421); the band block goes after the sum block. |
| R4 | MINOR | The SDK `_gate_reason` check order was not given; with GR-I3 first, the second AB-E3 input fails with the wrong message. | abstain-band SDK delta: `_gate_reason` checks GB-I4 first, then GR-I3 (with the WHY). |
| R5 | MINOR | The two-pass `_signal_values` put `_Summed` items in `by_name`, which breaks the types of `_reader_numbers` and `_column`; a sum key in `_column` would give quiet, wrong values. `SumSource` was not in `spec.__all__`. | signal-sum delta: the exact code shape (`plain` keys and a non-sum `by_name` for the two helpers, then the sum columns with `sum_value`); `SumSource` in `spec.__all__`, `sum_value` in `signal_sum.__all__`. |
| R6 | MINOR | "Zero or less" missed the `MAX_WEIGHT` upper limit of `_weight`. | P13, N3 and the docs PRD weight sentence name the upper limit too. |
| R7 | MINOR | BA-E2 cited `S/reducer.py:185-186`. | Now `S/reducer.py:195-196` (`_cannot_rebuild`). |
| R8 | MINOR | AB-D6 exemplar was vague. | Exemplar is `ET/test_combine_gate.py:540-557`. |
| R9 | MINOR | "after "Signal...", in the sorted list" for `S/__init__.py`; `__all__` is not sorted. | sum-api: `"Sum"` after `"SelfCorrective"`, before `"signal"`. |
| R10 | MINOR | Rank and Filter never read a sum in an Engine run. | New scenario SM-2b (rank `top_k@1` k=1 min and filter `le 3.0` over fixture S, both choose member_2, member_3 `no_signal`) in SM#7; plan §5 and test-plan §2 updated. |
| R11 | MINOR (STRUCTURAL, plan shape) | Old unit 3 (18 rows, about 10 files, 12 pins) was too large for one implementer spec. | Split: unit 3 band-spec (AB#1–3, spec v1 half of AB#15), unit 4 band-record (the rest, SDK mirror with the contract case). AB#15 is two test functions. Old units 4–6 are now 5–7. |
| R12 | MINOR | `_gate_record(..., *, band=False)` allowed records that are not valid. | `_gate_record(gate, observed, passed, branch)`: `_gated` gives the branch, `_not_run` gives None. |
| R13 | MINOR | The new record and evidence rules would pass the lint complexity limit (part 5 erratum E3). | Helpers `_check_band_record` (rules 2, 3, 5) and `_band_reason_holds` (GB-I4, called first in `_check_gate`); SDK `_check_band_gate`. |
| R14 | MINOR | SM-D6 oracle was not exact. | "the one combine log line ends with `outcome=ok`", exemplar `ET/test_combine_gate.py:523-537`. |
| R15 | MINOR | `_mean_cell` overflow fallback is a second copy of the Engine `_mean` rule. | Kept; one WHY comment names `E/combine/gate.py` `_mean` as its twin. |

### Status

Spec and plan written headless from the owner answers of 2026-10-16. Spec review done and fixed
(seven units now). Build not started. The units
append their sections (Intent, Planned changes, Pinned edits, Test plan, Acceptance, Deviations,
Outcome) below, in the order of plan §2.

## Unit 1: signal sum in the Engine (`sum-engine`)

### Intent

PRD `signal-sum` (rows SM#1–14); ans:Q1 ("each member gets risk = sum of coefficient x
component ... recorded like any declared signal"); P1, P3–P6, P16, P17. The combine spec gets a
fourth `signals` union member `SumSource` (`{"source": "sum", "coefficients": {...}}`) with
`_check_sum` (declared component, no sum of a sum, no zero coefficient; fixed messages that echo
no value). The new pure module `E/combine/signal_sum.py` gives `sum_value`: the exact rational sum
of coefficient x value, rounded once; None when a component is None or the sum is outside the
float range. `_signal_values` computes the non-sum columns first, then the sums. A Pick, Rank,
Filter, vote weight and gate read the sum by name with no code change. New contract case
`pick_sum_min` (37 → 38). No SDK source change, no log change, no new failure code.

### Planned changes

- `E/combine/spec.py`: `SumSource`, the union member, `_check_signals` loop, `_check_sum`,
  `__all__`.
- `E/combine/signal_sum.py` (new): `sum_value`, `__all__`.
- `E/combine/endpoint.py`: import, `_Summed`, `_Plan.declared` type, two-pass `_signal_values`,
  the sum branch of `_declared`.
- New tests: `ET/test_combine_signal_sum.py` (15 functions, 26 items),
  `ET/test_combine_signal_sum_words.py` (2).
- Test inserts: the `pick_sum_min` block in `ET/test_combine_evidence_contract_fixture.py` (after
  line 418), one `_EXPECTED_NAMES |=` line in `ST/test_combine_evidence_contract.py` (after line
  61).

### Pinned edits

- `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`:
  regenerated; adds `$defs.SumSource`, the `sum` discriminator mapping and one `oneOf` item only.
- `apps/screamingface-engine/tests/unit/data/combine_contract/evidence_cases.json`: regenerated;
  adds the case `pick_sum_min` at the end; the 37 old cases keep their bytes.
- `packages/screamingface/tests/test_frozen_record_fields.py` (line 184: 37 → 38).
- `apps/screamingface-engine/tests/unit/test_combine_gate.py` (lines 566-567; deviation D-1):
  `sorted((*L32, *GATE_CASES))` → `sorted((*L32, *GATE_CASES, "pick_sum_min"))`;
  `list(cases)[-5:]` → `list(cases)[32:37]`.

### Test plan

- 14 PRD rows in PRD §7 order. CHAR: SM#1 (fixed lists L37 and L47, 48 specs). RED: SM#2–11,
  SM#14. PIN: SM#12 (contract case, both sides), SM#13 (spec v1 snapshot).
- Stubs in commit A: `SumSource` (final, not in the union), `sum_value` raising
  `NotImplementedError`. Commit A: ET new files 20 failed / 8 passed; edited ET files 4 failed;
  SDK 3 failed.
- Commit A run (the focused lists of §9, real counts): Engine focused list 24 failed / 164
  passed (the 20 new-file reds above, plus the 4 edited-file reds); SDK focused list 3 failed /
  154 passed. Every red row fails for its stated reason; no import or collection error.
- Oracles: fixture S and signals S of signal-sum §3 (exact sums with `fractions.Fraction`), the
  SM-D1/D2 sums, the fixed rule messages.

### Acceptance

- A spec with a sum parses; each SM-E1 input is `combine_spec_invalid` with its fixed message,
  no echo.
- Each member records `risk` = the exact sum rounded once, None when a component is None or the
  sum is out of range; the key order is unchanged.
- Pick, Rank, Filter, a vote weight and a gate `chosen:` / `mean:` read the sum by name.
- `declared` records the sum entry as the spec wrote it.
- `pick_sum_min` is byte equal on both sides; the 37 old cases and the 48 url4 specs keep their
  bytes.
- Gates: append-only lists only the four pinned files; every other gate green; `repo` green.

### Deviations

- (pre-filled) D-1: `ET/test_combine_gate.py:566-567` (part 5) pins the exact case set and the
  last five case names of `evidence_cases.json`; any new case turns it red. Smallest edit as above;
  it is a fourth pinned file of this unit (not in spec §8 / plan §6). Unit 4 edits line 566 again
  (`"vote_gate_band"`); line 567 needs no second edit.
- (pre-filled) D-2: PRD §7 lists row 1 in both new files; it is in
  `ET/test_combine_signal_sum_words.py` only. Row 12 also has a named test with hand oracles in
  `ET/test_combine_signal_sum.py`, beside the parametrized byte tests.
- (pre-filled) D-3: SM#3 checks that each message ENDS with its rule text; the seven union-level
  inputs give the existing quiet message, so those seven items pass in commit A too.
- (pre-filled) D-4: SM#14 (SM-E2) uses the built-in operators (`by_signal@1` reads `sev_a`,
  weights read `risk`), not the fake registry: the fake registry has no `verbalized` source, so
  `_declared` would refuse the spec first.

### Notes for the review

- `_check_sum` runs inside the model validator, so its error location is `spec` and the message
  is `combine spec is invalid: spec: Value error, <rule>`.
- For unit 4: `ET/test_combine_gate.py:566` must add `"vote_gate_band"` (one more pinned edit).
- Part 7 (`consistency@N`) adds its own union member and `_declared` branch; a `consistency` name
  can be a sum component with no change (C10).

### Outcome

(fill at the end of the unit)
