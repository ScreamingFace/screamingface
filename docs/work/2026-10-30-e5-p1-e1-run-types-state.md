---
ticket: OME-1797
stack: screamingface-engine
status: done
started: 2026-10-30
finished: 2026-10-30
---

# e5-p1-e1-run-types-state — E1: layering rule, Run types and state

## Intent

First PR of the E5 P1 Engine stack (`docs/plan/2026-10-30-e5-p1-first-class-run.md`, E1; spec
`docs/spec/2026-10-27-e5-p1-first-class-run.md`), under `OME-1785`. It adds the layering rule
that keeps every database write in the App (spec D3, §9), the Run domain types, the pure state
function (R5) and the `run_` id (D5). Nothing is wired; there is no dependency change.

## Planned changes

- `.claude/scripts/check_layering.py`: `runs` and `adapters.run_registry_tortoise` (the Run
  registry) join the control plane; the worker may not import them; only the registry imports
  the database stack (`tortoise`, `asyncpg`, `aiosqlite`), exempt modules included. A design
  guard against accidental drift, not a security boundary (spec §9).
- `apps/screamingface-engine/src/screamingface_engine/runs/__init__.py` (new)
- `.../runs/model.py` (new): Candidate and Run states, `OwnerKey` and `owner_key`, `RunSpec`,
  `CandidateRecord`, `RunRecord`, `RunQuery`, `RunPage`, `is_aware`.
- `.../runs/state.py` (new): R5 `derive_state`.
- `.../runs/ids.py` (new): `new_run_id` (`run_` + a random UUID in hex) and the anchored
  `RUN_ID_PATTERN`.
- Tests (new): `tests/unit/test_layering_run_registry.py`, `tests/unit/test_run_state.py`,
  `tests/unit/test_run_ids.py`, `tests/unit/test_run_model.py`.
- this ledger, and the `docs/tasks` mirror

## Test plan

- Layering, on a synthetic tree: worker, runner and shared-leaf imports of the registry fail;
  the database stack imported outside the registry fails, `local.py` included; the App and the
  registry may use what they own; the registry adapter may be a package; the real tree is clean.
- State: every R5 row in order on an injected clock, overlaps, both sides of the grace, and
  refusals (no Candidates, an unknown state, a naive datetime, a non-positive grace).
- Ids: the form, distinctness, and an anchored `RUN_ID_PATTERN`.
- Model: `owner_key` trims, NFC-normalises and case-folds; `RunSpec` keeps the domain rules (at
  least one Candidate, no blank or duplicate names after stripping, no blank text, no negative
  `case_count`) and stores what it validated; `RunQuery` bounds `limit` and checks `state`, an
  aware `since` and `cursor`; the terminal helpers match the spec and refuse unknown states.
  Request types are the route schemas' to check (E8).

## Acceptance

- All new tests pass; every prior test stays green and unedited; `run_gates.py
  screamingface-engine` green.

## Outcome

- **Actual files:** as planned.
- **Commits:** one, `feat(engine): add the Run types, state rule and the database-writes layering rule`.
- **Gates:** `run_gates.py screamingface-engine` and `run_gates.py repo` all green. 81 new
  tests; `runs/` at 100% line coverage. No prior test edited.
- **Deviations:** none. Left to later units on purpose: size limits on `RunSpec` follow the
  database columns (E2); request types are checked by the route schemas (E8).
