---
ticket: OME-1437   # E14 leaf under epic OME-1307 (filed at PR-open, 2026-09-30)
stack: url4
status: done   # planned | in_progress | done | blocked
started: 2026-09-29
finished: 2026-09-29
---

# url4-system-fingerprint — the pure `system_fingerprint` in `packages/url4` (E14, OME-1307, unit URL4-fp)

## Intent

Wave 1 of epic E14 (reproducible submissions). The scoreboard needs one stable identity for
a "system" (the Candidate, without the benchmark). This unit adds the pure function
`url4.fingerprint.system_fingerprint(linked, binding="candidate", *, exclude_bindings=frozenset())`
and `canonical_system_url4`. The value is the sha256 of the canonical text of the Candidate after
the caller's metadata bindings are removed from the Candidate root (decision D3). The unit also
freezes 50 golden vectors that the scoreboard half of SR-5 reads later. The plan is
`docs/plan/2026-09-29-e14-reproducible-submission/URL4-fp.md` (approved; it is the full spec).
Delivery model D1: commit on `unit/URL4-fp` only. No PR, no Linear issue, no push.

## Planned changes

- create `packages/url4/src/url4/fingerprint.py`
- create `packages/url4/tests/unit/test_fingerprint.py`
- create `packages/url4/tests/unit/test_fingerprint_properties.py`
- create `packages/url4/tests/unit/test_fingerprint_parity.py`
- create `packages/url4/tests/unit/test_fingerprint_purity.py`
- create `packages/url4/tests/fixtures/fingerprint_vectors.json`
- change `packages/url4/pyproject.toml` and `packages/url4/uv.lock` (add `hypothesis` to dev group)
- change `apps/screamingface-engine/uv.lock` (lock only, D7 X-25)
- change `packages/url4/ARCHITECTURE.md` and `packages/url4/README.md`
- no migration (`packages/url4` has no database; stack rule S1 does not apply)

## Test plan

- SR-2 property (Hypothesis): equal fingerprint for normalizable spellings.
- SR-3 guard: no seed parameter in the signature; seed has no channel into the value.
- SR-4: one Candidate on two benchmarks gives one fingerprint.
- SR-5 (url4 half): 50 golden vectors; fixture guards (oracle, twin) plus the parity test.
- SR-H3 precondition: two recipe display names give one fingerprint with `exclude_bindings`.
- C11 purity tests: imports (AST), no bare I/O calls, no SDK name, subprocess import probe.
- Supporting tests for each edge case of plan section 7.

## Acceptance

- All owned tests green with RED evidence (or guard note) below.
- `fingerprint_vectors.json` has 50 entries, `exclude_bindings == ["_sf_recipe"]`.
- All gates green; url4 coverage >= 95 %; `fingerprint.py` 100 % line coverage.
- Diff against `e14-reproducible-submission-spec` shows only the plan files and this ledger.

## RED / GREEN evidence

**Resume note.** An earlier implementer run stopped part-way. It left the final `fingerprint.py`,
the four test files, the vectors file, and the README and ARCHITECTURE edits uncommitted. It did
not record any RED result in this ledger, so no RED step counts as "observed before the stop".
This run re-verified every RED and GREEN step. Method: the final `fingerprint.py` was saved
outside the repo, then the T1 stub, the T2 GREEN code and the T3 GREEN code were put in its place
one after the other, and the four test files (unchanged) ran on each. The final file was then
restored (78 passed). The vectors file was also re-made with the plan T5 script (scratch file,
not committed): the output is byte-identical to the file in the tree.

- **T0 (no test).** `packages/url4/pyproject.toml` has `hypothesis>=6.168.3` in the dev group
  (commit b597027a). The only change in `apps/screamingface-engine/uv.lock` is that one
  `hypothesis` line in the `url4` `requires-dev` block. `uv lock --check` exits 0 in both
  directories. No other package version moved.
- **T1 stub, re-verified.** 68 failed, 10 passed. All 68 failures are `NotImplementedError`
  (no import error, no `TypeError`). The 10 passes are the guards: 3 vector-file guards
  (`test_vectors_file_has_fifty_unique_entries`, `test_vectors_match_their_independent_oracle`,
  `test_vectors_hold_the_sr_h3_twin`), `test_strategy_canonical_form_is_canonical`, and the 6
  purity tests (they read the module source and do not call the stub). The two
  `pytest.raises(Url4Error)` tests fail too, because `NotImplementedError` is not a `Url4Error`.
  The vector-file guards and the strategy guard pass on the stub by design: they do not call the
  code under test.
