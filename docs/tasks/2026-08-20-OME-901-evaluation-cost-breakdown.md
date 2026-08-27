---
id: OME-901
linear_url: https://linear.app/openmined/issue/OME-901/break-down-an-evaluations-cost-per-operation-instead-of-one-total
status: in_progress
type: epic
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-08-20
closed:
---

# Break down an evaluation's cost per operation instead of one total

Retain the accounting already observed during an evaluation, attribute only exact evidence to the
existing Candidate-operation and grading-Evidence records, and expose a completed-Report breakdown
without changing URL4, benchmark scores, model calls, or the existing live widget.

## Lineage audit result

- The final Candidate/run total is already exact when every observed call is priced.
- Generic URL4 span/usage facts reach the live Client, but nested Candidate member and synthesis
  calls have already coalesced into one outer Candidate span.
- ScreamingFace Engine already retains Candidate operation outputs and grading Evidence. One shared
  accounting value attaches to `CaseOperation` for generation/synthesis and `Evidence` for grading;
  there is no parallel grading operation ledger.
- One existing capture mechanism uses two isolated scopes: Candidate-local member/synthesis calls
  and a composition-root run scope for canonical grading calls.
- The retained breakdown needs a ScreamingFace Engine producer followed by a Python Client decoder,
  projection, and completed-Report UI. It requires no AI Gateway or `packages/url4` change.
- Candidate totals remain authoritative. Ambiguous values remain unknown; only cost gets an exact
  remainder where the arithmetic is supported.
- Existing live cost/cache behavior remains unchanged; semantic live parity stays in `OME-699`.
- Existing Gateway provider-attempt latency is retained as Provider time. No new timer or member
  wall duration is invented.

Evidence and the proposed dependency order are recorded in
`docs/work/2026-08-27-OME-901-runtime-accounting-lineage.md`. The approved design and plan are
`docs/spec/2026-08-27-OME-901-operation-accounting.md` and
`docs/plan/2026-08-27-OME-901-operation-accounting.md`.

## Implementation children

1. [OME-1030](https://linear.app/openmined/issue/OME-1030/retain-per-operation-evaluation-accounting-in-candidate-results)
   — ScreamingFace Engine producer and retained Candidate-result contract.
2. [OME-1031](https://linear.app/openmined/issue/OME-1031/decode-and-render-per-operation-evaluation-accounting)
   — Python Client decoder, projections, and completed-Report UI; blocked by OME-1030.

OME-1030 is in progress after explicit owner approval. OME-1031 remains in Backlog until the
Engine contract is reviewed. OME-699 retains ownership of later live semantic parity.
