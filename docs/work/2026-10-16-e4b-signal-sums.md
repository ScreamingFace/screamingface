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

## Unit 4: band-record (`band-record`)

**Status:** in_progress

### Intent

PRD `abstain-band` rows AB#4–14, AB#15 (evidence v1 and answer.v1 half), AB#16–18 (ans:Q2, P8–P12,
P17, P18). The vote gate checks the abstain band before the comparison. Inside the closed band the
Case abstains with the new reason `in_band`, for every `otherwise`, and no comparison is made
(`passed` null, `branch` "band"). Outside the band, or with no number, the gate compares as in part
5. The gate record holds the band (`abstain_band`, after `otherwise`, only when set). The band
branch never reads a fallback reply (FB-I1, C8). `in_band` and `band` join the words on both sides,
with GB-I1 to GB-I4. The SDK mirror and the contract case `vote_gate_band` come in the same unit
(38 → 39 cases).

### Planned changes

- `E/combine/ports.py`: `in_band` in `AbstainReason`, `AnswerReason` (last), `ABSTAIN_REASONS`;
  `band` in `GateBranch`.
- `E/combine/gate.py`: new pure `in_band(observed, band)`.
- `E/combine/endpoint.py`: `_gated` checks the band first (one flow, `banded` flag);
  `_gate_record(gate, observed, passed, branch)` copies the band; `_not_run`; docstrings.
