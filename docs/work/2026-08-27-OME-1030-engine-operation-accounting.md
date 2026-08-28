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

- Keep payload-bearing Candidate operation capture local, and add a separate run-local recorder
  containing only request identity and strict accounting.
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
- Render each DRACO criterion's grading context and invariant Judge intent once, then reuse those
  exact bytes across its seeded judge-pass registrations.
- Retain accounting for provider-refused terminal calls before the refusal exits the connector.
- Require provider and served-model identity agreement across every Gateway attempt whose usage
  contributes to one retained call.
- Keep accounting fail-open when malformed provider metadata cannot satisfy the strict retained
  contract: preserve the model answer and retain no accounting rather than failing execution.
- Split Candidate payload capture from run-level grading accounting capture so the latter never
  retains model outputs.
- Poison a multi-round operation's retained accounting when any consumed round cannot be
  normalized, rather than publishing a falsely exact subtotal.
- Reconcile grading accounting at final Candidate Result construction so a request-key collision
  discovered after an earlier verdict retroactively nulls every affected Evidence item.
- Skip complete-request hashing while Candidate execution has suspended run-level grading capture.
- Synchronize the approved spec with the reviewed payload-bearing/payload-free recorder split and
  the Engine's canonical provider identity on cache hits.
- Preserve the pre-existing terminal-attempt identity used by live/root Usage while requiring
  unanimous attempt identity only for the new retained operation breakdown.
- Keep confirmed cache-hit provider identity canonical to the requested route and suppress served
  model identity when Gateway accounting is incomplete.

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
- RED regression that a five-pass DRACO criterion renders its context and intent once rather than
  once per pass.
- RED connector regression proving a refused response retains its exact accounting.
- RED normalization regressions for provider/model disagreement across Gateway attempts and for
  malformed optional identities remaining fail-open.
- RED capture regression proving the run-level grading ledger retains request identity/accounting
  but no model output while Candidate-local attribution remains unchanged.
- RED regressions proving live/root Usage keeps terminal-attempt identity and retained accounting
  rejects disagreeing or incomplete attempt identity, including confirmed cache hits.
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

- **Actual files:** added the strict `OperationAccounting` contract, nominal payload-free request
  key, grading ownership registry, and composition-root capture decorator. Candidate-local capture
  retains the outputs required by existing operation attribution; the run-level grading ledger
  retains only request identity and accounting. DRACO, HealthBench, and GDPval attach uniquely
  owned judge accounting to Evidence; deterministic IFEval Evidence remains null. Connector
  hardening retains provider refusals, requires attempt identity agreement, preserves exact
  fixed-point sums, and makes malformed bookkeeping fail-open. Test-only modules were split without
  semantic edits to keep every Python file under the 450-line ceiling.
- **Commits:** `feat(screamingface-engine): retain operation accounting`;
  `fix(screamingface-engine): harden accounting attribution`;
  `fix(screamingface-engine): preserve exact accounting evidence`;
  `perf(screamingface-engine): reuse DRACO judge prompts`; and
  `fix(screamingface-engine): harden operation accounting boundaries`; and
  `fix(screamingface-engine): preserve live and retained identity contracts`.
- **Gates:** `python3 .claude/scripts/run_gates.py screamingface-engine --skip-append-only` — ALL
  GATES GREEN: Ruff check, Ruff format, Pyright, layering, and the full pytest/coverage suite
  (2,230 tests collected; coverage remained above the 80% gate). The final focused accounting
  regression set passed 69 tests. `git diff --check` passed. The append-only exception is the
  explicit owner approval recorded below.
- **Non-regression:** no `packages/url4`, AI Gateway, Client, URL4 expression, benchmark data,
  rubric, scoring formula, retry policy, cache key, model-call cardinality, or live Event change.
  DRACO prompt rendering was extracted and pinned byte-identical. Live/root Usage retains its
  pre-existing terminal-attempt identity contract; only the new retained breakdown requires
  all-attempt agreement. Cache hits retain the canonical route provider and suppress incomplete
  served-model evidence. Root usage remains authoritative; unsupported and ambiguous work remains
  null rather than guessed. The evolved required-null wire fields require OME-1031's strict Client
  decoder to deploy first or atomically.
- **Deviations:** Candidate execution suspends the run-level grading ledger while preserving its
  existing Candidate-local output recorder; this additional separation was required to satisfy the
  reviewed no-payload run-scope invariant. Request-key hashing remains separate from the catalogue
  ETag helper because its serialization, length, and layer ownership differ. The existing PR branch
  retains the parent name `OME-901-runtime-accounting-lineage`; commits, task mirror, and PR body
  identify the implementation child OME-1030. No runtime-scope or product-behavior deviation.

## Confidence-gate decisions

- **Append-only test guard:** the owner explicitly approved updating prior tests where the approved
  required-null `accounting` contract, board route signature, or composition-root executor wrapper
  made the old expected shape mechanically stale. Assertions were deepened, not weakened. The
  guard correctly stopped on those files; remaining gates are run with `--skip-append-only` under
  that recorded approval.
- **Live identity regression:** the owner explicitly approved restoring the prior terminal-attempt
  identity assertion after review found that the exact-only retained policy had unintentionally
  changed the shared live/root Usage reader. A separate retained-accounting regression now pins
  unanimous attempt identity without changing live behavior.
