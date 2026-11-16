---
id: OME-1835
linear_url: https://linear.app/openmined/issue/OME-1835/return-a-benchmark-runs-report-by-reference-so-its-per-case-results
status: in_review
type: improvement
priority: none
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-16
closed:
---

# Return a benchmark run's report by reference so its per-Case results never sit in memory at once

Unit 1 of memory fix 3. The aggregate writes the Candidate Result one Case at a time into a
run-scoped spool: inline up to the inline cap, else a streamed artifact sink. url4 carries a short
reference, and `build_result` redeems it for the artifact. The bytes and the SDK contract do not
change. Peak per Case: 39.1 → 31.9 KiB (5-member Fusion), 77.6 → 32.7 KiB with one emoji in one
answer. Unit 2 (parked Cases, which removes the `CaseResult` list peak) follows.

Related: OME-1885, OME-1887.

Spec: `docs/spec/2026-11-16-streamed-candidate-result.md`. Plan: `docs/plan/2026-11-16-streamed-candidate-result.md`. Ledger: `docs/work/2026-11-16-streamed-result-delivery.md`.
