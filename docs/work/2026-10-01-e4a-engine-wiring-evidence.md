---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# e4a-engine-wiring-evidence — wire combine into the world, the envelope and the catalog

## Intent

OME-1289 (E4a) unit 3. Units 1 and 2 built the combine core and the 15 built-in operators. This
unit connects them to the rest of the engine. The world factory installs the combine route for
every world that runs benchmarks. The Candidate envelope carries the combine evidence per
operation (`OperationOutput.combine`, left out when null). Attribution also reads `judge_N` and
`writer_N` bindings. `GET /v1/operators` lists the registry. A fixture test keeps the binding
pattern equal to the SDK pattern.

## Planned changes

- Modify: `world/factory.py` (install the combine route after the corrective runtime).
- Modify: `benchmarks/contract.py` (`OperationOutput.combine`).
- Modify: `benchmarks/operation_outputs.py` (`_BINDING` widened; copy `combine` for one claimant).
- New: `rest/operators.py`; modify `rest/__init__.py` and `app.py` (router, DI, `app.state.operators`).
- New tests: `test_combine_evidence_wire.py`, `test_combine_wiring.py`, `test_rest_operators.py`,
  `test_binding_names_fixture.py`.
- Not touched: `encode_candidate_invocation` encoding (no `sort_keys`), `ports.py`, existing tests.

## Test plan

EV-1 CHAR envelope bytes (before any delta) · EV-2 CHAR ambiguous fingerprint · EV-5 omit and
round trip · EV-4 attribution copy · ambiguous and last-call tests · EV-9 judge/writer bindings ·
binding-names fixture · end-to-end candidate invocation · FW-12 build_world install · FW-14 catalog
with ETag and 304 · FW-15 catalog ids equal resolvable ids.

## Acceptance

- All tests above pass; CHAR tests pass at once by design.
- Engine gate green; with append-only on, only the two approved offenders appear.
- `screamingface` (SDK) and `repo` gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `app.py` helper `_install_catalogs` (see Deviations). New
  tests: `test_combine_evidence_wire.py`, `test_combine_wiring.py`, `test_rest_operators.py`,
  `test_binding_names_fixture.py`.
- **Commits:** c4dbbb28d feat(engine): carry combine evidence on the operation output and attribute
  judge and writer bindings; 4298f50d5 feat(engine): install the combine route for every benchmark
  world; efda523d4 feat(engine): serve the combine operator catalog at GET /v1/operators.
- **TDD notes:** EV-1 (both envelope and CaseResult), EV-2 and `test_operation_output_omits_combine_when_null`
  pass before any delta (CHAR, by design; the omit test passes trivially before the field exists).
  RED seen for the right reason (assertion or missing attribute, not ImportError): EV-5 round trip,
  EV-4, ambiguous and last-call tests, EV-9, the binding-names fixture tests, FW-12 (route not in
  `processor_routes()`), FW-14/FW-15 (404 body, no `data`; the `operators` DI seam was added first).
  The end-to-end test passes at once after EV-4 and EV-9 (spec order); it fails when the
  `combine=combine` copy in `_attributed` is reverted (checked by hand).
- **Gates:** `run_gates.py screamingface-engine --base 4eca379d1`: only the two approved append-only
  offenders (`test_failure_classes.py`, `test_url4_executor.py`). With `--skip-append-only`: ALL GATES
  GREEN (ruff, format, pyright, check_layering, pytest with the 80 percent coverage floor).
  `screamingface`: ALL GATES GREEN. `repo`: ALL GATES GREEN.
- **Deviations:** `create_app` was at the 26-statement limit (PLR0915). The new
  `app.state.operators = operators` line made it 27. The two catalog assignments moved into a small
  helper `_install_catalogs(app, benchmarks, operators)`. Behavior is the same.

## Review round 1 (coordinator: ACCEPT-WITH-FIXES)

The branch was rebased onto the review-fixed units 1 and 2 (my commits became c6d85376e..60e77dec8);
the full engine suite was green there (4787 passed) before this round.

- Items 1: the "one registry" INVARIANT comment in `rest/operators.py` and `test_rest_operators.py`
  now says the App parameter is a test-only seam and both sides default to `BUILTIN_OPERATORS`.
- Item 2: `test_factory_installs_the_registry_the_default_app_serves` spies on
  `world.factory.install_combine_runtime` and asserts the registry `is` the default App's
  `app.state.operators` and `is BUILTIN_OPERATORS`. It passes at once (a pin; the factory already did this).
- Item 3: the tautological fake-registry test is deleted (the FW-14 test keeps the literal body).
- Item 4: `operation_outputs.py` docstring states the stricter combine-evidence rule.
- Item 5: `conditional_json_response` now lives in `rest/conditional.py` and both `rest/benchmarks.py`
  and `rest/operators.py` use it. The existing benchmark REST tests pass unchanged.
- Item 6: `test_judge_and_writer_model_routes_are_attributed_their_own_output_and_accounting`.
- Item 7: `_install_catalogs` renamed `_install_discovery_registries`;
  `test_graded_row_without_reducer_is_byte_identical` pins `graded_results.encode_result`.
- Gates: append-only run shows only `test_failure_classes.py` and `test_url4_executor.py`;
  `--skip-append-only`, `screamingface` and `repo` are green.
