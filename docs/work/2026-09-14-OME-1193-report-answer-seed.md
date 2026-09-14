---
ticket: OME-1193
stack: screamingface
status: done
started: 2026-09-14
finished: 2026-09-14
---

# OME-1193 — Name the answer seed in the run report

## Intent

OME-1038 lets a run declare an answer seed, but `report.json` never names it — a
researcher's N-seed variance study leaves N unlabeled samples. This unit adds the seed to
the SDK: `evaluate(answer_seed=…)` sends `X-Answer-Seed` on run start, and the per-run
report record carries `answer_seed` beside `run_id`/`trace_id`. SDK-only; the engine half
shipped in PR #927.

## Planned changes

- `packages/screamingface/src/screamingface/client.py` — `answer_seed: int | None = None`
  kwarg on sync + async `evaluate`, threaded to the evaluation runner.
- `packages/screamingface/src/screamingface/_engine/transport.py` — run-start request
  gains the `X-Answer-Seed` header when declared; no header when not.
- `packages/screamingface/src/screamingface/_evaluation/` (runner/results) — carry the
  declared seed into the assembled record.
- `packages/screamingface/src/screamingface/report.py` — `answer_seed: int | None` on the
  per-run record model, serialized only when declared (absence-is-default, mirroring the
  engine).

## Test plan

- RED: (1) `evaluate(answer_seed=7)` → transport sends `X-Answer-Seed: 7` (fake engine
  asserts the header); (2) no kwarg → no header, and the serialized report is
  byte-identical to today's (INVARIANT: absence is the default); (3) report record
  round-trips `answer_seed` through serialize → parse; (4) declared seed appears in the
  written `report.json`.

## Acceptance

- `evaluate(answer_seed=7)` sends the header and the report record carries 7.
- Undeclared: no header sent; report serializes exactly as today.
- Round-trip preserves the field. Gates: run_gates.py screamingface all green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, but the seed rides the compiled `Candidate`
  (`_evaluation/model.py`: field + `_with_answer_seed` + `_answer_seed_value`) instead of a
  new transport-protocol kwarg — the run-transport protocol and every prior fake stay
  untouched. Plus `_engine/transport.py` (header on both starts), `_evaluation/runner.py`
  (stamp once, one tuple for observer/preflight/run), `_evaluation/url4.py` (replay path),
  `_evaluation/results.py`, `report.py` (validated field, serialized as stable null key),
  `client.py` (kwarg on 4 overloads + 2 impls), `CHANGELOG.md`, regenerated
  `tests/public_surface_snapshot.json` (sanctioned procedure), new
  `tests/test_answer_seed_report.py` (13 tests).
- **Commits:** rides OME-1038-answer-seeds / PR #927 (owner decision) — 9d389103 feat(screamingface): name the answer seed in the run report.
- **Gates:** run_gates.py screamingface ALL GREEN (ruff, pyright, pytest 1480 passed cov ≥95,
  notebooks, build, distribution). Append-only waived once with owner approval for the
  regenerated public-surface snapshot.
- **Deviations:** transport-kwarg design dropped mid-unit for the Candidate-borne seed
  (protocol untouched); url4-replay path INCLUDED (reproduction is the use case);
  report serializes `answer_seed` as an always-present null-when-unseeded key per the
  report's stable-key convention.
