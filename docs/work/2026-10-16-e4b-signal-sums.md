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

Status: done. Unit 1 is built. Commit A (`1c2788a40`) holds the RED tests, the stubs and the
pinned edits of §8.3 and §8.4. Commit B (`43c73bc4b`) holds the code and the two regenerated files.
Commit C holds this outcome. The part stays `in_progress`.

Files of commit B:

- `E/combine/spec.py`: `SumSource`, the union member, `_check_signals` loop, `_check_sum`.
- `E/combine/signal_sum.py`: `sum_value` (exact `Fraction` sum, rounded once).
- `E/combine/endpoint.py`: import, `_Summed`, `_Plan.declared` type, two-pass `_signal_values`,
  the sum branch of `_declared`.
- `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`: 30 lines added, 0 removed.
- `ET/data/combine_contract/evidence_cases.json`: 94 lines added, 0 removed (`pick_sum_min`).

Test counts:

- Focused Engine tests, after commit B: 189 passed (the nine files of spec §9).
- New Engine files before the regeneration of §8.1 and §8.2: 26 passed, 2 failed (the byte test of
  `pick_sum_min` and the schema snapshot test). Both pass after the regeneration.
- Focused SDK tests, after commit B: 158 passed.
- Lint on the changed Engine files (`ruff format --check`, `ruff check`, `pyright`): clean.

Append-only check (first run, before `--skip-append-only`):

- `screamingface-engine`: three offenders, all pinned. `tests/unit/data/combine_contract/evidence_cases.json`,
  `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`,
  `tests/unit/test_combine_gate.py` (lines 566 and 567, D-1).
- `screamingface`: one offender, pinned. `tests/test_frozen_record_fields.py` (line 184).
- `repo`: green with the check on.

Gate results:

- `screamingface-engine`: the append-only check was the only red result. The rerun with
  `--skip-append-only` gave ALL GATES GREEN (ruff check, ruff format, pyright, check_layering,
  pytest with coverage).
- `screamingface`: the append-only check was the only red result. The rerun with
  `--skip-append-only` gave ALL GATES GREEN (ruff, pyright, pytest with coverage, notebooks,
  `uv build`, distribution check).
- `repo`: ALL GATES GREEN, with the append-only check on.

Flakes: none seen in this unit.

Pinned edits: the four files of the Pinned edits section above. No other test file was edited in
commit B.

### Review fixes

Review of commit `43c73bc4b` (and the ledger commit `845c451d7`) gave four findings. Results:

- MINOR, `-0.0` from `sum_value`: fixed. RED commit `0c5734402` adds
  `test_sum_value_never_gives_negative_zero` (it failed with `-0.0`). Fix commit: `sum_value`
  returns `float(total) + 0.0`, the same idiom as `logprob_forms.py`. The module docstring
  invariant ("never -0.0") is now true. Unit spec §6 row "-0.0 cannot happen" was wrong; recorded
  as erratum E2 in `docs/spec/2026-10-16-e4b-signal-sums/00-overview.md` §11.
- MINOR, `ET/test_combine_gate.py:566-567` not in the PINNED list: no code change. It is already
  pinned in this unit (D-1, erratum E1). Owner approval is still needed after the build. Unit 4
  must also edit line 566 (`"vote_gate_band"`).
- MINOR, RED commit subject differs from spec §11 A: no change. History is not rewritten.
- MINOR (optional), `sum_value` takes name and value maps: no change. The spec pins the
  signature.

Gates after the fix (base `633fec3a1`):

- `screamingface-engine`: the append-only check was the only red result, with the same three
  pinned offenders (`evidence_cases.json`, `screamingface.combine-spec.v1.json`,
  `test_combine_gate.py` lines 566-567). Rerun with `--skip-append-only`: ALL GATES GREEN (ruff
  check, ruff format, pyright, check_layering, pytest with coverage).
- `screamingface`: the append-only check was the only red result in the earlier unit, with the
  pinned offender `test_frozen_record_fields.py` line 184. Rerun with `--skip-append-only`: ALL
  GATES GREEN (ruff, pyright, pytest with coverage, check_notebooks, `uv build`,
  check_distribution).
- `repo`: ALL GATES GREEN, with the append-only check on.

Pinned edits in this fix: none new. Every pinned edit is from the earlier unit 1 commits.

## Unit 2: sum-api (`sf.Sum`)

### Intent

