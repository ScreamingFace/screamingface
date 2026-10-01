---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: blocked   # planned | in_progress | done | blocked
started: 2026-09-30
finished: 2026-10-01
---

# e4a-combine-core — the combine framework core (registry, spec, evidence, endpoint)

## Intent

OME-1289 (E4a) unit 1. Add the core of the deterministic combine framework to the engine: an
immutable operator registry, the strict combine-spec parser, the evidence wire model, and the
`/ensemble/combine/v1` url4 endpoint that runs a spec over member outputs with pure functions and
records one `CombineEvidence` in the task-local operation-call recorder. No operator plugins ship
here (builtins is empty); the core is tested with fake operators. The layering gate gets a
COMBINE_CORE rule so the core never imports a plugin. The shared base (ports, failure codes, SDK
twin codes) is already committed in caaa882dd.

## Planned changes

- New: `combine/registry.py`, `spec.py`, `evidence.py`, `endpoint.py`, `builtins.py` (empty).
- Modify: `operation_calls.py` (`OperationCall.combine`, `record_combine_call`).
- Modify: `.claude/scripts/check_layering.py` (COMBINE_CORE rule).
- New tests: `combine_support.py` (fakes), `test_combine_ports.py`, `test_combine_registry.py`,
  `test_combine_spec.py`, `test_combine_failure_codes.py`, `test_combine_endpoint.py`,
  `test_combine_determinism.py`, `test_layering_combine.py`.
- Not touched: `ports.py` (base), `world/factory.py`, REST (unit 3), operators (unit 2).

## Test plan

U1-1 ports characterization (CHAR, green at once) · U1-2 FW-1 registry · U1-3 FW-2 spec ·
U1-4 FW-7 failure codes (green at once, the base did the GREEN) · U1-5 FW-4 · U1-6 EV-3/FW-H1 ·
U1-7 evidence fields · U1-8 FW-5 · U1-9 FW-6 · U1-10 args-before-context · U1-11 FW-8 ·
U1-12 FW-9 · U1-13 FW-10 · U1-14 built output · U1-15 invalid selection · U1-16 FW-11 ·
U1-17 FW-16 · U1-18 FW-17 · U1-19 presentation order · U1-20 no member text in messages ·
U1-21 `$` escape through url4 · U1-22 FW-3 hash-seed determinism · U1-23 FW-13 layering.

## Acceptance

- Engine, SDK and repo gates are green; the append-only check shows only the base's one approved
  edit to `test_failure_classes.py`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Added after planning: the median rule in `combine/spec.py` (the
  orchestrator's addition: a `median` reducer needs a `numeric` normalize step, any version).
- **Commits:** 7168b5351 test(engine): characterize the combine ports and pin the combine failure
  codes · 58dd266df feat(engine): add the immutable combine operator registry · a58b639f4
  feat(engine): add the combine spec parser, evidence model and endpoint · 4e7b41726 feat(layering):
  add the COMBINE_CORE rule to the layering gate · e028e8e97 docs(work): add the ledger · then the
  url4 refactor: 868998730 test(engine): allow world/combine.py to import the url4 engine · 5c4599a45
  docs(engine): a combine plugin imports only the ports and the standard library · a1ec4e8da
  refactor(engine): keep combine free of url4 and serve the route from world/combine.py.
- **Refactor (user decision, after the url4-import guard blocked `combine/endpoint.py`):**
  `combine/` imports no `url4` module. `combine/endpoint.py` keeps the route name, the caps, the
  failure order and the log line, and exposes the pure `run_combine(registry, params, context,
  intent) -> CombineOutcome`. The new `world/combine.py` owns `install_combine_runtime`, the
  `CombineRoute` handler, the `CombineError` -> `ResolutionError(permanent=True)` mapping and the
  task-local record. Core tests call `run_combine`; the url4 tests are in `test_world_combine.py`.
- **CHAR (green at once, by design):** `test_combine_ports.py` (U1-1) describes the committed
  `ports.py`; `test_combine_failure_codes.py` (U1-4) passes at once because the base already holds
  the codes. `test_a_plugin_importing_ports_passes`, `test_builtins_may_import_plugins`,
  `test_a_world_module_may_import_the_combine_core`, `test_the_gate_tolerates_a_tree_without_combine`
  and `test_combine_is_a_shared_leaf` also pass at once (they pin that the rule does not
  over-reach). All other tests were seen RED first on an assertion, against a skeleton. The
  hash-seed and 100-run tests were mutation-checked. The refactor moved existing (new-in-branch)
  tests; their assertions were kept, and `test_the_combine_core_imports_no_url4_module` was added.
- **Gates:** append-only vs 4eca379d1: exactly two offenders, both approved:
  `test_failure_classes.py` (the base) and `test_url4_executor.py` (one allow-list line for
  `world/combine.py`). `screamingface-engine --skip-append-only`: ALL GATES GREEN. `repo` and
  `screamingface` (SDK, append-only vs 4eca379d1 clean): ALL GATES GREEN.
- **Deviations:** U1-21 asserts the evidence tally value (`"$input"`), not the output text,
  because the select step copies a member text. The handler class is public (`CombineRoute`), not
  `_CombineRoute`, so tests can call it directly.
