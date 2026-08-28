---
ticket: OME-1023
stack: screamingface-engine
status: in_progress
started: 2026-08-27
finished:
---

# OME-1023 — Keep the GDPval judge's raw reply on valid verdicts

## Intent

A scored GDPval criterion's evidence row carries `raw_output: ""`, so a suspicious verdict
cannot be re-read against the reply that produced it. GDPval's `verdict.bind` keeps the raw
reply only on the invalid branch — a deviation from HealthBench and DRACO, which persist it
on every verdict. Restore the engine convention. Owner decision: fix lands on the OME-971
branch (PR #714) rather than a separate PR.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/gdpval/verdict.py` — move
  `raw_output` into the common record so the valid branch keeps it (HealthBench shape).
- `apps/screamingface-engine/tests/unit/test_gdpval_grading.py` (or the file holding
  `bind` tests) — new assertions: a valid verdict carries the reply bytes.
- `apps/screamingface-engine/tests/unit/test_gdpval_aggregate.py` — new assertion: a valid
  evidence row's `raw_output` is the judge's reply, not `""`.
- No change to `aggregate.py` expected — it already reads `record.get("raw_output", "")`.
- No grader-prompt or revision-hash input changes.

## Test plan

- RED: valid `bind` result includes `raw_output == raw` (invariant: every verdict is
  auditable against the reply that produced it).
- RED: aggregate evidence for a valid verdict carries the reply text.
- Existing invalid-branch tests stay untouched (raw kept + reason).

## Acceptance

- A scored criterion's evidence row shows the judge's actual reply.
- Invalid-reply behavior byte-identical to before.
- `run_gates.py screamingface-engine` all green; no prior test modified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `benchmarks/gdpval/verdict.py` (raw_output moved into the common record;
  docstring updated), `tests/unit/test_gdpval_verdict.py` (+3 tests, append-only). No
  `aggregate.py` change needed — its `record.get("raw_output", "")` picks the value up.
- **Commits:** pending — owner reviewing locally before commit (owner instruction).
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only check, ruff ×2,
  pyright, layering, pytest 2,154 w/ coverage ≥80). RED confirmed first: 3 failures,
  `KeyError: 'raw_output'`.
- **Deviations:** none from plan; test file is `test_gdpval_verdict.py` (the planned
  `test_gdpval_grading.py` name does not exist in this suite).
