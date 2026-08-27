---
title: Retain and present evaluation accounting by operation
ticket: OME-901
status: approved
date: 2026-08-27
spec: ../spec/2026-08-27-OME-901-operation-accounting.md
---

# Retain and present evaluation accounting by operation

The owner approved this revised plan. Work lands in two ordered PRs; neither changes
`packages/url4` or AI Gateway.

## 1. ScreamingFace Engine producer (`OME-1030`)

1. Add characterization tests pinning current root Usage, live Events, Candidate operation outputs,
   grading Evidence, URL4 rendering, retries, cache behavior, and CorrectiveLoop isolation.
2. Add RED normalization tests for complete/partial/omitted Gateway accounting, cache outcomes,
   multi-call strict sums, model identity disagreement, and existing provider latency.
3. Add the shared nullable `OperationAccounting` contract and deepen the existing
   `OperationCall`; do not add a timer, attempt counters, or serialized request identity.
4. Add RED recorder-scope tests for Candidate isolation, run capture, concurrent runs, nested DAG
   tasks, cancellation, and early async-generator close.
5. Implement a ScreamingFace Engine composition-root `Executor` decorator that enters the run
   recorder around the unchanged generic `Url4Executor`.
6. Deepen the existing Candidate projector so unique Model/Fusion/Pipeline member and synthesis
   calls populate `CaseOperation.accounting`; add the solo Model operation. Pin ambiguous equal
   operations and CorrectiveLoop as unavailable rather than guessed.
7. Add a shared grading request-key port. Each rubric board registers its exact authored judge
   request with its Evidence key; the connector records the same in-memory key from the actual
   request. Attach strict accounting to Evidence only when the join is unique.
8. Evolve Candidate Invocation/Result v1 directly and add vertical slices for HealthBench,
   GDPval, DRACO redraws, deterministic Evidence, cache hits, tool/retry rounds, duplicate request
   keys, unpriced calls, and partial evidence.
9. Prove scores, Evidence meaning/raw output, outputs, failures, root totals, URLs, cache keys,
   retries, and call cardinality are unchanged. Run the complete Engine gates and review
   `origin/main...HEAD` before opening the Engine PR.

## 2. Python Client consumer (`OME-1031`)

1. Add RED decoder/round-trip tests for `OperationAccounting` on Candidate `CaseOperation` and
   grading Evidence, including required-null fields and malformed counts.
2. Decode the evolved v1 contract without compatibility fallback.
3. Add computed views grouped by stage, operation, model, member, and Case. Populate
   `MemberResult.usage` only from unique Candidate operations; keep `duration_ms` null.
4. Add cost-only reconciliation tests. Show an exact unattributed cost remainder only when root and
   attributed costs are known and disjoint; never claim an exact token remainder.
5. Render the completed-Report SFDS breakdown with Calls, Cache, Tokens, Cost, and **Provider
   time**. Keep per-Case detail expandable/API-accessible and unknown values explicit.
6. Pin CorrectiveLoop as total-only/unattributed and ambiguous work as unavailable.
7. Add one same-run regression proving generic detailed Events still reach `on_event`, while the
   completed Report uses retained semantic accounting. Keep the live evaluation widget unchanged.
8. Run the complete Client gates, notebook/build checks, SFDS review, and
   `origin/main...HEAD` review before opening the Client PR.

## 3. Dependency order

```text
OME-1030 Engine retained accounting
                ↓
OME-1031 Client decode + completed-Report presentation
                ↓
OME-699 optional later live typed semantic parity
```

`OME-784` separately owns accounting/evidence for failed calls that do not survive into a
completed Candidate operation or grading Evidence.

## 4. Owner approval gate

Before implementation, confirm:

- accounting lives on Candidate `CaseOperation` and grading Evidence;
- Provider time is explicitly not wall-clock duration;
- CorrectiveLoop nested detail and failed-path accounting remain deferred;
- the live evaluation widget remains unchanged;
- implementation may begin with `OME-1030`.