- `E/combine/evidence.py`: `GateRecord.abstain_band`; `_check_band_record` (GB-I1–I3, GR-I1');
  `_band_reason_holds` (GB-I4); `_check_gate_reasons` (GB-I4, then GR-I3); GR-I4' reads `branch`.
- `S/answer.py`: `in_band` in `AbstainReason` and `AnswerReason`.
- `S/combine_evidence.py`: `GateBranch` gains `band`; `CombineGate.abstain_band`; `_gate_band`;
  `_check_band_gate`; `_gate_reason` GB-I4 first; GR-I4' reads `branch`.
- `S/_evaluation/combine_evidence.py`: `_OPTIONAL_GATE_KEYS`, `_gate` reads the band,
  `_abstain_band`.
- Tests: appends to `ET/test_combine_band.py`; new `ST/test_band_words.py`; the `vote_gate_band`
  block in `ET/test_combine_evidence_contract_fixture.py`; one line in
  `ST/test_combine_evidence_contract.py`.

### Pinned edits

Made in commit A (test text only, on the approved list):
`ET/test_combine_gate_words.py` (:645, :761, :765), `ET/test_combine_pick_output.py` (:341-343,
:352), `ET/test_combine_evidence_words.py` (:321 +1), `ST/test_gate_words.py` (:524, :567, :582,
:583, :586 +1), `ST/test_evidence_words.py` (:373, :460, :467 +1), `ST/test_pick_output.py`
(:250, :255 +1), `ST/test_frozen_record_fields.py` (:184 38 → 39).

Regenerated in commit B (data only): `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
`ST/data/schemas/screamingface.answer.v1.json`, `ET/data/combine_contract/evidence_cases.json`,
`ST/public_surface_snapshot.json`.

Append-only, not flagged: `ET/test_combine_evidence_contract_fixture.py`,
`ST/test_combine_evidence_contract.py`.

### Test plan

- 15 rows (AB#4–14, AB#15 unit 4 half, AB#16–18), 17 test functions. All RED in commit A; commit A
  changes no source file, and every test imports only names that exist, so each row fails on its
  behavior. AB#15, AB#16, AB#18 are PIN rows (regenerated files).
- Expected RED: `ET/test_combine_band.py` unit 4 part: 12 items failed; `ST/test_band_words.py`: 6
  failed; the pinned tests of the spec §8 items 1–8 failed.
- Actual RED (commit A): `ET/test_combine_band.py` 12 failed, 15 passed (the 15 unit 3 cases pass).
  The six focused Engine files: 18 failed, 210 passed. `ST/test_band_words.py` 6 failed. The six
  focused SDK files: 14 failed, 141 passed (the 6 band tests, and 8 pinned or contract tests).
  `ruff check` and `ruff format --check` clean on `tests/unit` (engine) and `tests` (SDK).

### Acceptance

- Fixture B, `band(0.6, 0.7, 0.7, abstain)`: output `""`, evidence = the AB-2 wire (`in_band`,
  `branch "band"`, `passed null`, `abstain_band [0.6, 0.7]`, tally / agreement / tie kept).
- Both edges of the band are inside; the adjacent floats are outside.
- `band(0.7, 0.9, 0.6, …)` gives the part 5 majority bytes plus the band key.
- Judge and writer: the same bytes with and without the fallback reply.
- The log line ends with `outcome=abstain_in_band`; the Case is a final abstain.
- `evidence_cases.json` has 39 cases; the 38 old cases keep their bytes.
- Gates: `screamingface-engine`, `screamingface`, `repo` green (append-only offenders = the pinned
  files only).

### Deviations

- `_gated` uses one flow (a `banded` flag and one abstain return for `in_band` and `gate_not_met`)
  and not an early band return, because ruff `max-returns = 3`. The behavior is the PRD's: the band
  is checked before the comparison, and `passes` is not called inside the band.
- The Engine `_check_gate` calls the new helper `_check_gate_reasons` (GB-I4, then GR-I3) on its
  first line, in place of its GR-I3 `if`, because ruff `max-branches = 7` and mccabe 8. The PRD
  said "calls `_band_reason_holds` on its first line, then the existing GR-I3 check": the order is
  the same.
- NOT MADE in commit A (open question for the owner): `ST/test_gate_words.py:326` (the `_one_of`
  message lists the sorted branch words, so it reads `band, fallback, majority` after this unit).
  The unit spec §8 item 4 names this edit, but the approved pin list of this unit does not. The
  line is left as it is in commit A. It passes in commit A and fails after commit B.
- NOT MADE in commit A (open question for the owner): `ET/test_combine_gate.py:566-567` (the GD#19
  test lists the whole fixture; the spec §8 item 8 sets the final text). The approved pin list of
  this unit does not name it. Unit 1 already edited these lines (unit 1 ledger). In commit A the
  test fails because the fixture now holds `vote_gate_band`.
- AB#15 (unit 4 half), AB#16 and AB#18 are in `ST/test_band_words.py` (the PRD names no file). The
  Engine half of AB#16 is the existing parametrized fixture byte test.
- New helper names (not in the PRD): Engine `_check_gate_reasons`, `_BAND_REASON`; SDK `_gate_band`
  (`S/combine_evidence.py`), `_abstain_band` and `_OPTIONAL_GATE_KEYS`
  (`S/_evaluation/combine_evidence.py`).
- AB#5 also checks the upper edge (`band(0.6, 2/3)` is inside) and the adjacent floats.
- RED reason, AB#7 (judge and writer): the run without a reply raises `SpecInvalid` (a subclass of
  `CombineError`), from the part 5 `fallback_label` / `fallback_text` step. The PRD names
  `CombineError`. The failure is the same: the fallback runs before the band exists.
- RED reason, AB#13 (SDK refusals): the decoder refuses the key `abstain_band` first
  (`ExecutionError`), so the first line of the test fails. The PRD names a `TypeError` from the
  keyword. The failure is the same: no band support yet.
- Build change, schema text: the `GateRecord` docstring of the Engine evidence v1 schema now
  has the E4b part 6 paragraph (§2.4 gives that text). So the regenerated
  `screamingface.combine-evidence.v1.json` also shows a changed `description` for `GateRecord`.
  The §8 item 9 list did not name it. No other change in the schema.
- Build change, lint: one comment line in `E/combine/endpoint.py` (`_abstain`) was re-wrapped to 100
  columns (ruff E501). No behavior change.
- Build change, pinned edits made in commit B (not in commit A): `ST/test_gate_words.py:326`
  (§8 item 4, the `_one_of` message) and `ET/test_combine_gate.py:566` (§8 item 8, only line 566;
  line 567 came from unit 1). Both are named in this section above. The owner approves them.

### Notes for the review

- FB-I1: grep shows `fallback_judge` / `fallback_writer` read only in `combine/gate.py`, and
  `_fallback` is reached only when `banded` is False.
- C9: `combine/gate.py` imports only the standard library, `combine.ports`, `combine.spec`;
  `combine/evidence.py` imports only pydantic and `combine.ports`.
- C10 (part 7): this unit adds no union member and does not touch `_declared`.

### Outcome (fill at the end — required before COMMIT)

- **Status:** GREEN. The unit is built. Every gate is green or green except the append-only
  check. The append-only offenders are listed below and all are pinned files.
- **Actual files:**
  - Engine source: `E/combine/ports.py`, `E/combine/gate.py`, `E/combine/endpoint.py`,
    `E/combine/evidence.py`.
  - SDK source: `S/answer.py`, `S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`.
  - Regenerated data: `ET/data/combine_contract/evidence_cases.json` (39 cases),
    `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
    `ST/data/schemas/screamingface.answer.v1.json`, `ST/public_surface_snapshot.json`.
  - Pinned test edits in this commit: `ST/test_gate_words.py:326`, `ET/test_combine_gate.py:566`.
  - Test files from commit A are not changed by this unit's GREEN work, except those two lines.
- **Commits:** A = `e1fe049d2` (RED, made before this build). B = the code commit of this unit
  (this section and its Outcome). C = the docs commit of this unit (the errata in the overview).
- **Gates:**
  - Focused Engine run (`tests/unit/test_combine_*.py`, `test_wire_schema_freeze.py`,
    `test_abstain_*.py`): 1297 passed.
  - Focused SDK run (14 test files of spec §9 step 7): 266 passed, 2 warnings.
  - Pyright, both stacks (touched files): 0 errors.
  - `screamingface-engine`, base `4cbf26582`: append-only red (offenders below). With
    `--skip-append-only`: ruff check, ruff format, pyright, layering, pytest (cov 80%): green.
  - `screamingface`, base `4cbf26582`: append-only red (offenders below). With
    `--skip-append-only`: ruff check, ruff format, pyright, pytest (cov 95%), notebooks, build,
    distribution: green.
  - `repo`, base `4cbf26582`: green (append-only check passed).
  - `screamingface-engine`, base `633fec3a1`: append-only red (offenders below). With
    `--skip-append-only`: green.
  - `screamingface`, base `633fec3a1`: append-only red (offenders below). With
    `--skip-append-only`: green.
  - `repo`, base `633fec3a1`: green.
  - Append-only offenders, base `4cbf26582`, Engine: `ET/data/combine_contract/evidence_cases.json`,
    `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
    `ET/test_combine_evidence_words.py`, `ET/test_combine_gate.py`,
    `ET/test_combine_gate_words.py`, `ET/test_combine_pick_output.py`.
  - Append-only offenders, base `4cbf26582`, SDK: `ST/data/schemas/screamingface.answer.v1.json`,
    `ST/public_surface_snapshot.json`, `ST/test_evidence_words.py`,
    `ST/test_frozen_record_fields.py`, `ST/test_gate_words.py`, `ST/test_pick_output.py`.
  - Base `633fec3a1` adds one more Engine offender: the unit 3 pinned file
    `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`. All offenders are
    pinned files. None is a test file that this unit did not pin.
  - Flakes: none in these runs. No known timing flake failed.
- **RED log:** Engine: 18 failed, 210 passed (the six files of spec §9). The failures are the
  unit 4 tests, the pinned snapshot tests and `vote_gate_band`. SDK: 14 failed, 141 passed. The
  failures are `test_band_words.py` (6), the pinned tests and the `vote_gate_band` tests. No
  `ImportError` and no `NameError`. Pyright was not run on the RED tree.
- **Pinned edits made:**
  - In commit A (already committed, §8 items 1–7): `ET/test_combine_gate_words.py`,
    `ET/test_combine_pick_output.py`, `ET/test_combine_evidence_words.py`,
    `ST/test_gate_words.py` (except line 326), `ST/test_evidence_words.py`,
    `ST/test_pick_output.py`, `ST/test_frozen_record_fields.py`.
  - In commit B (this build): the regenerated files of §8 items 9–12 (the Engine evidence v1
    schema with its `GateRecord` description, the SDK answer v1 snapshot, the 39-case
    `evidence_cases.json`, the public surface snapshot). The two text edits: `ST/test_gate_words.py:326`
    and `ET/test_combine_gate.py:566`.
  - The 38 old cases of `evidence_cases.json` kept their bytes (checked with a script before
    commit B).

## Unit 5: band-api (`sf.Gate(..., abstain_band=(lo, hi))`)

**Status:** GREEN (built; see Outcome)

### Intent

PRD `band-api` rows BA#1–9 (ans:Q2; P7, P8, P11, P15; contracts C4, C6). The SDK gate gets the
keyword-only `abstain_band=None` and the last field `abstain_band`. The constructor checks the
band (a pair of finite numbers, `lo <= hi`, an agreement band in `[0, 1]`) and stores two floats.
The spec gate gets `"abstain_band": [lo, hi]` only when set; the repr and `Url4.to_python()` write
`abstain_band=(lo, hi)` after `otherwise=`. `_rebuilt_gate` accepts the part 5 keys plus the
optional band; a present non-list band (null included) is "cannot rebuild". The SDK-compiled
fixture `gate_band_vote_candidate.url4` (recipe G) runs offline in the Engine world: in the band
the Case abstains with `in_band`; below it the majority stands.

### Planned changes

- `S/gate.py`: field and keyword `abstain_band`; `_band`, `_band_pair`, `_BAND_PAIR`,
  `_BAND_FINITE`; `_spec`, `_render`; docstrings.
- `S/reducer.py`: `_GATE_SPEC_KEYS`, `_BAND_KEY`, `_rebuilt_band`; `_rebuilt_gate` key check and
  `abstain_band=` pass-through.
- New `ST/test_band_api.py` (rows 1–6, 24 test ids). Appended to `ST/test_sum_contract_fixtures.py`:
  builder `gate_band_vote_url4`, one `BUILDERS |=` line, `test_gate_band_fixture_matches_the_sdk_compile`.
  Appended to `ET/test_combine_sum_run.py`: `test_engine_runs_the_band_fixture_offline` (2 ids).
  New data `ET/data/combine_contract/gate_band_vote_candidate.url4`.

### Pinned edits

- `packages/screamingface/tests/public_surface_snapshot.json` (regenerated with
  `UPDATE_SURFACE_SNAPSHOT=1`): `Gate.__init__` gains
  `abstain_band: 'tuple[float, float] | None' = None`; `Gate` member `abstain_band`.
- `packages/screamingface/tests/test_gate_api.py` line 472: the parameter list gains
  `"abstain_band"`.

### Test plan

- 9 rows: CHAR BA#1; RED BA#2–8 (BA#6 also has one guard function that passes in commit A);
  PIN BA#9.
- Stub (commit A): `Gate.__init__` takes `abstain_band` and stores None. Expected RED:
  `test_band_api.py` 22 failed, 2 passed; BA#7 1 failed; BA#8 2 failed. No import or keyword
  error.
- Oracles: the PRD messages; exact sums with `fractions.Fraction` (risk 5.0, 2.5, 2.0 → mean
  `3.1666666666666665`; 1.0, 1.0, 2.0 → `1.3333333333333333`); the judge text rendered by part 5
  `Gate._python()`.

### Acceptance

- The 9 rows pass. BA#1 passes before and after the change.
- The snapshot diff is only the two `Gate` lines; `test_gate_api.py` differs only at line 472.
- `git diff U4 --stat` on `packages` and `apps` lists only the files of the unit spec §9.
- Gates: `screamingface-engine`, `screamingface`, `repo` green, except the append-only check
  against `633fec3a1`, which lists only the pinned files of units 1–5; green with
  `--skip-append-only`.

### Deviations

- D-1 (BA-3 oracle): the PRD writes the fallback as `sf.Judge("prov/judge", returns="label")`,
  but `sf.Judge` requires `rubric=`. The test uses `rubric="Pick the best answer."` (the part 5
  `_FB_RUBRIC`), so the text is `sf.Gate('mean:risk', '<=', 3.0, otherwise=sf.Judge('prov/judge',
  returns='label', rubric='Pick the best answer.'), abstain_band=(2.5, 3.5))`. Erratum in
  overview §11 (commit C).
- D-2 (helpers): `_band`, `_band_pair` (S/gate.py) and `_rebuilt_band`, `_GATE_SPEC_KEYS`,
  `_BAND_KEY` (S/reducer.py) are private names the PRD does not give. They keep the ruff caps
  (max-branches 7, max-returns 3, mccabe 8).
- D-3 (rows): BA#3 adds one input beyond the PRD list, `(0.0, float("inf"))`. BA#6 is two
  functions: the hand edits (BA-E2) and the declared-name guard (BA-D3, with
  `signals={"conf": ...}` so its message does not depend on unit 2).
- D-4 (BA#8 oracle): the PRD gives the full gate record of run 1 only. Run 2's record is
  hand-derived (`observed 1.3333333333333333`, `passed True`, `branch "majority"`, the band
  kept, GB-I3). The test also checks the member signals, the declared map and the record key
  order (erd §4).
- D-5 (commit split): the snapshot and the line 472 edits are in commit A, because the stub
  already has the final signature.

### Outcome

- **Status:** GREEN. Every gate is green. The append-only check of the two gate stacks lists
  only pinned files of units 1 to 5 (overview §8). Those two stacks pass with
  `--skip-append-only`.
- **Actual files:**
  - SDK source: `S/gate.py` (field and keyword `abstain_band`, `_band`, `_band_pair`,
    `_BAND_PAIR`, `_BAND_FINITE`, `_spec`, `_render`, docstrings); `S/reducer.py`
    (`_GATE_SPEC_KEYS`, `_BAND_KEY`, `_rebuilt_band`, `_rebuilt_gate` key check and pass-through).
  - Data: `ET/data/combine_contract/gate_band_vote_candidate.url4` (new, written by
    `write_fixture`).
  - Commit A files, unchanged in this build: `ST/test_band_api.py`,
    `ST/test_sum_contract_fixtures.py`, `ET/test_combine_sum_run.py`,
    `ST/public_surface_snapshot.json`, `ST/test_gate_api.py:472`.
  - Test edits made in this build: none. No existing test file changed.
- **Commits:** A = `6f3430c76` (RED). B = the code commit of this unit. C = the docs commit of
  this unit (overview §11 erratum E1 for the unit 5 `rubric=` fix).
- **U4 (unit 4 tip):** `7b43b3bd3`.
- **RED log:** The RED tree of commit A was not run again in this build. The GREEN run is
  below. Before the fixture was written, `ST/test_band_api.py`, `ST/test_sum_contract_fixtures.py`
  and `ST/test_gate_api.py` gave 55 passed and 1 failed. The one failure was BA#7
  (`test_gate_band_fixture_matches_the_sdk_compile`), because the fixture file did not exist.
- **Gates (GREEN tree):**
  - Focused SDK run (`test_band_api.py`, `test_sum_contract_fixtures.py`, `test_gate_api.py`,
    `test_gate_contract_fixtures.py`, `test_public_surface.py`): 68 passed.
  - Focused SDK run (the ten files of spec §9): 216 passed.
  - Focused Engine run (`test_combine_sum_run.py`, `test_combine_gate_run.py`,
    `test_combine_band.py`, `test_combine_gate.py`): 65 passed.
  - `screamingface-engine`, base `633fec3a1`, with `--skip-append-only`: ruff check, ruff format,
    pyright, layering, pytest (cov 80%) green.
  - `screamingface`, base `633fec3a1`, with `--skip-append-only`: ruff check, ruff format,
    pyright, pytest (cov 95%), notebooks, build, distribution green.
  - `repo`, base `633fec3a1`: green, with the append-only check green.
- **Append-only offenders (base `633fec3a1`, both stacks red before the skip):**
  - Engine: `ET/data/combine_contract/evidence_cases.json`,
    `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
    `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`,
    `ET/test_combine_evidence_words.py`, `ET/test_combine_gate.py`,
    `ET/test_combine_gate_words.py`, `ET/test_combine_pick_output.py`.
  - SDK: `ST/data/schemas/screamingface.answer.v1.json`, `ST/public_surface_snapshot.json`,
    `ST/test_evidence_words.py`, `ST/test_frozen_record_fields.py`, `ST/test_gate_api.py`,
    `ST/test_gate_words.py`, `ST/test_pick_output.py`.
  - All of them are pinned in overview §8 for units 1 to 5. The `repo` stack append-only check
    was green.
- **Flakes:** none. No suite was rerun.
- **Deviations (build):** none. The constants of `S/reducer.py` sit above `_rebuilt_fallback`,
  as §2.3 of the unit spec says. The `_band` and `_band_pair` helpers sit after
  `_check_agreement`, as §2.1 says.

## Unit 6: show the sum and the band in the report (`sum-band-display`)

### Intent

PRD `sum-band-display`, rows SD#1–10 (ans:Q1 "recorded like any declared signal", ans:Q2
"recorded in the gate record"; P14). The Case pane and the run summary name a declared sum's
formula in its header title: `source: sum of 0.5 × sev_a + 0.3 × sev_b`; a malformed sum entry
shows `source: sum`. The gate chip shows ` · band [lo, hi]` when the record has a band, and the
band branch's verdict `in band · abstain`. The verdict, the observed reason and the run summary
counters read `branch`, not `passed` (the band branch has `passed` null). The run summary gate
line adds ` · in band {b} of {N}` when `b > 0`, before ` · not run`. The run summary mean takes the
exact `Fraction` mean when `math.fsum` overflows (the part 5 erratum E6 rule); a WHY comment names
`E/combine/gate.py` `_mean` as its twin. The export already holds the band and `in_band`; no
export, trace or schema change. Each case of list L37 keeps its bytes. Unit 5 tip: `018f035ae73c2284fc9d96d9b4bac6f30e6ab0d5`.

