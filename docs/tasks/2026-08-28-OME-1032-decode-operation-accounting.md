---
id: OME-1032
linear_url: https://linear.app/openmined/issue/OME-1032/keep-each-operations-cost-and-token-facts-when-a-report-is-read-back
status: in_review
type: feature
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-28
closed:
---

# Keep each operation's cost and token facts when a report is read back

Parent: `OME-1031` (which keeps the computed views, `MemberResult.usage`, and the
completed-Report table). Grandparent: `OME-901`.

The Engine (`OME-1030`, PR #762) retains `accounting` on Candidate `CaseOperation`
and grading `Evidence`, emitted unconditionally and `null` when empty. The Client's
strict decoder rejected the unknown field, so every evaluation against that Engine
failed and #762's golden-replay lane was red. This slice decodes the retained value
and round-trips it through the public API and Report JSON — nothing more.

**Lands atomically with the Engine.** The field is required-nullable and the decoder
has no compatibility fallback, so either side alone turns CI red in the mirror-image
way. This branch is cut from `OME-901-runtime-accounting-lineage` and its PR targets
that branch, not `main`.

Ledger: `docs/work/2026-08-28-OME-1032-decode-operation-accounting.md`.