- **T2 GREEN, re-verified** (`_binding_text`; the embedded text returned as it is; no exclude).
  All T2a and T2b tests are green. In the parity file, 40 vectors are green and the 10 vectors
  `c08-*` and `c09-*` are RED (the recipe blob is still in the hashed text). At this stage the
  T3 and T4 tests already exist in the tree, so 5 more tests are RED for their stated reason:
  `test_fingerprint_unparseable_embedded_candidate_raises_url4_error` (`DID NOT RAISE Url4Error`),
  `test_fingerprint_equal_for_normalizable_spellings` (`sha256(variant_text)` is not
  `sha256(canonical_text)`), and the three T4 tests (`sr_h3`, `direct_run`, `empty_group`).
  Total 15 failed, 63 passed.
- **T3 GREEN, re-verified** (`build(embedded)` then `render`). The embedded-unparseable test and
  the SR-2 property (200 examples, derandomized) are green. Left RED: the three T4 tests and the
  same 10 parity vectors (13 failed, 65 passed). The `empty_group` test fails on
  `"(_sf_recipe:0.0:'x')!'y'" == "()!'y'"`.
- **T4 GREEN = the final module** (`_without_bindings` added). 78 passed, including all 50 parity
  cases. The nested and linked-root cases of the root-level test pass at every stage (they guard
  against a walk that goes too far).
- **T5 vectors.** Command: the plan section 6 T5 script, run once with `uv run python` from
  `packages/url4` as a scratch file outside the repo, output written with
  `json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"`. 50 entries,
  `exclude_bindings == ["_sf_recipe"]`, 9 unique fingerprints (c08 and c09 share one).
- **T6 (SR-3) is a guard.** The signature assert fails the moment a seed parameter is added.
  No seed-strip behavior was invented to make a RED.
- **T7 (C11 purity) are guards.** They pass on correct code by design. The two teeth tests
  (`test_the_import_scan_sees_a_forbidden_import`, `test_the_call_scan_sees_open`) prove that the
  scans can fail.
- **Ordering note.** The GREEN code and the tests were written by the earlier run before the
  ledger held any evidence. The stage-by-stage re-verification above is the evidence for the
  TDD order. It is not a claim that the earlier run observed each RED.

## Outcome

- **Actual files:** as planned, no extra file. `packages/url4/src/url4/fingerprint.py`;
  `packages/url4/tests/unit/test_fingerprint.py`, `test_fingerprint_properties.py`,
  `test_fingerprint_parity.py`, `test_fingerprint_purity.py`;
  `packages/url4/tests/fixtures/fingerprint_vectors.json`; `packages/url4/pyproject.toml`,
  `packages/url4/uv.lock`, `apps/screamingface-engine/uv.lock` (one line);
  `packages/url4/ARCHITECTURE.md`, `packages/url4/README.md`; this ledger.
  No migration (no database).
- **Commits (on `unit/URL4-fp`):** d1d531d9 `docs(url4): start the E14 system fingerprint ledger`;
  b597027a `build(url4): add hypothesis to the dev group`;
  91128cb1 `feat(url4): add the pure system_fingerprint for the E14 system registry`;
  and the docs commit that fills this outcome.
- **Gates (all green):** `run_gates.py url4 --base e14-reproducible-submission-spec` (append-only,
  ruff check, ruff format, pyright, pytest cov >= 95: 98 % total, `fingerprint.py` 100 %; 1437
  passed); `uv lock --check` in `packages/url4` and `apps/screamingface-engine`;
  `check_suppressions.py` (7, baseline 7); `check_module_size.py`; the four fingerprint test
  files (78 passed); `run_gates.py screamingface-engine` and `run_gates.py screamingface` (both
  ALL GATES GREEN). Note: the first `screamingface` run failed in pyright, only with
  `reportMissingImports` for `ipywidgets`, because the local venv lacked the `notebook` extra
  (CI runs `uv sync --extra notebook`). After `uv sync --extra notebook` in
  `packages/screamingface` (venv only, no tracked file) the lane is green. It is an environment
  matter, not a change in a gate.
- **Wisdom review:** no simpler design (two public functions, two helpers, as in the plan). No
  speculative generality. The tests use a `hashlib` oracle over literals, so no expected value
  comes from the code under test. Blast radius: one new module; `__init__.py`, `test_layering.py`
  and the module-size baseline are untouched; no prior test was changed (append-only gate green).
  No secret, no I/O, no fail-open path. No `# type: ignore`, no bare `except`.
  `packages/url4/.hypothesis/` appeared during test runs; it was deleted and not committed.
- **Deviations:**
  - tortoise-dev waived by the user for E14 (no Tortoise code in this unit).
  - A previous implementer run stopped part-way and left uncommitted work. This run kept it,
    checked it against the plan, and re-verified each RED and GREEN step by stage (see the
    evidence section). No RED was recorded before the stop.
  - The plan lists no fixed intermediate-stage code for the re-verification; the T1/T2/T3
    stage files were made in the scratchpad outside the repo and are not committed.