### Planned changes

- `S/_ui/combine_view.py`: import `Fraction`; `_gate_chip` (band text, reason by branch);
  new `_band_text`; `_gate_verdict` (by branch, `in band · abstain`); `_signal_head` and
  `_StepSummary.add` call the new `_source_text` (with `_term_text`); `_StepSummary.band`;
  `_add_gate` (by branch); `_gate_line` (` · in band`); `_mean_cell` (overflow fallback, WHY twin
  comment).
- New test file `ST/test_sum_band_display.py` (SD#1–10). It reads
  `COMBINE_CONTRACT / "evidence_cases.json"` under `requires_engine_app`, builds each Case by hand,
  and imports its builders from `ST/test_gate_display.py`.

### Pinned edits

None.

### Test plan

- 10 PRD rows in the PRD §7 order. CHAR: SD#1 (the 37 L37 cases; sha256 of section + summary,
  taken on the base SDK), SD#7 (the export; "none expected"), SD#8 (a malformed sum entry; today's
  text is already `source: sum`). RED: SD#2–6, SD#9, SD#10.
- No stub: the tests import no new name. RED: `7 failed, 11 passed`; each failure is an assertion,
  except SD#9 (`OverflowError`, the behavior the row adds).
- Every oracle is hand-written from sum-band-display §3, the AB-2 record and the SM-2 values.

