---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# e4a-combine-hardening — close four cross-unit gaps found by the whole-stack review (OME-1289 unit 12)

## Intent

The whole-stack review of E4a found four gaps between units. A raw url4 replay never loads the
operator catalog, so a reducer url4 that pins an operator the Engine lacks pays every member call
and then fails (H1). The SDK evidence decoder and its tests use hand copies of the Engine's
evidence, so the two can drift (H2). The SDK workflow does not run when the Engine files its
conformance checks read change (H3). The changelog still says the release ships no concrete
reducer (H4). This unit closes all four with new tests and small source edits.

## Planned changes

- H1: `packages/screamingface/src/screamingface/_evaluation/url4.py` (check the combine calls'
  pinned operators against the client catalog before the run), `.../client.py` (pass the existing
  catalog `load` into the replay path, sync and async); new test
  `packages/screamingface/tests/test_url4_replay_operator_check.py`.
- H2: new engine test `apps/screamingface-engine/tests/unit/test_combine_evidence_contract_fixture.py`,
  new fixture `apps/screamingface-engine/tests/unit/data/combine_contract/evidence_cases.json`
  (written by the engine test helper `write_fixture()`); new SDK test
  `packages/screamingface/tests/test_combine_evidence_contract.py`.
- H3: `.github/workflows/screamingface-tests.yml` path lists (push and pull_request).
- H4: `packages/screamingface/CHANGELOG.md`.

## Test plan

- H1 (RED first; final list in the Outcome): reducer url4 pinning `mode@9` -> ValueError before the run transport; engine 404
  on `/v1/operators` -> EngineCapabilityError before the run transport; plain url4 -> zero
  `/v1/operators` requests; valid reducer url4 -> one catalog request, then runs; async twins for
  the first two.
- H2: the engine test builds ten scenarios with the pure core and pins their canonical evidence
  JSON to the fixture (missing file FAILS). The SDK test decodes every entry and checks `to_dict()`
  round-trips. The fixture is a contract fixture, not an oracle: the engine output is what it pins.
- H3/H4: no test (config and docs).

## Acceptance

- Gates green for `screamingface` and `screamingface-engine` (append-only and `--skip-append-only`)
  and `repo`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** H1: `_evaluation/url4.py` (`_replayed_url4`, `_require_known_operators`;
  `_candidate_from_url4` stays as the recovery-only wrapper for existing callers), `url4.py`
  (shared `_combine_operator_pairs`), `client.py` (passes `self._operator_catalog.load` in both
  clients), `tests/test_url4_replay_operator_check.py`. H2: engine
  `test_combine_evidence_contract_fixture.py` and `data/combine_contract/evidence_cases.json`; SDK
  `tests/test_combine_evidence_contract.py`. H3: `.github/workflows/screamingface-tests.yml`. H4:
  `packages/screamingface/CHANGELOG.md`.
- **Tests and RED:**
  - H1 first cut: 8 tests, 7 RED (the plain-url4 test is a characterization and passed at once).
  - H1 unpinned round: 2 tests RED (the run transport was called), then GREEN.
  - H1 review round: the file grew to 17 tests (corrective-loop replay, unreachable catalog,
    unpinned forms `mode`, `mode@01`, `Mode@1`, zero `/v1/operators` requests). Against the
    previous source 4 of them were RED; all 17 are GREEN now.
  - H2: engine 22 tests (11 RED first, the fixture was missing); SDK 11 tests (2 RED with the
    fixture moved away). The SDK decoder needed no change: it round-trips all ten entries.
- **Commits (oldest first):**
  - da6f9ce34 fix(sdk): check the operator catalog before a raw url4 replay spends
  - cf78f1752 test: pin the combine evidence contract from real engine output and decode it in the sdk
  - dde41858b ci(sdk): run the sdk tests when the engine combine conformance inputs change
  - 760645f9d docs(sdk): say the whole reducer stack ships and note the replay catalog check
  - 5a45c7137 docs(work): record the e4a combine hardening ledger
  - f6616d5f4 fix(sdk): refuse an unpinned operator name in a replayed url4
  - 9dc2e69b8 docs(work): record the unpinned operator follow-up gates
  - b4b6b87ec refactor(sdk): share the combine operator pairs and check the pinned form without I/O in a url4 replay
  - a079bac9e test: cover corrective, unpinned and unreachable replays and parametrize the evidence contract
  - 41d50f45f ci(sdk): watch two more engine inputs and fix the evidence changelog wording
- **Gates (final, after the review round):** `screamingface` with append-only ALL GATES GREEN (no
  offenders); `screamingface-engine` with append-only ALL GATES GREEN (no offenders); both with
  `--skip-append-only` ALL GATES GREEN; `repo` ALL GATES GREEN. An earlier SDK skip run failed once
  on `test_cache_saved_cost_submission.py::test_archive_money_never_reaches_the_result_or_the_board`,
  a pre-existing flake (it asserts the text `0.5` is absent from a payload that holds a timestamp);
  it passes alone and on rerun.
- **Decisions during review:** a replayed url4 must name exact pinned ids. The form check runs in
  `_replayed_url4` with no I/O through `_OperatorCatalog.from_pinned`, so a Fusion and a corrective
  loop give the same message (`... operator 'mode' is not a pinned id`). `Mode@1` in a corrective
  loop is refused earlier by the vote-spec rebuild with its own message.
- **Deviations:** none from the spec.
