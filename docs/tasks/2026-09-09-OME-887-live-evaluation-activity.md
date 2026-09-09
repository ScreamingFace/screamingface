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

PR 877 merged URL4 structured Log emission; PR 884 merged Engine attribute forwarding and safe buffer admission. These provide transport, not production stage activity.

## Remaining delivery

* `OME-1161`: Engine production model-call activity/failure/heartbeat producer.
* `OME-1135`: Client Logs tab, assigned to Keelan at High priority following Khoa's request. Does not wait for scoring refactors.
* `OME-699`: exact Case/operation/member/role enrichment; separate Engine/Client children required when scheduled.
* `OME-932`: cumulative terminal outcomes and Benchmark-native provisional scores. `OME-1097` is Done; `OME-1100`/`OME-1101` remain prerequisites. File a separate Client snapshot-folding child when this stage is scheduled; the Logs tab is not that scoring consumer.

## Boundaries

Existing terminal Case Spans remain baseline liveness. Optional Logs do not create another required pipeline or new public Event kind. No Client URL4 parsing or scoring, inferred phases/ownership, extra paid calls, execution-graph/cache-identity changes. The approved additive URL4 observation change is isolated in OME-1165; no domain-specific URL4 behavior. Cumulative scoring snapshots tolerate log loss; final CandidateResult is authoritative. Logs remain privacy-safe and bounded.

`OME-700` owns optional criterion/judge-pass detail. `OME-901`/`OME-1031` own completed-Report accounting. This parent coordinates outcomes; it is not an implementation unit.

## Major-stage design proposal

The user requested a clean first experience covering case loading, answering, grading, aggregation and final evaluation outcomes, with rich safe facts and a calm default view. The [proposed spec](../spec/2026-09-09-OME-887-evaluation-activity.md), [delivery plan](../plan/2026-09-09-OME-887-evaluation-activity.md) and [design ledger](../work/2026-09-09-OME-887-evaluation-activity-design.md) prepare that decision.

Schema, budgets, coverage and Client support-state behavior remain proposed pending owner review. OME-1161 retains model-call production; a separate Engine stage-instrumentation child is proposed but not yet filed. OME-1135 remains the Client owner. No implementation ticket is expanded or completed by these documents.
