---
id: OME-887
linear_url: https://linear.app/openmined/issue/OME-887
status: Backlog
priority: High
labels: [screamingface-engine, py-screamingface, agentic, deferred]
created: 2026-08-18
closed:
---

# Deliver live Evaluation activity logs and provisional scores

Owner: Keelan Jordan. Milestone: Public Launch.

## Outcome

Help researchers see whether an Evaluation is progressing and what failed. Owner-approved sequencing on 9 September: useful activity/failure logs first; richer semantic attribution and provisional scores later.

## Delivered

`OME-950` and `OME-933` shipped baseline per-Candidate completion, lifecycle, activity, cost, cache and final authoritative score. Before final results the Client truthfully says Not scored yet.

## Remaining delivery

* `OME-1165`: generic URL4 node-scoped structured Log emission, approved 9 September in draft #876.
* `OME-934`: Engine attribute forwarding and safe bridge buffering; depends on OME-1165, silent by default.
* `OME-1161`: Engine production model-call activity/failure/heartbeat producer.
* `OME-1135`: Client Logs tab, assigned to Keelan at High priority following Khoa's request. Does not wait for scoring refactors.
* `OME-699`: exact Case/operation/member/role enrichment; separate Engine/Client children required when scheduled.
* `OME-932`: cumulative terminal outcomes and Benchmark-native provisional scores. `OME-1097` is Done; `OME-1100`/`OME-1101` remain prerequisites. File a separate Client snapshot-folding child when this stage is scheduled; the Logs tab is not that scoring consumer.

## Boundaries

Existing terminal Case Spans remain baseline liveness. Optional Logs do not create another required pipeline or new public Event kind. No Client URL4 parsing or scoring, inferred phases/ownership, extra paid calls, execution-graph/cache-identity changes. The approved additive URL4 observation change is isolated in OME-1165; no domain-specific URL4 behavior. Cumulative scoring snapshots tolerate log loss; final CandidateResult is authoritative. Logs remain privacy-safe and bounded.

`OME-700` owns optional criterion/judge-pass detail. `OME-901`/`OME-1031` own completed-Report accounting. This parent coordinates outcomes; it is not an implementation unit.
