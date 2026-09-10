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

## Owner refinement — 10 September 2026

Removed the proposed lifetime activity-record cap and its suppression counter at the owner’s request. Rate, record-size, bridge and Client-history bounds remain proposed as before. See the [refinement ledger](../work/2026-09-10-OME-887-remove-activity-total-cap.md).

Clarified at the owner’s request that the Logs tab is a bounded live view. Durable run-log storage/export and its retention/loss contract remain separate delivery work; existing Engine retention is unchanged. See the [boundary ledger](../work/2026-09-10-OME-887-live-view-export-boundary.md).

Owner-approved refinement: limits recover or roll forward without blocking evaluation; prioritize outcomes over repetitive updates within bounded capacity, preserve bounded active/failure summaries, and disclose reconnect gaps. Use fixed 60-second async heartbeats (superseding the earlier backoff recommendation), with elapsed time distinct from received activity. See the [long-run refinement ledger](../work/2026-09-10-OME-887-rolling-activity-limits.md). Product implementation remains separate.

Latest owner clarification: activity is ephemeral; no new server-side archive or historical retrieval is wanted. Existing temporary transport retention remains unchanged. Discarded Client history need not be recoverable, and durable storage/export is not requested follow-up work.

## Deployment policy and review follow-up

PR #885 now proposes full/off deployment enforcement in OME-1161, with genuine aggregate mode deferred. OME-1135 owns bounded decoder ID tracking as well as bounded projection; the bounded ID-reuse detection tradeoff is explicit. OME-1161 adds structured run-scoped bridge-loss attributes to the existing closing diagnostic. Owner confirmed the 180-second threshold since the last fresh update, not operation start. Stale model rows say “No recent update; call may still be running”; fresh 60-second heartbeats keep long calls active. Replay alone cannot restart timers. See the [review ledger](../work/2026-09-10-OME-887-policy-and-review-findings.md).

The [freshness confirmation ledger](../work/2026-09-10-OME-887-confirm-freshness.md) records this approval; other implementation-readiness gates remain unchanged.
