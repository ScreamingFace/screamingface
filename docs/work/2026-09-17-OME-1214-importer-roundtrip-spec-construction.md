---
ticket: OME-1214
stack: screamingface-engine
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1214 — A board-spec change can break the importer without any test failing

## Intent

The importer emits SnapshotSpec/BoardSpec rows as template strings; today's tests only
`ast.parse` those fragments (and exec pins.py constants), so a rename or new required
field on either dataclass keeps the suite green and breaks at the next import session.
Add round-trip tests that exec the emitted rows with the REAL dataclasses in the
namespace — a spec change then fails in its own PR. Test-only; zero importer runtime
changes.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_inspect_importer.py` — append two tests:
  - snapshot fragment (prepare.py row): `generate_rows` into the copied package with a
    maximal fact set (prompt_template + choice_template + shuffle_seed), exec the copy's
    pins.py, then exec the emitted snapshot fragment with the real `SnapshotSpec` —
    assert it constructs and carries the facts.
  - board fragment (boards.py row): exec the emitted board fragment with the real
    `BoardSpec` — assert it constructs, key/scorer/scorer_kwargs/with_check_surface land.
- pins.py fragment is already exec'd by `test_generated_snapshot_row_resolves_against_the_real_spec` (unchanged — append-only).
- The ticket's optional in-importer `dataclasses.fields` guard is SKIPPED: importer
  importing prepare/boards would create a heavy import edge (boards pulls
  url4.peer.server), and the exec tests already pin the contract. Noted as deviation.

## Test plan

- New tests fail when a required field of `SnapshotSpec`/`BoardSpec` is removed or
  renamed (verified by a local probe: temporarily delete a field, run, restore).
- Invariant named in each docstring: an emitted row must construct the real spec, so a
  spec change breaks here, not at the next import session.
- All existing importer tests stay green and unmodified.

## Acceptance

- One construction test per fragment file (pins covered by existing exec test).
- Local probe (remove a required field) makes at least one importer test fail.
- Gates green (`run_gates.py screamingface-engine`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `apps/screamingface-engine/tests/unit/test_inspect_importer.py`
  (+2 tests, append-only) plus this ledger and the `docs/tasks/` mirror.
- **Commits:** 444de4de — test(engine): emitted importer rows must construct the real specs
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only check, ruff check,
  ruff format, pyright, layering, pytest cov≥80). Importer suite: 40 passed (38 prior + 2 new).
  Probes: renaming `SnapshotSpec.case_count` fails the snapshot test; renaming
  `BoardSpec.scorer` fails the board test; both restored.
- **Review round 1 (confirmed finding):** only the maximal shapes were constructed — a
  minimal snapshot row (no prompt/choice template, no shuffle_seed) and an MCQ board row
  (no scorer_kwargs, no with_check_surface) stayed ast.parse-only, so dropping an optional
  field's default survived the suite. Added one minimal-facts construction variant per
  fragment (42 tests now). Probe: making `shuffle_seed` required fails the construction
  tests (and the real catalogue import — louder still).
- **Deviations:** the ticket's optional in-importer `dataclasses.fields` guard skipped —
  importer would need to import prepare/boards (boards pulls `url4.peer.server`), a heavy
  import edge for a check the exec tests already pin. Flagged in the PR for review.