### Acceptance

- The sum column and the `risk mean` header name the formula; the other declared names keep
  `source: verbalized`; a malformed sum entry shows `source: sum` and never raises.
- The band chip on the band, majority and not-run branches; the `in_band` result chip.
- The run summary counts the band Cases, in the order majority, fallback, in band, not run.
- `_mean_cell` gives the exact mean on overflow and today's text otherwise.
- The export holds the band and `in_band`.
- The 37 base cases keep their bytes; the part 5 display tests stay green unchanged.
- `screamingface --base <U5>` all green; `screamingface --base 633fec3a1` red only on the unit 1–5
  pinned files; `repo` green.

### Deviations

- D-1 (test design, SD#7): the PRD writes `operations[0]["combine"]`. The hand-built Case puts the
  three model operations first and the combine operation last (the `ST/test_gate_display.py`
  `_case` builder), so the test takes the one operation with a `combine` key, as part 5 GS#11 does.
  Same oracle values.
- D-2 (kind, SD#7, SD#8): CHAR, not RED. SD#7: unit 4 already exports the record (PRD "none
  expected"). SD#8: today's text is `str(entry["source"])`, which is already `source: sum`; the row
  guards that the new formatter falls back and never raises.
- D-3 (test design, SD#8): seven inputs beyond the PRD's two (text, empty map, bool, number as
  text, null, an int past the float range, one bad term among good ones), one per fallback branch
  of `_source_text` / `_term_text` (spec §8).
- D-4 (test design, SD#5, SD#9, SD#10): extra assertions on the same behavior. SD#5: a band on a
  gate that did not run (AB-D4) shows the band and the not-run dash. SD#9: `[-1e308, -1e308]`,
  `[1e308, 1e308, -1e308]` and `[]`. SD#10: an int coefficient shows as a float (`1.0`), and a name
  with `<` reaches the page escaped (PRD §4).
- D-5 (method, SD#1): the 37 digests were taken by the unit planner on commit `644e34b7b`, whose
  code tree equals the base `633fec3a1` (`git diff --stat 633fec3a1 644e34b7b -- packages apps` is
  empty); the 32 digests of the part 5 list L32 equal the `ST/test_gate_display.py` literals.

### Outcome (fill at the end — required before COMMIT)

- **Status:** GREEN. All focused tests, the neighbour run, the lint and the three gate runs pass.
  The append-only check of the `screamingface` stack and of the `repo` stack is run against
  `633fec3a1` (the part base). The `screamingface` stack has seven offenders, all pinned files of
  units 1 to 5 (overview §8). It passes with `--skip-append-only`.
- **Actual files:**
  - `S/_ui/combine_view.py`: the import `Fraction`; `_gate_chip` (band text, reason by branch);
    new `_band_text`; `_gate_verdict` (by branch, `in band · abstain`); `_signal_head` and
    `_StepSummary.add` call the new `_source_text` (with `_term_text`); `_StepSummary.band`;
    `_add_gate` (by branch); `_gate_line` (` · in band`); `_mean_cell` (overflow fallback with the
    WHY twin comment). Nothing else in the file changes.
  - Test file `ST/test_sum_band_display.py` (new, commit A). No edit in this commit.
  - Test edits made in this unit: none. No existing test file changed. No pinned edit.
- **Commits:** A = `9ed5fa50f` (RED; the `U5` tip is `018f035ae`). B = the code commit
  `feat(e4b): show the sum formula, the abstain band and the in-band count in the report` (this
  commit). C: none (overview §11: the README and CHANGELOG are unit 7).
- **Gates:**
  - Focused run (`ST/test_sum_band_display.py`): 18 passed.
  - Neighbour run (the twelve files of spec §11): 241 passed.
  - `ruff check`, `ruff format --check` and `pyright` on the touched files: green (0 errors).
  - `screamingface`, base `633fec3a1`: append-only check red on seven pinned files (below), then
    `--skip-append-only`: ALL GATES GREEN (ruff, format, pyright, pytest with cov 95%, notebooks,
    build, distribution).
  - `screamingface`, base `018f035ae` (`U5`): ALL GATES GREEN, append-only check included.
  - `repo`, base `633fec3a1`: ALL GATES GREEN, append-only check included (green).
- **Append-only offenders (`screamingface`, base `633fec3a1`):**
  - `tests/data/schemas/screamingface.answer.v1.json`
  - `tests/public_surface_snapshot.json`
  - `tests/test_evidence_words.py`
  - `tests/test_frozen_record_fields.py`
  - `tests/test_gate_api.py`
  - `tests/test_gate_words.py`
  - `tests/test_pick_output.py`
  - All seven are pinned files of units 1 to 5 (spec §11 list). None is a file of this unit.
- **RED log (commit A, before commit B):** `7 failed, 11 passed`. The failures are the seven
  expected rows: SD#2 (`test_sum_column_title_names_the_coefficients`), SD#3
  (`test_run_summary_mean_header_names_the_sum`), SD#4
  (`test_case_pane_shows_the_band_and_the_in_band_verdict`), SD#5
  (`test_case_pane_shows_a_band_on_the_majority_branch`), SD#6
  (`test_run_summary_counts_the_band`), SD#9 (`test_run_summary_mean_does_not_overflow`, an
  `OverflowError` from `math.fsum`) and SD#10 (`test_a_negative_coefficient_shows_as_written`).
  The passing rows are SD#1, SD#7 and the nine SD#8 parameters.
- **Flakes:** none. No suite was rerun.
- **Deviations (build):**
  - D-6 (process): commit A was made in an earlier run and was not made again here. Its tree holds
    the test file and the §12 ledger section, as spec §12 says. Its RED run was repeated in this
    build and gave the counts above.

## Unit 7: docs (README and CHANGELOG)

### Intent

Tell the SDK user how to sum declared signals and how the abstain band works (ans:Q1, ans:Q2):
`sf.Sum` is a declared derived signal of one member, its component and coefficient rules, the
missing rule, the exact arithmetic, every rule and gate that reads it by name, the vote weight rule
with its exact upper limit (spec review R6), the closed band on `sf.Gate` with the new reason
`in_band`, what it costs today (the fallback still runs), the scope (one member; `mean:<name>`
for the panel), and where the report shows both. Docs only: no code, no snapshot, no golden and
no url4 change.

### Planned changes

- `packages/screamingface/README.md` — R1: the new section `### Sum signals and the abstain band`
  between `### Fusion as a named recipe` and `## Install`, with one code block that assigns
  `s1_sum_pick` and `s2_band_gate`. R2: the paragraph `**Sums and the band.**` in
  `### Combine steps in the report`, after the `**The gate.**` paragraph.
- `packages/screamingface/CHANGELOG.md` — B1: one part 6 bullet at position 3 of the first
  `### Features` list of `## Unreleased`, after the part 4, part 3 and part 5 bullets.
- New `packages/screamingface/tests/test_sum_band_docs.py` — DC#1–DC#5. It imports `_section`
  from `test_evidence_completeness_docs`, four helpers from `test_show_signals_docs`, and
  `BUILDERS` from `test_sum_contract_fixtures`.

### Pinned edits

None.

### Test plan

- DC#1 CHAR (the seven anchor headings, once each, in order). DC#2 the new section, its place, the
  names in the code, the weight limit literal, and its rules (the missing, exact, reads, weight,
  cost, scope and report sentences verbatim). DC#3 the README code block compiles to the two url4
  fixtures and their builders byte for byte. DC#4 the `**Sums and the band.**` paragraph, its
  header, chip, result and summary examples, and the export key; no new heading between Browse and
  Accounting. DC#5 one part 6 bullet at position 3, with no counted token.
- Regression (CHAR, no edit): `test_gate_docs.py`, `test_show_signals_docs.py`,
  `test_evidence_completeness_docs.py`, `test_signal_recipes_readme.py`,
  `test_combine_recipes_readme.py`, `test_pick_output.py`, `test_mean.py`,
  `test_fusion_doc_goldens.py`, `test_gate_contract_fixtures.py`, `test_sum_contract_fixtures.py`,
  `test_sum_band_display.py`.

### Acceptance

- DC#1–DC#5 green; the regression tests green.
- README diff: 81 added, 0 removed lines; no added line over 100 bytes (the count stays 37).
  CHANGELOG diff: 2 added lines.
- `run_gates.py screamingface --base <unit 6 tip>`: all green, append-only included.
- `run_gates.py screamingface --base 633fec3a1`: append-only offenders are only SDK files of the
  unit 1–5 pinned lists; with `--skip-append-only` all green. `run_gates.py repo --base 633fec3a1`:
  green.

### Planned deviations

- DC#3 imports the `BUILDERS` dict (the name that sum-api §7 sets) instead of two builder functions
  by name (PRD docs §7 says "the two builders"); the function names are set by the unit 2 and 5
  specs. DC#3 also compares the fixture files, as part 5 DC#3 does.
- DC#1 also pins `### Gate the majority` and the order of all seven anchors.
- README planner additions (true for units 1–5, not in the PRD delta text): A1 the E4a key examples
  (`cost_usd`, `score:judge`) and "any other component raises `ValueError` before any call"
  (SA-E1–E3); A2 a negative coefficient is allowed and the Engine does not normalize (P4); A3 a sum
  too large for a float is missing (P5); A4 the weight sentence names the exact limit
  `7.022238808055921e+305` (the largest float divided by 256), says that `sf.Fusion` raises
  `ValueError`, and names `no_weight` (P13, N3, SA-E4, R6); A5 the band shape: finite, `lo <= hi`,
  a one-point band is valid, an agreement band from 0 to 1 (P7, BA-D2); A6 the band wins also over
  a judge or a writer (P9), and the record has `"passed": null` (P10); A7 the code comments (the
  member severity lines; what each branch does) and the placeholder routes; A8 R2 names the result
  chip `abstain · in_band` (SD-3), says the summary count shows only when a Case is in the band
  (P14), and names `[lo, hi]` and `"passed": null`.
- DC#2 also checks `hasattr(sf, "Sum")`, `in_band`, the `abstain_band` keyword and
  `repr(sys.float_info.max / 256)`; DC#4 also checks `` `abstain · in_band` ``; DC#5 also checks
  the README pointer and that bullet `[2]` is the part 5 bullet.

### Unit 7 outcome

- **Status:** Built. The README section, the README paragraph and the CHANGELOG bullet are in
  commit C. The docs tests of this unit pass. No code and no test file changed in this unit.
- **Unit 6 tip (base of the unit 7 append-only check):** `8c8297257`.
- **Commits:** A = `78732b606` (test(e4b): RED for E4b part 6 unit 7 docs); B = none; C = the commit
  `docs(e4b): README and CHANGELOG for sums and the abstain band (part 6)` that holds this outcome.
- **RED record (commit A):** `tests/test_sum_band_docs.py`: 1 passed, 4 failed. DC#1 passes; DC#2
  to DC#5 fail on the missing doc text, as the spec §6 table says.
- **Gates:**
  - Focused list of spec §9 step 4 (12 files): 122 passed. The README diff is 81 added and 0
    removed lines; the CHANGELOG diff is 2 added lines. The count of lines over 100 bytes stays
    37, and no added line ends with a space. `ruff format --check`, `ruff check` and `pyright` on
    the new test file are clean.
  - `screamingface --base 8c8297257` (unit 6 tip): ALL GATES GREEN, append-only check included.
  - `screamingface --base 633fec3a1`: the append-only check was the only red result. Its offenders
    are exactly the SDK files of the units 1 to 5 pinned lists: `tests/data/schemas/screamingface.answer.v1.json`,
    `tests/public_surface_snapshot.json`, `tests/test_evidence_words.py`,
    `tests/test_frozen_record_fields.py`, `tests/test_gate_api.py`, `tests/test_gate_words.py`,
    `tests/test_pick_output.py`. This unit changed none of them. With `--skip-append-only`:
    ALL GATES GREEN.
  - `repo --base 633fec3a1`: ALL GATES GREEN.
  - Flakes: none seen in this unit.
- **Deviations:**
  - The gate results are in a follow-up ledger commit, not in commit C. The gates run after
    commit C (spec §11), so their results are not known when commit C is made.
  - No other deviation from the spec text. The spec §10 planned deviations apply as written.
