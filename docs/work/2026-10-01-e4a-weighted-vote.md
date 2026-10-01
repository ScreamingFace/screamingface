---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# e4a-weighted-vote — constant weights for sf.Vote (OME-1289, unit 7)

## Intent

`sf.Vote(weights=[...])` gives each member a constant, positive weight. The Vote then compiles to
`weighted_mode@1` + `max_weight_holder@1` with a `weights` map in the combine spec. A wrong weight
count or a bad weight value fails at build time, before any call. `sf.Median(weights=...)` raises
`TypeError`. The spec is part of the url4 text, so weights are part of the replay identity. Covers
WV-1..WV-9. The Engine already runs the spec (units 1-3), so the Engine tests are contract pins.

## Planned changes

- SDK src: `reducer.py` (`Vote`, `Median`), `CHANGELOG.md`, `README.md` (one paragraph in unit 5's
  section), `tests/public_surface_snapshot.json` (only if the public signature changes it).
- SDK tests (new): `tests/test_weighted_vote.py`, `tests/test_weighted_vote_contract_fixture.py`.
- Engine data (new, SDK-written): `combine_contract/weighted_vote_specs.json`.
- Engine tests (new): `tests/unit/test_combine_weighted_vote.py`.

## Test plan

SDK (RED first, on a skeleton that accepts `weights` but does nothing with it): WV-1, WV-3, WV-8,
the weighted compile and repr, the 11-member url4 round trip (member_10 sorts before member_2 in
canonical JSON), the drift guard.
Engine (contract pins, GREEN at once by design): WV-2/H1/7, WV-4, WV-D2, WV-5, WV-9, WV-6 (route
level, real operators).

## Acceptance

- Both gates green (append-only: expected offender only `public_surface_snapshot.json`, if any),
  repo gate green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; nothing unlisted. `weighted_vote_specs.json` is written by
  `test_weighted_vote_contract_fixture.write_fixture()`; `reducer_specs.json` is untouched.
- **RED/GREEN:** the SDK side was RED for the right reason on a skeleton that accepted `weights` and
  stored it unchecked (28 of 30 tests failed on assertions such as DID NOT RAISE and a spec with
  `weights: null`). The two that passed at once pin shape the skeleton already had (the two
  `_from_spec` refusals of a weighted-operator spec without weights, and an absent extract). The
  drift guard was RED (file missing), then GREEN after `write_fixture()`. The Engine tests (WV-2/H1/7,
  WV-4/D2, WV-5, WV-9, WV-6) are contract pins and were GREEN on their first run by design.
- **WV-6 probe (before writing the test):** every bad-weights mutation returns `combine_spec_invalid`,
  `permanent True`, and records no operation call: missing `member_5`, `member_1: 0`, `member_1: -1`,
  `"weights": null` (with `weighted_mode@1`; message "weighted_mode@1 needs weights"), `NaN`
  (message "not valid JSON") and `1e309` ("Input should be a finite number").
- **Hand check (WV-4, WV-5):** tally order is score descending, then first-holder position; the score
  is the `Decimal(str(weight))` sum. `weighted_tie_3` `["9","12","12"]`: 9 scores 2, 12 scores 2, order
  [9, 12], chosen member_1 (sole holder of 9), agreement 2/4. `weighted_decimal_4`: 5 scores
  0.1+0.2+0.3 = 0.6 and 7 scores 0.6, tie, holders of 5 weigh 0.1/0.2/0.3 so member_3; reversed
  weights 0.3/0.2/0.1 give member_1. All as the spec says; a float sum would give 0.6000000000000001.
- **Commits:** see `git log e4a-samples..HEAD` on branch `e4a-weighted-vote`.
- **Gates:** `screamingface --base e4a-samples` with append-only: only offender
  `tests/public_surface_snapshot.json` (expected: the Vote and Median `__init__` signatures and
  `Vote.weights` changed); with `--skip-append-only`: ALL GATES GREEN. `screamingface-engine --base
  e4a-samples` with append-only: green (no offender); with `--skip-append-only`: ALL GATES GREEN.
  `repo`: ALL GATES GREEN.
- **Deviations:** `Vote._from_spec` also refuses (`cannot rebuild`) a weight map whose keys differ
  from `spec["members"]` (missing or extra key), and a weight value that is not an int or float
  (ratified by the coordinator). The cap deviation of round 0 is gone (see round 1).
- **Review round 1 (coordinator ACCEPT-WITH-FIXES; branch rebased onto `e4a-samples`):**
  `_MAX_REDUCER_MEMBERS` moved from `fusion.py` into `reducer.py` (fusion imports it back, no cycle);
  `_MAX_WEIGHT = sys.float_info.max / 256` is checked on the raw item in `_vote_weights`
  (`0 < item <= cap`; the OverflowError branch and the `math` import are gone); `_from_spec` refuses
  non-number weight values and passes raw values through the same validator; tests for the exact cap,
  `1e308`, `nextafter(cap)`, an extra weight key and bad value types; `weighted_cap_2` added to the
  fixture and an Engine test that the cap weight is accepted; WV-9 also pins agreement, chosen and
  tie; WV-6 adds an extra `member_6` key and a finite weight above the Engine cap (1e308); the compile
  test compares the full literal spec; README and CHANGELOG say where each error is raised and name
  the cap. Gates: `screamingface --base e4a-samples` with append-only: only offender
  `tests/public_surface_snapshot.json`; `--skip-append-only` for both stacks and `repo`: ALL GATES GREEN.
