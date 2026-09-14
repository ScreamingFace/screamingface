---
ticket: OME-981
stack: screamingface-engine
status: done
started: 2026-09-13
finished: 2026-09-13
---

# OME-981 — IFEval collected failure attribution

## Intent

Identify proven Gateway-call failures as Candidate failures in IFEval, retaining
unknown collected failures at the existing grading fallback.

## Planned changes

- IFEval grade.py: narrowly recognize the Engine connector's diagnostic codes.
- New regression tests exercising connector errors through URL4 collection and aggregation.
- Specification, plan, and task mirror.

## Test plan

RED first: Gateway HTTP/transport/response failures become candidate-stage.
Unknown codes, kind/message-only rows and genuine protected checker failures stay
grading-stage. Preserve safe diagnostics and malformed-row rejection. Run Engine gates.

## Acceptance

No message matching or blanket provider-prefix rule. No changes to successful scores,
denominators, benchmark identity, shared protocol, or other benchmarks.

## Outcome

- Actual files: IFEval grade.py, one new regression module, and the planned docs.
- RED: 11 failures and 11 passes before the production change. GREEN: all 22 new
  cases pass; combined focused run with existing unscored tests: 27 passed.
- Gates: `uv run .claude/scripts/run_gates.py screamingface-engine` ALL GATES GREEN:
  append-only tests, Ruff lint/format, Pyright, layering, full pytest and coverage ≥80%.
- Commit: `fix(engine): attribute known IFEval Gateway failures to candidate`;
  body `Refs: OME-981`.
- Wisdom review: small board-local classifier; no dependency, secret, schema,
  public interface or shared execution changes. Explicit unknown-code fallback;
  existing checker attribution and successful results remain protected.
- Deviations: none. Linear stays open pending draft review/merge.
