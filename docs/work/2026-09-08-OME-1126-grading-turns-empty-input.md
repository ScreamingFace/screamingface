---
ticket: OME-1126
stack: screamingface-engine
status: done
started: 2026-09-08
finished: 2026-09-08
---

# OME-1126 — the two-turn protocol's model calls resolve their inputs to empty

## Intent

Live-run diagnosis (evidence on the OME-1126 issue, comment of 2026-09-08) captured the
MedXpertQA grading stage sending a model call whose entire user prompt was empty
(prompt_tokens=32 — system prompt only). Root cause is a double scope defect in the
board's expression (`medxpert/definition.py::_build`):

1. the grading-side turn-1 invocation reads `$item.cot_prompt`, but inside
   `preserve_candidate_outcome`'s protective iterate `$item` is the
   `{candidate_invocation, case_id}` struct — no `cot_prompt` → empty prompt;
2. the commit (turn 2) envelope references `$reasoning`, which is bound only inside that
   inner grading scope → the commit ships with empty reasoning, degrading the official
   two-turn protocol into a one-shot letter-last essay — the exact shape the grading
   parser's 35.5%-vs-70.2% regression note warns about.

Fix: bind the turn-1 `reasoning` invocation once at case-execution scope, ahead of the
commit, so both the commit envelope and the check read the same real turn-1 output; the
grading scope stops re-invoking the candidate.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/definition.py`
  — restructure `_build`: hoist `reasoning`, commit consumes it, `checked` stops
  invoking the candidate.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/protocol.py` — give
  `preserve_candidate_outcome` an ordered `bindings` parameter (mirroring
  `build_evaluation_protocol`) so a board can bind case-scope values the preserved
  invocation depends on.
- `apps/screamingface-engine/tests/unit/test_medxpert_protocol_turns.py` — NEW,
  end-to-end resolution against a MockTransport gateway (idiom of
  `test_grading_error_integrity.py`).

## Test plan

- RED: resolve `MEDXPERT.build(1)` linked to a model candidate against a recording fake
  gateway; assert (a) no model call carries an empty/blank user message, (b) the commit
  turn's request contains the question, the real turn-1 reasoning text, and the trigger,
  (c) the case scores against the letter committed in the commit turn.
- Boundaries: two cases (`build(2)`) keep per-case reasoning distinct.
- Error path unchanged: existing medxpert unit tests remain green and unmodified.

## Acceptance

- The new resolution test passes; every existing test passes unmodified.
- A live 2-case qwen3.7-flash run scores (no `aigateway_bad_response`), and the debug
  instrument captures nothing.
- `run_gates.py screamingface-engine` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `benchmarks/definition.py` (extracted `candidate_call`
  — the bare invocation for direct-sibling scope) and `medxpert/pins.py`
  (`PROTOCOL_REVISION` two-turn-cot-v1 → v2: the expression changed, so the exam
  re-addresses).
- **Commits:** 4f8a4f5e — fix(screamingface-engine): deliver real inputs to both MedXpertQA turns
- **Gates:** run_gates.py screamingface-engine — ALL GATES GREEN (2423 passed, 5 skipped;
  ruff, pyright, layering, coverage).
- **Deviations:** the planned fix assumed `bindings=` alone would suffice; url4 scoping
  probes showed sibling references resolve only within ONE group, so the commit also had
  to become a direct slot (`candidate_call`) instead of the `candidate()` wrapper. The
  protective-iterate body DOES see enclosing bindings, so the check side needed nothing
  extra. Live-run verification (solo qwen3.7-flash, limit=2) is owner-run and pending.
