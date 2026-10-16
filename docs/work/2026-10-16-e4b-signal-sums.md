---
ticket: unfiled   # epic OME-1290 is the parent; the leaf is filed at PR-open
stack: screamingface-engine, screamingface, repo
status: planned   # planned | in_progress | done | blocked
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
| 3 | band-record | AB#1–18 | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`, `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`, `ST/data/schemas/screamingface.answer.v1.json`, `ET/test_combine_gate_words.py` (:645, :761, :765), `ET/test_combine_pick_output.py` (:341-343, :352), `ET/test_combine_evidence_words.py` (:310-322), `ST/test_gate_words.py` (:524, :567, :582-589), `ST/test_evidence_words.py` (:373, :460-475), `ST/test_pick_output.py` (:250-265), `ET/data/combine_contract/evidence_cases.json`, `ST/test_frozen_record_fields.py` (:184), `ST/public_surface_snapshot.json`; append-only, not flagged: the two contract test files |
| 4 | band-api | BA#1–9 | screamingface-engine, screamingface, repo | `ST/public_surface_snapshot.json` |
| 5 | sum-band-display | SD#1–10 | screamingface, repo | none |
| 6 | docs | DC#1–5 | screamingface, repo | none |

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
- Tests that enumerate the words or the branch (pinned in unit 3): ET/test_combine_gate_words.py:645
  (branch enum), :761-766; ET/test_combine_pick_output.py:341-352; ET/test_combine_evidence_words.py:310-322;
  ST/test_gate_words.py:524, :567, :582-589; ST/test_evidence_words.py:373, :460-475;
  ST/test_pick_output.py:250-265. ET/test_combine_evidence_contract_fixture.py:461-463 needs every
  `AbstainReason` in the contract scenarios, so `in_band` comes with its contract case in unit 3.
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

Not run yet. The orchestrator runs it before unit 1; the findings and their fixes go here.

### Status

Spec and plan written headless from the owner answers of 2026-10-16. Build not started. The units
append their sections (Intent, Planned changes, Pinned edits, Test plan, Acceptance, Deviations,
Outcome) below, in the order of plan §2.
