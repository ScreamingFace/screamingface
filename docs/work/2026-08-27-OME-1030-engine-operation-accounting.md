---
ticket: OME-1030
stack: screamingface-engine
status: done
started: 2026-08-27
finished: 2026-08-28
---

# OME-1030 — Retain per-operation evaluation accounting

## Intent

Retain exact current-run model accounting on the benchmark records that already own Candidate
member/synthesis and grading Evidence semantics. Reuse the Engine's existing operation recorder
and Gateway accounting facts without changing URL4, AI Gateway, model execution, scoring, or live
Event behavior.

## Planned changes

- Extend `src/screamingface_engine/operation_calls.py` with the shared strict accounting value and
  run-local capture state.
- Deepen connector accounting normalization without adding a timer, attempt counter, or payload
  retention.
- Add a composition-root streaming `Executor` decorator around the unchanged `Url4Executor`.
- Deepen Candidate operation projection and add the solo-Model operation.
- Add the shared grading request-key port and board-owned registrations; attach unique accounting
  to grading Evidence.
- Evolve benchmark Candidate Invocation/Result v1 contracts directly.
- Add dedicated tests and update the existing strict wire-shape fixtures/assertions that must name
  the new required-null field or the composition wrapper.
- Preserve the absent `operations` envelope when a solo named source is a nested Recipe and no
  model output can be attributed.
- Index run-scoped grading calls incrementally by request key so verdict lookup is linear across a
  run rather than scanning every preceding call for every Evidence record.
- Sum retained fixed-point costs independently of the ambient Decimal precision.
- Aggregate several uniquely owned request keys for one grading Evidence owner instead of dropping
  that owner's accounting.
- Preserve an explicit all-null operation list for a multi-operation Candidate when no call can be
  attributed, while keeping a solo nested Recipe's envelope absent.

## Test plan

- Characterize the existing pre-accounting `CaseOperation` and `Evidence` dictionaries in the five
  current test modules before adding the nullable field.
- RED tests for complete, partial, omitted, unpriced, cache-hit, multi-call, and model-identity
  normalization.
- RED tests for Candidate-local versus run-local scope ownership, concurrent runs, nested tasks,
  cancellation, and early iterator close.
- RED tests for unique and ambiguous Candidate projection, solo Model, and CorrectiveLoop
  non-attribution.
- RED tests for unique/duplicate grading request keys, redraw aggregation, deterministic Evidence,
  and HealthBench/GDPval/DRACO vertical slices.
- Regression tests for unchanged root Usage, score, Evidence meaning/raw output, URL4 rendering,
  cache keys, retries, model-call cardinality, failures, and live Events.
- RED regression tests for a solo nested Recipe producing no empty operation and for grading
  lookup indexing only newly appended calls.
- RED regressions for full-precision cost sums, multiple unique request keys per Evidence owner,
  and an all-unattributed multi-operation Candidate; characterize malformed omission metadata as
  deliberately unavailable rather than partially trusted.
- Run `uv run ../../.claude/scripts/run_gates.py screamingface-engine` from the repository root.

## Acceptance

- `CaseOperation.accounting` and `Evidence.accounting` are required nullable fields using one
  shared `OperationAccounting` contract.
- Exact uniquely attributable Model/Fusion/Pipeline and rubric-judge accounting is retained once;
  ambiguity, partial evidence, and unsupported paths remain null.
- CorrectiveLoop nested details remain unattributed while its authoritative total is unchanged.
- No accounting state leaks across runs or lifecycle exits.
- No `packages/url4`, AI Gateway, URL4 expression, scoring, model-call, cache, retry, or live-widget
  behavior changes.

## Outcome

- **Actual files:** added the shared accounting contract, payload-free request identity, grading
  ownership registry, and generic composition-root capture decorator; deepened connector and
  operation-call normalization; projected exact accounting through Candidate operations and the
  DRACO, HealthBench, GDPval, and IFEval contracts; added dedicated contract, normalization,
  ownership, lifecycle, ambiguity, and board vertical-slice tests; updated approved strict legacy
  shape and composition tests plus the spec, plan, and task mirror. Review follow-up suppresses an
  entirely unattributed solo nested-Recipe operation envelope and incrementally indexes grading
  calls by request key instead of rescanning the run ledger for each verdict. Final review follow-up
  makes fixed-point cost sums independent of ambient Decimal precision, aggregates every uniquely
  owned request key for revised grading evidence, and preserves explicit null entries when a
  multi-operation Candidate cannot be attributed.
- **Commits:** this implementation commit — `feat(screamingface-engine): retain operation
  accounting`.
- **Gates:** `python3 .claude/scripts/run_gates.py screamingface-engine --skip-append-only` — ALL
  GATES GREEN (ruff check, ruff format, pyright, layering, and full coverage suite). The
  append-only exception is the explicit owner approval recorded below. Review regressions: 22
  focused accounting/operation-output tests and 38 benchmark vertical-slice tests passed. Final
  review regressions: 51 focused accounting and board tests passed; the full Engine gate passed
  again.
- **Deviations:** Candidate invocation needed a separate `isolate_operation_calls` switch so its
  model-call ledger is isolated from grading without discarding the existing nested Candidate
  outcome capture. This preserves the published behavior while enforcing the planned ownership
  boundary. Malformed Gateway omission metadata remains deliberately fail-closed: no attempt-level
  identity, token, latency, or cost facts are trusted when completeness cannot be established, and
  this is now characterized by a regression test. Request-key hashing remains separate from the
  catalogue ETag helper because their lengths, serialization rules, and layer ownership differ.
  The capture scopes overlap by lifetime but have no ordering dependency. No scope, URL4, Gateway,
  score, live-event, or call-cardinality deviation.

## Confidence-gate decisions

- **Append-only test guard:** the owner explicitly approved updating prior tests where the approved
  required-null `accounting` contract, board route signature, or composition-root executor wrapper
  made the old expected shape mechanically stale. Assertions were deepened, not weakened. The
  guard correctly stopped on those files; remaining gates are run with `--skip-append-only` under
  that recorded approval.
