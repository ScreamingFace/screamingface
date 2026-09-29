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

(filled during the loop)

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** (pending)
- **Commits:** (pending)
- **Gates:** (pending)
- **Deviations:** (pending)
