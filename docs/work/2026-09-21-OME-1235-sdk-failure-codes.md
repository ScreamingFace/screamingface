---
ticket: OME-1235
stack: screamingface
status: in_progress
started: 2026-09-21
finished:
---

# OME-1235 — Refuse undeclared failure names in the SDK and pin its list to the engine's

## Intent

SDK half of the OME-1233 epic. The SDK's `Failure` primitive validates `code` only as
non-empty text, so a renamed or misspelled code silently changes what a researcher
reads and what `case_result` branches do. Mirror the engine's declared vocabulary in
the SDK (the FailureStage house-pattern duplication), refuse undeclared codes, and
bind the two copies with a conformance test that parses the engine's source — no
cross-app import.

## Planned changes

- `packages/screamingface/src/screamingface/_report_primitives.py`: `DECLARED_FAILURE_CODES`
  frozenset + the `aigateway_http_[1-5]\d\d` family + `is_declared_failure_code`; the
  `Failure.__init__` code check refuses undeclared codes.
- New `packages/screamingface/tests/unit/test_failure_code_conformance.py`: ast-parses
  `apps/screamingface-engine/.../benchmarks/contract.py` (repo-relative, skip-guarded
  when the engine source is absent, e.g. installed-package runs) and asserts set and
  family equality with the SDK copy.
- SDK tests pinning the retired `no_valid_judge_verdict` spelling update to
  `judge_reply_invalid` (owner-approved reconciliation, decided on OME-1234).
- Docs: the declared list documented for report consumers (module docstring on the
  SDK copy — the list itself is the reference).

## Owner decisions (2026-09-21)

- SDK is STRICT like the engine: refuse undeclared codes at Failure construction.
  ~28 prior fixture tests using placeholder codes ("failed", "Provider Error",
  "unsafe_text", retired spellings) migrate to declared codes — owner approved the
  batch edit. Consequence accepted: reports published before the reconciliation
  (carrying no_valid_judge_verdict) will refuse to load; acceptable pre-launch.

## Review fixes (PR #1000 review, 2026-09-21)

- Blocker (conformance never fires on engine drift, CI is path-filtered): fixed with
  an ENGINE-SIDE twin test (apps/screamingface-engine/tests/unit/
  test_failure_code_conformance.py) parsing the SDK source — whichever side drifts,
  that side's lane goes red. Chosen over editing workflow triggers (owner territory).
- Family bind made bidirectional: both twins assert the compiled pattern strings are
  byte-identical, not just accepted examples.
- Dead-battery skip tightened on both twins: skip only when the sibling app/package
  DIR is absent (installed run); a present dir with a missing file FAILS.
- Misnamed decode test renamed (test_failure_code_uses_the_declared_engine_contract)
  and extended into the wire-boundary refusal pin: undeclared code payload →
  sf.ExecutionError — the only decode-path pin.

## Test plan

- RED: SDK `Failure(code="undeclared")` raises (invariant: an undeclared code cannot
  enter a Report object).
- RED: conformance — mutate-free equality of engine and SDK sets + family patterns
  (invariant: a name added on one side and forgotten on the other fails loudly).
- Keep green: declared codes (incl. `aigateway_http_429`) construct unchanged;
  `case_result` `provider_refusal` semantics untouched.

## Acceptance

- Undeclared code → ValueError on SDK Failure; declared + family codes pass.
- Conformance test fails if either copy drifts.
- Full screamingface stack gates green (incl. notebooks, build, distribution).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
