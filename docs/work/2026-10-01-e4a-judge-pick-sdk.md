---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# e4a-judge-pick-sdk — sf.Judge and the reducer signal infrastructure (OME-1289, unit 8 SDK)

## Intent

`sf.Judge(model, returns="label"|"scores", rubric=..., params=...)` is a Fusion synthesizer. It
compiles to two url4 sources: a judge model call (`judge_N`, with the `judge-template@1` text at the
head of its system prompt) and one combine call that reads the judge reply as `signals.judge`. The
combine step copies the chosen member's text byte for byte. This unit also builds the base hooks that
units 9 and 10 reuse: `_ModelSignal`, `Reducer._signals/_rebuild/_python`, `FIELD_PATH`,
`_next_binding`, `_operation_shape`, the topology `signals` key, and the `binding` model param
reservation. The Engine half (judge operators, attribution-only `binding`) is on another branch, so
every test here uses fixture catalogs.

## Planned changes

- SDK src: `judge.py` (new), `_evaluation/reducer_signals.py` (new), `reducer.py`,
  `_evaluation/candidate.py`, `_evaluation/topology.py`, `url4.py`, `_evaluation/url4.py`,
  `accounting.py`, `_candidate_policy.py`, `__init__.py`, `CHANGELOG.md`, `README.md`.
- SDK tests (new): `tests/_combine_flow_fixtures.py` (ids for units 8-10), `test_reducer_signals.py`,
  `test_judge_reducer.py`, `test_judge_url4_round_trip.py`, `test_judge_report.py`.
- `tests/public_surface_snapshot.json` regenerated (the one allowed append-only offender).

## Test plan

RED first on skeletons: `_next_binding`, `_fusion_context(signals)`, `_operation_shape`, `FIELD_PATH`,
`Judge` validation and the `binding` reservation, the JG-7 template, JG-6 compile (judge and combine
sources, topology JSON), P2 fingerprint, two-judge numbering, only-a-Fusion-synthesizer guards, url4
round trip and tampering, corrective replay, JG-H3 report, JG-10 accounting row. CHAR tests pass at
once by design: a reducer without signals compiles as before (SL-1), the existing reducer goldens.

## Acceptance

- `screamingface --base e4a-weighted-vote` with append-only: only `public_surface_snapshot.json`.
- `screamingface --skip-append-only` green, `repo` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; nothing unlisted. New: `judge.py`, `_evaluation/reducer_signals.py`,
  `tests/_combine_flow_fixtures.py` (all 28 operator ids of units 8-10, a literal), and the four test
  files. Edited: `reducer.py`, `_evaluation/candidate.py`, `_evaluation/topology.py`, `url4.py`,
  `_evaluation/url4.py`, `accounting.py`, `_candidate_policy.py`, `__init__.py`, `CHANGELOG.md`,
  `README.md`, `tests/public_surface_snapshot.json` (regenerated).
- **RED/GREEN:** RED for the right reason (assertions, not ImportError) on skeletons that returned
  empty values: `_next_binding`, `_fusion_context(signals)`, `_operation_shape`, `FIELD_PATH` valid
  paths, the whole of `test_judge_reducer.py` except the guard test, the round trip, six tamper cases
  and the corrective replay, and the accounting row (JG-10). Then GREEN with the real code. These pass
  at once by design: the CHAR test (a reducer without signals compiles as before, SL-1), the
  guard test (`a Judge is only a Fusion synthesizer`: the existing guards already cover it), JG-H3
  (the decoders from unit 4 already carry `op_judge_1` and `combine.judge`), the FIELD_PATH reject
  cases against the placeholder, and ten tamper cases that the new decoder rejects by construction.
- **Gates:** `screamingface --base e4a-weighted-vote` with append-only: only offender
  `tests/public_surface_snapshot.json` (expected: `sf.Judge` and the `Judge` entry in `__all__`);
  with `--skip-append-only`: ALL GATES GREEN (ruff, format, pyright, pytest with coverage >= 95,
  notebooks, build, distribution). `repo`: ALL GATES GREEN. The two known flaky tests did not fail.
  A byte-stability probe (4 hash seeds) gave one url4 for a scores Judge with params.
- **Deviations:** none from the behavior spec. Small choices: `Judge._rebuild` accepts only the exact
  two spec shapes (label: `label` + `by_label`, no args; scores: `scores {"source":"judge"}` +
  `max_score`) and refuses a spec with an extract, a normalizer or weights, instead of deciding on
  the reduce name alone. `_signal_role` (topology decoder) maps the key `judge` to the role `judge`
  and is the one place unit 9 adds `writer_<field>`. `_operation_shape` returns (kind, suffix) for the
  node only; the writer label with its field name (`{fusion} write {F}`) is for unit 9 to extend.