PRD `sum-api` rows SA#1–SA#14 (ans:Q1; P2–P4, P13, P15, P17). The SDK gets the public declared
derived signal `sf.Sum(coefficients)`: a `SignalSource` with the wire word `"sum"`, its terms
sorted by name as floats in a read-only mapping, every constructor check of the PRD table, and no
hash. `sf.Fusion` refuses, before any call, a sum component that it does not declare, a sum of a
sum (also of itself), and a vote weight that reads a sum which adds `sf.Logprob("mean")`,
`sf.Logprob("sum")` or `sf.Entropy`. The compile writes `{"source": "sum", "coefficients": {...}}`;
`Url4.to_python()` rebuilds it through `_SOURCES`. One SDK-compiled fixture (recipe R, a Pick of
the lowest `risk`) runs offline in the Engine world with exactly three calls.

### Planned changes

- `S/signal_sources.py`: `Sum`, `_MAX_SUM_TERMS`; helpers `_sum_terms`, `_sum_name`,
  `_sum_coefficient`, `_is_wire_term`; `_SOURCES["sum"]`; `__all__`; module docstring.
- `S/fusion.py`: `_check_sums` (called from `_declaration`), `_check_sum_component`,
  `_check_sum_weight` (called from `_check_weight_source`); `Fusion` docstring sentence.
- `S/__init__.py`: export `Sum` (after `"SelfCorrective"`, before `"signal"`).
- New tests `ST/test_signal_sum_api.py` (45 ids), `ST/test_sum_contract_fixtures.py` (1 id),
  `ET/test_combine_sum_run.py` (1 id). New data
  `ET/data/combine_contract/sum_pick_candidate.url4`.

### Pinned edits

- `packages/screamingface/tests/public_surface_snapshot.json` (regenerated with
  `UPDATE_SURFACE_SNAPSHOT=1`): `"Sum"` in the `screamingface` `__all__`, and the `exports` entry
  `Sum` (`__init__(self, coefficients: 'Mapping[str, float]')`, field `coefficients`, attribute
  `source`).

### Test plan

- 14 rows: CHAR SA#1; RED SA#2–SA#13; PIN SA#14 (the regenerated snapshot, checked by the
  existing `test_public_surface_matches_the_committed_snapshot`).
- Stubs (commit A): `Sum` with the exact `__init__` signature, whose `__init__`, `_spec` and
  `_from_spec` raise `NotImplementedError`; exported from `screamingface` and
  `screamingface.signal_sources`. No `_SOURCES` entry yet. Expected RED: SDK `44 failed, 2 passed`
  for the two new files; the snapshot test fails; Engine `1 failed` (fixture missing).
- Oracles: the PRD messages (exact), recipe R and its decoded signals, fixture S with the
  hand-computed sums 5.0 and 2.5 (signal-sum PRD §3).

### Acceptance

- The 14 rows pass. SA#1 passes before and after the change.
- The snapshot diff is only the two hunks of the pinned edit.
- `git diff U1 --stat` on the two test folders lists only the new files and the snapshot.
- Gates: `screamingface-engine`, `screamingface`, `repo` green, except the append-only check
  against `633fec3a1`, which lists only the pinned files of units 1–2; green with
  `--skip-append-only`.

### Deviations

- D-1 (SA-E2 `listed`): the PRD says "the declared names joined by ', '" with no order. Built
  rule: the names are sorted (`", ".join(sorted(declared))`), as the Fusion stores them; SA#4
  checks both dict orders. The PRD oracle (`declared: risk, sev_a`) is unchanged.
- D-2 (SA#6 scope): the row also checks `sf.Median` and `sf.Mean` weights (the same
  `_check_weight_source` path; the part 3 `_WEIGHTED` precedent in `ST/test_logprob_source.py`).
