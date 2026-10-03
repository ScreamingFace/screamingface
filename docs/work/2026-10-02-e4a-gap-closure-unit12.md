---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
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
- Commit H: CI path filter, only if a new engine path is read.
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

Red set after the rebase (observed; matches the expected set):

| # | Observed |
|---|---|
| R1 | engine `test_combine_evidence_contract_fixture.py`: the ten byte tests fail (old wire `member`/`voted`); `test_the_scenarios_cover_the_evidence_shapes` fails (`status == "empty"`). The envelope test stays green. |
| R2 | SDK `test_combine_evidence_contract.py`: ten decode tests fail (`missing 'dropped'`). |
| R3 | the replay tests (`test_url4_replay_operator_check.py`, `test_url4_replay_fixed_seed_warning.py`) are green. |

## Notes

(filled in Commit J)
