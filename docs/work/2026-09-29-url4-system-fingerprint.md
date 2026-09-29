---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: url4
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-29
finished:
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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** (pending)
- **Commits:** (pending)
- **Gates:** (pending)
- **Deviations:** (pending)
