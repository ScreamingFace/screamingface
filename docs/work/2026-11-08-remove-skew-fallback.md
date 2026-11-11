---
ticket: OME-1832
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-08
finished:
---

# remove-skew-fallback — the Local Engine selects only by `effective` (OME-1138 close-out, L7b follow-up)

## Intent

L7b (OME-1830, #1684) kept a version-skew fallback for one Engine release: when no listed row
carries `effective` (a gateway older than L7a), the Local Engine selects the row labelled
`screamingface` and logs once per process that the gateway predates the field. This leaf removes
it, so the Engine selects only by `effective` and the label is never read for selection. A listing
whose rows lack the field breaks the listing contract and is a bad response (502), before any
write. Spec `docs/spec/2026-10-29-local-engine-effective-row.md` §3, §4; L7b ledger
`docs/work/2026-11-04-effective-row-engine.md` owner decisions 2 and 4; close-out spec
`docs/spec/2026-10-29-ome-1138-closeout.md` §8.

**Gate before PR-open** (owner decision 4): an Engine release that carries L7b has shipped. The
work is prepared in this worktree; the PR opens only after that release. It also waits for a
gateway release that carries L7a (owner, 2026-11-11): without the fallback the Engine needs a
gateway that lists the flag, and no gateway release did before `aigateway-v1.0.0`. Both shipped on
2026-11-11: `screamingface-engine-v2.0.0` contains L7b's `529bdb7f9`, and `aigateway-v1.0.0`
contains L7a's `6e998fa4d`.

## Planned changes

Engine paths under `apps/screamingface-engine/src/screamingface_engine/connections/`:

- `aigateway_rows.py`: `select` refuses a listing row without `effective`; the label rule, its
  `label_rule` thread, `_note_gateway_predates_effective` and the logger go; the comments on
  `MANAGED_LABEL` and `ConnectionRow.effective` drop the fallback.
- `aigateway.py`: the `WHY` in `_validate_row` keeps only the write response's absent flag.

Tests under `apps/screamingface-engine/tests/unit/`:

- No new test file: the deleted-file rule below keeps the new tests in the skew file.
- Prior tests that change (owner approval 2026-11-09, manifest at PR-open):
  - `test_connections_aigateway.py`: its rows carried no flag, so the label rule selected for them.
    `_row` gains `effective` (absent unless given, as on a write's response). Eight tests give
    their listed row `effective=True` and keep their behaviour; two are re-expressed with flags
    (`test_multiple_unmanaged_rows_leave_the_automatic_row_disconnected`: both rows not
    effective; `test_managed_row_is_selected_without_mutating_unmanaged_rows`: the labelled row
    effective, the other not). Three tests of the label rule itself retire
    (`test_connect_does_not_adopt_a_single_unmanaged_api_key_connection`,
    `test_multiple_managed_rows_are_a_conflict`,
    `test_disconnect_never_deletes_an_unmanaged_connection`); the effective suites hold their
    effective-rule counterparts.
  - `test_connections_aigateway_version_skew.py`: its fallback tests retire, and it takes the
    tests of the Engine against a gateway older than L7a as it is now: a listing without the flag
    is a bad response before any write, no notice is logged, and zero rows still list the
    gateway's status (owner, 2026-11-09). WHY not a deletion: the append-only check, which the
    pre-push hook also runs, rejects a deleted test file whatever a manifest says; a manifest
    pins a modified file only.
  - `test_profile_env_characterisation.py`: the three listing cases pin the label rule's 409 on
    rows without the flag; they retire with their fake, and the module docstring names where the
    ambiguity is held now (no effective row and two or more active ones: 409 before any write).

## Test plan

- A listing whose rows carry no `effective` is a bad response for `list`, `connect`,
  `start_oauth` and `disconnect`, with no write.
- A listing with zero rows still lists the gateway's status.
- No notice is logged for a listing without the field.
- The existing effective suites (`test_connections_aigateway_effective*.py`, the conditional
  repair suite) stay green unchanged.

## Acceptance

- Choosing the effective row never reads `MANAGED_LABEL` (close-out spec §8); repair planning
  (the stale rows and the label check) still does. No `label_rule` or
  `_note_gateway_predates_effective` remains in Engine src.
- `run_gates.py screamingface-engine` green.
- Every changed prior test is in `.claude/test-change-approvals/OME-1832.json` at PR-open.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `aigateway_rows.py` and `aigateway.py` in Engine src; the three
  approved prior test files above, `test_connections_aigateway_version_skew.py` now holding the
  14 tests of the refusal.
- **Commits:** on `OME-1832-remove-skew-fallback` from `origin/main` `6e73b4adb`:
  `refactor(screamingface-engine): select the Local Connection only by the effective flag`, then
  `docs(screamingface-engine): record the releases OME-1832 waited on` for this ledger and the
  mirror. Upstream since `6e73b4adb` touches none of these files. Not marked breaking (owner,
  2026-11-11); the PR body states that the Local Engine now needs AI Gateway 1.0.0 or later.
- **Gates (2026-11-11, the change on `origin/main` `d81e4d83a`, the `aigateway-v1.0.0`
  release):** `run_gates.py screamingface-engine` green: the
  append-only check (`OME-1832.json` admits the three approved files), ruff, ruff format, pyright,
  the layering check and the full suite with coverage.
- **Deviations:** the approval covered a third prior test file, `test_connections_aigateway.py`,
  found at GREEN. The skew file is modified rather than deleted, and the new tests moved into it
  (owner, 2026-11-09). `test_profile_env_characterisation.py` keeps only the worker fakes, which
  nothing imports; deleting it would hit the same deleted-file rule. The PR-open gate gained the
  gateway release that carries L7a (owner, 2026-11-11).
