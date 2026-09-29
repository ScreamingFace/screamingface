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
3. Add the shared nullable `OperationAccounting` contract. Keep the existing payload-bearing
   `OperationCall` Candidate-local, and add a separate payload-free run record containing only
   request identity and accounting; do not add a timer or serialized request identity. The
   Gateway's own validated attempt count IS retained (owner-approved 2026-08-28 in review of
   PR #762, reversing this step's earlier prohibition); no Engine-side counter is introduced.
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

## Client delivery notes — 2026-09-28

OME-1032 already delivered steps 1–2 of the Client slice. The owner authorized the remaining
OME-1031 implementation and a draft PR with a Jupyter review notebook on 2026-09-28.

- `CandidateResult.accounting` returns immutable derived rows and grouped summaries via
  `by_stage`, `by_operation`, `by_model`, `by_member`, and `by_case`.
- Member totals use exact direct-model operation identity in every retained Case. Composite
  members and loop internals stay unavailable rather than infer ownership from DAG dependencies.
- Missing records poison group totals. Cost reconciliation subtracts only existing, priced,
  disjoint Engine-owned records; unpriced retained records or an unknown root prevent a remainder.
- Duplicate/unknown operation identities and negative cost remainders disable the view with a
  payload-free diagnostic. Equal accounting values on different legitimate owners are not duplicates.
- Completed Report HTML uses native disclosures and a keyboard-scrollable table; no new JavaScript.
- `examples/14_report_accounting.ipynb` is an output-free deterministic, offline review notebook
  with explicitly synthetic observations. Its executable assertions also run in Client tests.

Owner review follow-up (2026-09-28): simplify the first view to activity, cost and labelled cache
outcomes; retain the full required operation columns in a collapsed details table. Keep Case
expansion within those details. Hide zero remainder in the first view, preserve it in details.

Owner approved the final layout: remove the separate accounting section, use native radio tabs
inside each Case (Answer & grading / Cost & usage), and show labelled activity blocks without
tables. Whole-run totals and any Unattributed run cost remain above the Cases. This supersedes
the prior cost-summary/disclosure design.

Approved visual polish: underline-only case tabs; operation title and cost share a header.
Group calls/cache, input/output tokens, and provider time into three stable columns. Move
explanations into a native About these numbers disclosure. Keep exact pricing and unknowns.

Owner follow-up: remove About these numbers and its explanation entirely; retain compact blocks.

Owner approved removing the grey rule above the first cost block; retain inter-operation rules.

Review fixes approved: render nonzero costs below USD 0.0001 with exact decimal precision,
including run remainders. Type AccountingRow.stage as generation | synthesis | grading.

## Approved review correction — 2026-09-29

1. Add regression tests for incomplete per-model totals, declared model attribution,
   ambiguous synthesis, and judge IDs differing from request model names.
2. Resolve missing identities from unambiguous declarations with no conflicting retained
   request identity. Unknown identity invalidates every named model summary; preserve the
   strict anonymous bucket and all other grouping behavior.
3. Run the full Client gates against the pre-follow-up PR head for append-only protection,
   record the result, commit and push to the existing PR branch.

## Partial-token review correction — 2026-09-29

1. Reproduce the owner's P2 report through evaluation, member usage projection and HTML.
2. Require both counts for a token total; render missing split components as `—`.
3. Preserve existing tests; verify partial counts in both directions, zero, unknown and
   complete controls, then run full Client gates and update PR #1097.
