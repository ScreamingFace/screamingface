---
ticket: OME-1769
stack: client-sf
status: in_review
started: 2026-10-29
---

# OME-1769 — make pinned-cache capture opt-in

## Intent

The owner reverses Q22: capture is off by default (Q31). A run captures only with `capture=True`.
Small change: the ticket body is the plan, and the spec change is the Q31 row and §1/§7 text in
`docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md`.

## Changes

- `client.py` (`Client`, `AsyncClient`) and `_default_client.py`: the normal overloads take
  `capture: bool = False`; the implementation resolves `capture = bool(capture)`. The replay
  overloads keep `Literal[False] | None`, so `capture=None` stays valid there.
- `_engine/transport.py`, `_evaluation/results.py`: docstrings no longer say capture is the default.
- Tests: `test_a_normal_run_does_not_capture_by_default`, `test_the_client_does_not_capture_by_default`
  (no `EvaluationWarning`), `test_module_level_evaluate_does_not_capture_by_default`. Comments in
  `test_reproduce_review.py` and the e2e FakeGateway updated.
- Docs: README, CHANGELOG (breaking change), five public-docs pages. The leaderboard publish example
  passes `capture=True`.

## Checks

- `uv run ruff check`, `ruff format --check`, `pyright`: clean.
- `uv run pytest -n auto --cov=screamingface --cov-fail-under=95`: 4936 passed, 38 skipped, 97.05%.
- public-docs: prettier clean on the changed pages.

## Notes

- The e2e tests no longer run the capture path by default. The unit tests still cover it.
- A submitted score is reproducible only if its run used `capture=True`.
