---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 12 -- hardening: the shared evidence fixture, frozen schemas, Budget records, docs

## Intent

Fold the combine hardening branch (`e4a-combine-hardening`) into the gap-closure stack, as the LAST
unit. The branch is rebased onto `e4a-e2e-replay`. The old combine hardening work (replay operator
check, fixed-seed replay warning, evidence contract fixture) is replayed, then these rows land on
top: RT#2-3, BU#1-7, BU#9-10 (BU#8 was done in unit 4), the I-E5 shared evidence fixture, and the
final CHANGELOG and README pass. The CHANGELOG and README must describe the whole stack as built
(errata GE1-GE32 in `00-overview.md` section 9).

## Planned changes

- Commit B: regenerate the shared combine evidence fixture over 25 scenarios (I-E5).
- Commit C: freeze the combine spec and evidence wire schemas (RT#2).
- Commit D: `E/budget.py`, the budget.v1 records and the charge rule (BU#1-7, BU#10).
- Commit E: freeze budget.v1, pin its contract fixture (BU#9 engine).
- Commit F: `S/budget.py`, the SDK mirror (BU#1 SDK).
- Commit G: freeze the answer, report-trace and budget field sets (RT#3, BU#9 SDK, BU-D4).
- Commit H: CI path filter, only if a new engine path is read. SKIPPED (see Notes).
- Commit I: docs.
- Commit J: this ledger, closed.

## Test plan

Rebase. `git rebase --onto e4a-e2e-replay 28f2c1a31 e4a-combine-hardening` replayed 15 commits
(parent tip `becfda839`). Three stops, all in files the parent also edited:

| Stop | Commit | File | Resolution |
|---|---|---|---|
| 1 | `b2275dd8b` | `.github/workflows/screamingface-tests.yml` (both lists) | kept every parent line and comment; added this unit's comment and `combine/**`, `operation_outputs.py`, `contract.py` (`fixtures/combine/**` was already there) |
| 2 | `3a8d5c974` | `packages/screamingface/CHANGELOG.md` | kept the parent bullets (the parent already moved the reducer-slot bullet above the Rank bullet); dropped the old copy of the reducer-slot bullet; applied intent (1) in the parent's words: the bullet now names `Vote, Median, Judge, Pick, Merge, Rank, Concat` and `Filter` |
| 3 | `5a677a8fc` | the workflow again | kept the parent lines; added `definition.py` and `corrective_loop_candidate.url4`; used the commit's comment wording ("the SDK conformance and contract checks read") |

The other commits applied without a textual conflict. The pre-existing files that this branch
touches were diffed against the parent after the rebase: the workflow, CHANGELOG, README,
`_evaluation/{url4,runner}.py`, `url4.py`, `client.py` and `combine_evidence.py` hold only this
branch's hunks (the four CHANGELOG intents, the two README sentences, the `_Replay` code, the
`_warn_fixed_seed` extraction, `_combine_operator_pairs`, the two `load_operators=` arguments and
the two docstring rewordings). No stale hunk.

The parent then moved from `becfda839` to `82b9eee33` (3 review-fix commits, all under
`packages/screamingface/tests/e2e/`, no src change). `git rebase --onto e4a-e2e-replay becfda839
e4a-combine-hardening` replayed all 23 commits with no conflict (the three earlier resolutions were
reused). The diff of the pre-existing files against the parent is the same as after the first rebase.

Red set after the first rebase (observed; matches the expected set):

| # | Observed |
|---|---|
| R1 | engine `test_combine_evidence_contract_fixture.py`: the ten byte tests fail (old wire `member`/`voted`); `test_the_scenarios_cover_the_evidence_shapes` fails (`status == "empty"`). The envelope test stays green. |
| R2 | SDK `test_combine_evidence_contract.py`: ten decode tests fail (`missing 'dropped'`). |
| R3 | the replay tests (`test_url4_replay_operator_check.py`, `test_url4_replay_fixed_seed_warning.py`) are green. |

Rows (ET = `apps/screamingface-engine/tests/unit/`, ST = `packages/screamingface/tests/`):

| Commit | Row | Test (file) | RED |
|---|---|---|---|
| B | I-E5 | `test_the_scenarios_cover_the_evidence_shapes` and the byte tests (ET fixture test, 25 scenarios) | yes (the recorded red set, then the 15 new names missing from the fixture file) |
| B | 2 | `test_combine_evidence_contract.py`: the decode and round trip for 25 names | yes (27 failed before `write_fixture()`) |
| B | 3 | `test_the_sdk_local_fixture_is_the_engine_fixture` | guard, passes at once: the 7 SDK-local entries already equal the engine entries, so the copy rule was not needed |
| C | 4 | the five `check_frozen` meta tests (`test_wire_schema_freeze.py`) | yes (4 of 5 failed on the `pass` stub; the same-schema case passes with the stub) |
| C | 5 | `test_frozen_wire_schemas_match_snapshot_unless_id_changes` (spec, evidence) | yes (no file), then `UPDATE_SCHEMA_SNAPSHOT=1` |
| D | 6 | `test_budget_rejects_invalid_caps` (7 cases), `test_a_state_with_an_invalid_cap_is_rejected` | yes (no validators in the first version) |
| D | 7 | `test_usd_charges_decrement_remaining` | yes (stub `apply`) |
| D | 8 | `test_cache_hit_charges_original_cost` | yes (stub); the CHAR line (retained cost stays `"0"`) is inside it and passes at once |
| D | 9 | `test_token_budget_charges_in_plus_out` | yes |
| D | 10 | `test_unpriced_charge_counts_but_does_not_spend` | yes |
| D | 11 | `test_overrun_keeps_remaining_at_zero` | yes |
| D | 12 | `test_cached_replay_gives_same_charges` | yes |
| D | 13 | `test_charges_sum_exactly_in_decimal` (and the tamper case) | yes |
| D | 14 | the charge and refusal record rules | yes (no validators in the first version) |
| E | 15 | the `budget` case of the freeze test | yes (no file), then `UPDATE_SCHEMA_SNAPSHOT=1` |
| E | 16 | `test_budget_contract_fixture.py` (6 states) | yes (no file), then `write_fixture()` |
| F | 17-19 | `test_budget_records.py`, `test_budget_contract.py` | yes (35 failed against the stub records) |
| G | 20 | `test_sdk_records_match_frozen_field_sets` (answer, report-trace, budget) | yes (no `ANSWER_SCHEMA`, then no files), then `UPDATE_SCHEMA_SNAPSHOT=1` |
| G | 20 | the five `check_frozen` meta tests of `_schema_freeze.py` | yes (4 of 5 failed on the stub) |
| G | 21 | `test_fixture_answers_and_traces_use_the_frozen_fields` (25 Engine entries) | guard, passes at once |
| G | 22 | `test_budget_trace_kind_carries_every_budget_record_field` | guard, passes at once |
| H | - | none | skipped (no new engine path is read) |
| I | - | docs | no test |
| (after gates) | - | two replay tests that pinned "no catalog on a replay" | see D4 |

## Notes

Decisions F1-F14 come from the unit spec (`gap-unit12-hardening.md`). The ones that need a record:

- F1 three rebase stops, listed above. The replayed hunks of the four CHANGELOG intents are in the
  parent's words: (1) the reducer-slot bullet names the eight named classes (the parent already had
  `sf.Filter` and the rest; the old text listed seven), (2) the new bullet "check the operator
  catalog before a raw url4 replay spends" keeps the unpinned-name sentence, (3) the evidence bullet
  says it never holds the `output` copies and that `whole@1`/`json_object@1` put the whole reply in
  `raw`/`value`, (4) the `FixedSeedSittingWarning` bullet covers raw URL4 replays.
- F2 the engine fixture is regenerated over 25 scenarios (10 kept, unit 4's 6, 9 new). The JSON
  diff: every pre-existing entry moved to the Answer-row wire (`member_id`/`status` `answered|fail`,
  `result`, `dropped`, `signal`); 15 new entries. The SDK-local copy stays (installed runs have no
  Engine) and is guarded.
- F3 snapshots are written only by `UPDATE_SCHEMA_SNAPSHOT=1`. Each directory holds exactly its id
  files: Engine `combine-spec.v1`, `combine-evidence.v1`, `budget.v1`; SDK `answer.v1`,
  `report-trace.v1`, `budget.v1`. A rerun with `UPDATE_SCHEMA_SNAPSHOT=1` changes no byte.
- F4 (erratum GE27) `charge(signals, unit, *, cached)`: the caller passes the cache hit status.
- F5 a cached replay gives equal `amount` and `remaining_after`; `source` goes `live` to
  `cache_reference` (pinned by `test_cached_replay_gives_same_charges`).
- F6 every amount enters as `Decimal(repr(x))`; sums run in `DECIMAL_CONTEXT`.
- F7 `S/budget.py` is not exported from `sf` or `sf.report`; `public_surface_snapshot.json` has no
  diff against the parent. The record layering holds: `E/budget.py` imports pydantic, the stdlib,
  `combine.ports` and `operation_accounting`; `check_layering.py` is clean.
- F9 `ANSWER_SCHEMA` is added to `S/answer.py`, not in `__all__`.
- F14 unit 5's README paragraphs are not repeated. Added: SG-D13, the HealthBench abstain note,
  RE2, the report-trace and `report.v1` sentence.
- The follow-ups file `gap-sdk-followups-from-engine.md` has no item tagged 12 (its F12 is a unit
  10E finding, already built in units 9S and 10S).

Docs found stale and fixed in Commit I (the CHANGELOG and README now match the built behavior):

- the weights bullet said `score:judge` raises "until the judge arrives" (it needs a judge on the
  same vote, GE20);
- the `sf.Reduce` bullet said only three ops compile (all ten ops compile, `context` is the first
  half of the Fusion recipe);
- the README said an empty Filter, a Rank that cannot meet `k` and a Merge with no usable value
  FAIL with `combine_no_votes`. That code no longer exists: the combine step abstains with
  `no_votes` or `cut_not_met` (GE16, units 9E/10E);
- the README said a Filter that keeps no member marks the Case `abstained`. Only the final step of
  a Candidate can mark a Case (GE8), and a Filter is never final, so the evidence abstains and the
  Case is not marked. Corrected in the README and the CHANGELOG.
- added: GE29/GE30 (strict judge reply, `evidence.judge is None` for a judge-weighted vote), GE32
  (float thresholds), GE10 (`$` and the 5000-instruction limit), GE6/GE11 (abstained Case with a
  grader failure), SG-D13, HealthBench, the budget records, the frozen schemas.

Deviations from the spec:

- D1 `_ledger(cap, amounts)` takes the charge amounts, not the charges: `apply` needs the running
  remaining for the charge it is still building, and a `BudgetCharge` cannot exist before that
  number. `apply` and the state validator still share this one fold.
- D2 the spec's one cover test is two tests (`test_the_scenarios_cover_the_evidence_shapes` and
  `test_the_scenarios_pin_the_shape_facts`): one function over 26 statements breaks the engine lint
  (PLR0915). A GE30 pin (`vote_judge_weights.judge is None`) is added to the second.
- D3 the freeze test in the SDK runs the three field sets as three parameters, and the 25-name
  engine check is one loop, so `UPDATE_SCHEMA_SNAPSHOT=1` writes all three files in one run and a
  missing fixture fails (it never collects an empty set).
- D4 (unlisted files) two earlier-unit tests failed after the rebase because they pinned "a url4
  replay asks for no operator catalog", the exact behavior this unit's replay check adds on purpose:
  `ST/test_benchmark_extract_evaluation.py::test_resolved_url4_replays_without_benchmark_lookup`
  and `ST/test_signal_vote_replay.py::test_signal_reduce_replays_identically_from_cache`. Both
  keep their intent (no benchmark lookup; the replay is byte identical) and now allow exactly one
  `/v1/operators` GET. This is a change to prior tests, so the append-only gate lists both files
  as offenders (reported in the final message); `--skip-append-only` is used for the green run.
- D5 Commit H is skipped: `combine_contract/**` already covers `budget_cases.json` and `schemas/`.
  The commit `test(sdk): let a url4 replay read the operator catalog once` is the D4 fix.

Gates (`--base e4a-e2e-replay`; the parent tip is `82b9eee33`):

- screamingface-engine, without `--skip-append-only`: green (no offender).
- screamingface, without `--skip-append-only`: red on the append-only check only. Offenders: the two
  files of D4.
- screamingface, with `--skip-append-only`: ruff, format, pyright, pytest (coverage above 95%; 97.08% on the full run), notebooks,
  build and distribution all green.
- screamingface-engine with `--skip-append-only` and `repo`: green (see the final message).
