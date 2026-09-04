---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-09-04
finished: 2026-09-04
---

# OME-1013 — Finish diagnostic contract hardening

## Intent

Close the final agreed correctness and public-contract gaps before merge: accept only the
Client-supported lowercase W3C traceparent grammar, directly pin the public diagnostics lookup
facade, and report the canonical source-tree Client version in diagnostic receipts.

## Planned changes

- `packages/screamingface/src/screamingface/_diagnostics/evaluation.py`
- `packages/screamingface/src/screamingface/_diagnostics/capture.py`
- `packages/screamingface/tests/test_evaluation_diagnostics.py`
- `packages/screamingface/tests/test_diagnostic_capture.py`
- `packages/screamingface/tests/test_public_surface.py`
- `packages/screamingface/tests/public_surface_snapshot.json`

## Test plan

- RED: reject reserved uppercase `FF` and other non-supported traceparent spellings instead of
  retaining their trace id.
- RED: a source-tree Client receipt uses the canonical `0.0.0+source` version marker.
- RED: directly snapshot `screamingface.diagnostics`, including `get()` and `last()` signatures.
- GREEN: run focused diagnostic, version, and public-surface tests, followed by every ScreamingFace
  quality gate.

## Acceptance

- Only lowercase version `00` traceparents with lowercase nonzero trace/span ids become receipt
  correlation evidence.
- Diagnostic Client version resolution agrees with `sf.__version__` in installed and source-tree
  environments.
- Breaking changes to the public diagnostics lookup facade fail the public-surface snapshot test.
- No URL4 parameter capture, new architectural seam, or unrelated serialization refactor is added.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** replaced the permissive traceparent parser in
  `packages/screamingface/src/screamingface/_diagnostics/evaluation.py` with the exact supported
  lowercase version-00 grammar; reused the canonical resolver in
  `packages/screamingface/src/screamingface/_diagnostics/capture.py`; added boundary coverage in
  `packages/screamingface/tests/test_evaluation_diagnostics.py` and
  `packages/screamingface/tests/test_diagnostic_capture.py`; directly pinned the public facade in
  `packages/screamingface/tests/test_public_surface.py` and its snapshot; and recorded this ledger.
- **Commits:** this iteration's `fix(screamingface): finish diagnostic contract hardening` commit.
- **Gates:** RED confirmed four noncanonical traceparents, the divergent source-tree version, and
  the missing public-surface snapshot entry; 50 focused tests passed; Ruff and Pyright passed; the
  complete `python3 .claude/scripts/run_gates.py screamingface --skip-append-only` suite completed
  with `ALL GATES GREEN` (Ruff lint/format, Pyright, full pytest with at least 95% coverage,
  notebook validation, build, and distribution validation).
- **Deviations:** the owner-approved public-surface hardening necessarily updated an existing
  snapshot and its pinned-module tuple, so the preservation check was skipped after correctly
  flagging those changes. The complete suite ran against a byte-for-byte-verified clean worktree
  because the feature worktree contains the owner's modified quickstart notebook and exported
  diagnostic JSON; both remain untouched. URL4 parameter capture, traceback-renderer lifecycle,
  serialization/export cleanup, and a speculative diagnostics registry remained intentionally out
  of scope.