## Follow-up 1 — review finding F1 (blocking): `exclude_bindings` must strip only inert sources

Status: DONE (2026-09-29).

### Intent

The design review found that `_without_bindings` removes any root source whose name is in
`exclude_bindings`, whatever its value, weight or use. A client can name a working member
`_sf_recipe`. The member then leaves the identity, and two systems that behave differently get
one fingerprint. The scoreboard takes client text, so this is reachable. This follow-up narrows
the strip. A matching source is removed only when it is provably inert. Otherwise
`canonical_system_url4` and `system_fingerprint` raise a `Url4Error` subclass.

Inert means all of these are true:

1. the node is a `Source` (not a `Binding`);
2. its value is `Text`;
3. its weight is the scalar `0.0` (the rule of `url4.dag._lowering._is_instrumental_weight`,
   restated here because `url4.fingerprint` may import `url4.core` only, C11);
4. no `$name` reference to any excluded name remains in the system after the strip. The scan is a
   regex over the rendered remainder. It mirrors `_ENV_VAR_RE` of `url4.dag.semantics.ensemble`
   (`$$` is an escape; `$name` takes the longest identifier, so `$_sf_recipe_input` is not a
   reference to `_sf_recipe`).

### Planned changes

- change `packages/url4/src/url4/fingerprint.py` (the strip; a new `ExcludedBindingError`, a
  `Url4Error` subclass defined in this module, code `malformed_source`, permanent)
- append tests to `packages/url4/tests/unit/test_fingerprint.py` (append-only)
- this ledger
- no change to `errors.py`, `__init__.py`, the vectors file (must stay green), the spec or the plans

### Test plan (RED first)

- referenced `_sf_recipe` pair from the finding: raises, not one fingerprint (both functions);
- `_sf_recipe:1.0:/route(...)`: raises;
- non-Text value (`RelExpr`, `VarRef`, `Url`): raises;
- reference forms: `$_sf_recipe` in a sibling context, in the intent, with a field path: raises;
- not a reference: `$_sf_recipe_input`, `$$_sf_recipe`: the source is still stripped;
- the error is a `Url4Error` with a stable code; A8/A9 twin and the 50 vectors stay green.

### RED / GREEN evidence

- **RED.** A stub `ExcludedBindingError` (no behavior) went in first, so the file imported. The
  new tests then ran on the unchanged strip: 12 failed, 19 passed. All 12 failures are
  `DID NOT RAISE` (the reproduced finding, 6 non-inert forms, 4 reference forms, and the
  error-shape test). The two "not a reference" tests (`$_sf_recipe_input`, `$$_sf_recipe`) pass on
  the old code by design: they guard against a scan that is too wide.
- **GREEN.** The strip now checks inertness and scans the rendered remainder. The four
  fingerprint test files: 91 passed, then the purity allow-list edit (see Deviations) gave 92
  passed. The A8/A9 twin and the 50 parity vectors stay green with no change to the vectors file.

### Outcome

- **Files:** `packages/url4/src/url4/fingerprint.py`, `packages/url4/tests/unit/test_fingerprint.py`
  (append only), `packages/url4/tests/unit/test_fingerprint_purity.py` (allow-list),
  `packages/url4/README.md` (the rule), this ledger.
- **Gates (green):** `run_gates.py url4 --base e14-reproducible-submission-spec` (append-only,
  ruff check, ruff format, pyright, pytest cov >= 95: 1451 passed, 98 % total, `fingerprint.py`
  100 %); `uv lock --check`; `check_suppressions.py` (7, baseline 7); `check_module_size.py`.
- **Deviations:**
  - `test_fingerprint_purity.py` `_ALLOWED_IMPORTS` gained `re` (standard library) and
    `url4.core.errors` (core). The fix needs both. The rule of the test (core and standard
    library only) is unchanged. This is the one edit to a prior test. The append-only gate is
    green. It needs the reviewer to confirm.
  - **Pending approval:** this narrows the D3 / ERD 2.3.2 wording ("match on Source.name only,
    any value type"). The spec and the plans are in `e14-reproducible-submission-spec`, outside
    this branch, so they are not changed here. The integrator must record the amendment:
    D3/ERD 2.3.2 (strip only inert sources; else `ExcludedBindingError`, a `Url4Error`, code
    `malformed_source`, so the scoreboard maps it to 422 `invalid_url4`) and SB-registry (document
    the same rule, because `candidate_url4` is stored after the strip).
  - The error class is defined in `url4.fingerprint`, not in `url4/core/errors.py` (not a listed
    file); it reuses the `malformed_source` code.
  - Residual risk, not fixed (outside the finding): a positional `$N` reference counts slots of
    the whole group, so removing an inert source that comes before a referenced slot shifts `$N`.
    The scan does not treat `$N` as a reference to the removed name.