- D-3 (SA#1 oracle): the two fixtures also hold no `"source":"sum"`.
- D-4 (SA#11 addition): a direct `declared_from_spec` test (one rebuild, seven refusals), as part 3
  did for Logprob and Entropy.
- D-5 (helpers): `_sum_terms`, `_sum_name`, `_sum_coefficient`, `_is_wire_term`,
  `_check_sum_component`, `_check_sum_weight` are private helpers the PRD does not name. They keep
  the ruff caps (max-branches 7, max-returns 3, mccabe 8).
- D-6 (`_check_sums` call): `_check_sums(value)` runs on the unsorted map, as the PRD says; it
  sorts inside, so the result does not depend on the dict order.

### Outcome

- **Status:** Built. The code, the fixture and the pinned snapshot are in commit B. The part
  stays `in_progress`.
- **Actual files:**
  - `S/signal_sources.py`: class `Sum`, `_MAX_SUM_TERMS`, helpers `_sum_terms`, `_sum_name`,
    `_sum_coefficient`, `_is_wire_term`; `_SOURCES["sum"]`; the module docstring.
  - `S/fusion.py`: `_check_sums`, `_check_sum_component`, `_check_sum_weight`; the sum branch of
    `_check_weight_source`; the `Fusion` docstring.
  - `ET/data/combine_contract/sum_pick_candidate.url4`: new, written by `write_fixture`.
  - `ST/public_surface_snapshot.json`: PINNED, regenerated. Two hunks: `"Sum"` in `__all__` and
    the `Sum` export entry.
  - `ST/test_signal_sum_api.py`: one test edit, see Deviations (build).
- **Commits:** A = `0c6f80c68` (RED, made before this build). B = the commit that holds this
  Outcome. C = the commit `docs(e4b): build errata for part 6 unit 2`.
- **U1 (unit 1 tip):** `b3b6d2140`.
- **RED log:** Not re-run in this build. Commit A holds the RED tests and the stub.
- **Gates:**
  - Focused SDK list (spec §9, 16 files): 298 passed.
  - Focused Engine list (spec §9, 5 files): 43 passed.
  - `screamingface-engine`: the append-only check was red (three offenders). With
    `--skip-append-only`: ALL GATES GREEN (ruff check, ruff format, pyright, check_layering,
    pytest with coverage).
  - `screamingface`: the append-only check was red (two offenders). With
    `--skip-append-only`: ALL GATES GREEN (ruff, pyright, pytest with coverage 95 percent floor,
    notebooks, `uv build`, distribution check).
  - `repo`: ALL GATES GREEN, with the append-only check on.
- **Append-only list:**
  - `screamingface-engine`: `tests/unit/data/combine_contract/evidence_cases.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`,
    `tests/unit/test_combine_gate.py` (lines 566 and 567). All three are unit 1 pins (D-1).
  - `screamingface`: `tests/public_surface_snapshot.json` (unit 2 PIN, §8), and
    `tests/test_frozen_record_fields.py` (line 184, unit 1 pin).
- **Flakes:** None seen in this unit.
- **Deviations (build):**
  - B-1 (SA#7 test, one test edit). `test_rules_and_gates_read_a_sum_by_name` compiled the
    Fusion as the root candidate. The existing compile refuses a Rank or a Filter that ends a
    candidate (`a Rank must be followed by another stage`). The Pick and Vote readers were not
    affected. Fix: the test now compiles `sf.Pipeline([fusion, "provider/next"])`, the precedent of
    `ST/test_rank_by_signal.py` (`_wrapped`). The edit is 3 lines added and 1 removed, in
    `ST/test_signal_sum_api.py` only. It is a fix of a real test bug, not a loosened assertion.
    Errata E3 records it in the overview.
  - B-2: The unit 2 Fusion and SDK code follows spec §2.1 and §2.4 exactly. No other deviation.

## Unit 3: band-spec (`gate.abstain_band` in the Engine spec)

**Status:** in_progress

### Intent

PRD `abstain-band` rows AB#1–3 and the spec v1 half of AB#15 (ans:Q2; P7, P8; C4; BD-I1,
BD-I2). The Engine combine spec gets the optional gate key `abstain_band: [lo, hi]`: two finite
numbers, `lo <= hi`, and `0 <= lo <= hi <= 1` for an agreement gate. An explicit null is refused.
Each refusal is a fixed message with no value. No rule ties the band to the threshold. Nothing
decides on the band yet: the decision, the word `in_band`, the gate record and the SDK mirror are
unit 4; the SDK keyword is unit 5.

### Planned changes

- `E/combine/spec.py`: `GateSpec.abstain_band: list[float] | None = Field(default=None,
  min_length=2, max_length=2)` (last field; a comment, not a docstring line, so the schema
  `description` keeps its bytes); new helper `_check_band(gate)` after `_check_agreement_gate`;
  `_check_gate` calls it as its last line; one sentence in the module docstring.
- New test file `ET/test_combine_band.py` (5 test functions, 15 cases); helpers `_band_gate`,
  `_vote_with_band`, `_spec_failure`, `_combine_specs`, `_pinned`, `_bytes` for unit 4 to reuse.

### Pinned edits

- `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`
  (deleted, then regenerated with `UPDATE_SCHEMA_SNAPSHOT=1`): one hunk, 17 added lines,
  `$defs.GateSpec.properties.abstain_band` (`anyOf` array of two numbers or null, default null,
  title "Abstain Band"). `required` does not change. The schema id does not change.

### Test plan

- 4 rows: CHAR AB#1; RED AB#2, AB#3 (two functions: the 8 PRD inputs, and 4 non-finite edge
  inputs); PIN AB#15 spec v1 half.
- No stub: the commit A code refuses the key as an extra key. Expected RED: `6 failed, 9 passed`
  (`test_engine_parses_a_gate_band`, the AB#3 ids `explicit-null`, `lo-above-hi`,
  `agreement-above-one`, `agreement-below-zero`, and `test_spec_schema_snapshot_holds_the_band`).
- Oracles: the PRD messages (abstain-band §2.1), the AB-1 and AB-E1 inputs, the pydantic schema
  rendering of an optional two-item float list (checked on a copy on `644e34b7b`).

### Acceptance

- The 15 cases pass. AB#1 passes before and after the change.
- The snapshot diff is exactly the one hunk of the pinned edit.
- `git diff U2 --stat` lists only `E/combine/spec.py`, `ET/test_combine_band.py`, the spec v1
  snapshot and this ledger.
- Gates: `screamingface-engine`, `screamingface`, `repo` green, except the append-only check
  against `633fec3a1`, which lists only the pinned files of units 1–3; green with
  `--skip-append-only`.

### Deviations

- D-1 (PRD §2.1 call shape): the PRD says "when `abstain_band` is in `gate.model_fields_set`,
  `_check_band(gate)`". Built: `_check_gate` calls `_check_band(gate)` with no condition, and the
  guard is the first line of `_check_band`. Same behavior. WHY: `_check_gate` has 6 branches, and
  the Engine caps are max-branches 7 and mccabe 8 (part 5 erratum E3).
- D-2 (addition, P7 "finite"): AB#3 has a second test function,
  `test_engine_refuses_a_band_that_is_not_finite_without_echo` (`1e400`, `-1e400` overflow to
  ±inf in `json.loads` and are refused by `allow_inf_nan=False`; `NaN` and `Infinity` are refused
  by `loads_bounded`).
- D-3 (PRD §7 file): the PRD names no file for AB#15. The spec v1 half is in
  `ET/test_combine_band.py`; unit 4 adds the evidence and answer half as a second function there.
- D-4 (AB#2 scope): AB#2 also holds the valid inputs of AB-E1 (last sentence), the one-point band
  (P7), the int-to-float rule, the band far from the threshold (P8), and a gate with no band.
- D-5 (docs): the `GateSpec` class docstring is not changed (it is the schema `description`); the
  field has a `#` comment instead.

### Outcome (fill at the end, before commit B)

- RED result: commit A (`1a41af431`) gave `6 failed, 9 passed` in `ET/test_combine_band.py`.
- GREEN result: `15 passed` in `ET/test_combine_band.py`. The related set of nine Engine test files
  gave `140 passed`. `ruff check`, `ruff format --check` and `pyright` were clean on the two files.
- Snapshot diff: one hunk, 17 added lines, in `$defs.GateSpec.properties` before `cmp`. No removed
  line. The file was deleted and regenerated with `UPDATE_SCHEMA_SNAPSHOT=1`, then passed
  `test_wire_schema_freeze.py`.
- Gates (commit B code, before the ledger Outcome was written):
  - `screamingface-engine`: append-only check red. Offenders, all unit 1 or unit 2 pins:
    `tests/unit/data/combine_contract/evidence_cases.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json` (this unit's
    pin), and `tests/unit/test_combine_gate.py` (lines 566-567, unit 1 D-1; not in the spec list
    of units 1-3 pins, but recorded in the unit 1 ledger). Rerun with `--skip-append-only`: all
    green (ruff check, ruff format, pyright, layering, pytest with coverage).
  - `screamingface`: append-only check red. Offenders, both unit 1 or unit 2 pins:
    `tests/public_surface_snapshot.json` and `tests/test_frozen_record_fields.py` (line 184).
    Rerun with `--skip-append-only`: all green (ruff, pyright, pytest with coverage 95, notebooks,
    build, distribution).
  - `repo`: all green, including the append-only check against `633fec3a1`.
- Flakes: none recorded in this unit.
