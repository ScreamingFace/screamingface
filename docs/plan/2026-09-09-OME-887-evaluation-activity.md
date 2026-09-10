---
ticket: OME-887
status: proposed
created: 2026-09-09
---

# Deliver major-stage evaluation activity

Implements the proposed [activity spec](../spec/2026-09-09-OME-887-evaluation-activity.md) only after owner approval. This docs-only plan creates no new implementation authorization. The shared clone stays untouched; every implementation unit gets its own issue, mirror, start ledger and worktree from updated origin/main.

## 1. Review the user experience and freeze the contract

Review the example timeline, then the vocabulary/limits, then missing-support behavior, one decision at a time. Confirm that coarse loading/answering/grading/aggregation checkpoints satisfy first-release stage visibility without promising total grading wall time or exact member attribution.

Decisions are reflected in the spec before tickets are changed. Keep the broader outcome in OME-887. Update OME-1161 and OME-1135 to the same approved contract, preserving their Engine/Client separation. File one Engine child for Benchmark stage instrumentation after approval; it must not be folded silently into OME-1161. Existing OME-699/700/932 remain separate and are linked where real dependencies exist.

Inventory the seven registered boards with fixtures and exact hook locations. Verify the hooks execute within observed resolution; document absent/out-of-run coverage. No URL grammar, graph or cache-identity changes to add log points. Source pointers in the spec are investigation anchors, not permission to mechanically wrap every function.

## 2. OME-1161: shared activity behavior and model-call producer

Potential files: new `activity/contract.py`, `activity/scope.py`, `activity/session.py`; existing `runner/connector.py` and the execution wrapper/composition point. Generic `runner/executor.py` gains only safe structured attributes on the existing bridge-loss closing diagnostic; it gains no benchmark-stage knowledge.

Resolve full/off deployment policy in composition and test that Client/run input cannot escalate it. Missing policy is off; invalid configuration fails deployment setup. Public profiles explicitly choose full, private profiles off. Off starts no activity timers and emits no activity records/suppression diagnostics. Existing lifecycle/results/accounting and generic telemetry are not silently reclassified as privacy-safe. Aggregate/limited modes are not implemented.

Add the spec's structured bridge-loss attributes at the existing closing diagnostic, with saturation and run-total semantics. Test nonzero/zero drops, off policy, original lifecycle ordering, no message parsing, and no false promise of live or guaranteed loss notification. This Engine change belongs to OME-1161; merged OME-934 is not reopened.

TDD through the producer interface:

- Verify enabled/disabled operation, immutable scalar output, safe IDs/templates, byte/rate bounds, suppression counters and concurrent sessions. Verify that a run emitting more than 20,000 records within the rate limit continues admitting activity, including later terminal records; no lifetime record cap applies.
- Freeze the bounded admission allocation that prioritizes terminal/retry observations over repetitive heartbeats while preserving the total rate/burst cap. Test saturation and recovery, including later valid records after an oversized record; no optional logging limit may block or fail work.
- Real fake-provider completion, refusal, local transport retry, safe failure, cancellation and heartbeat timing. Use a simulated clock to verify fixed 60-second ticks across multi-day durations, no doubling or catch-up bursts, and immediate observed outcomes independent of timer phase. Preserve the number of calls, retry delays and original errors.
- Scope semantics: nested operations, multiple calls inside one node, expired contexts, async-generator advancement/closure from different tasks, and no retained tasks after run cancellation.
- Integrate the existing connector logging points without retaining two heartbeat loops for the same round trip. Preserve required server diagnostics while publishing the structured version from the same observed facts.
- Carry terminal identity/facts even if the start was suppressed. Exercise pressure via merged OME-934 and verify existing lifecycle/results remain authoritative.

Use an explicit emitter in the activity module; acquire URL4's sink only in permitted producer adapters. Do not change layering gates to permit core imports of Benchmarks or URL4 internals. No second bridge input, registry or generic factory.

Run full Engine gates. Keep the PR draft pending review; a model-only slice is useful but not yet full-stage delivery.

## 3. New Engine child: Benchmark stage producers

After approval, file a single-landing Engine issue under OME-887 with the approved spec as its contract. If board integration proves too large for one focused unit, split by shared hook versus concrete board group; do not create one issue per file.

Start with shared adapters in `benchmarks/evaluation.py` and the existing Candidate Invocation seam in `benchmarks/invocation.py`, before typed outcomes are serialized by `_encode`. Use board-owned loader/task-preparation/check/aggregate hooks only where work actually varies. Reuse existing decoded Candidate/grading outcomes; never build a second scoring path or inspect raw result text solely for instrumentation.

Required proof:

- Coverage matrix for DRACO/DRACO-3PASS, IFEval, HealthBench-Worst30/Professional, GDPVal-Text and MedXpert.
- Loaded count versus selected count remains truthful. Candidate refusal/error can be a returned typed outcome rather than a thrown exception.
- Grading preparation/reduction timing does not claim total judge duration. Sync work is measured without a fake live heartbeat.
- Every affected branch preserves canonical outputs, errors, scorer behavior, request identity and invocation counts.
- No public dataset content, rubric text, private prompt, response, request hash or local path is emitted.

Run full Engine gates in that issue's worktree. No scoring-spine migration is performed as a side effect; unsupported facts remain absent or are explicit dependencies.

## 4. OME-1135: Client contract, projection and Logs tab

Can proceed alongside producer implementation once the shared contract is approved. Keep all changes under `packages/screamingface` with its own issue/worktree/ledger.

- Define the strict activity interpreter over existing generic Log events. Preserve the callback path for newly accepted sequence numbers. Decode the generic structured bridge-loss diagnostic separately; take per-run maxima and never infer counts from body text.
- Bound `_RunState._event_ids` before the Logs projection: proposed 4,096 IDs / 1 MiB window plus constant-size sequence cursor. Review and document the loss of lifetime cross-sequence ID-reuse detection after eviction; preserve replay suppression, gap detection and authoritative event behavior. Exercise oversized tracking entries, duplicates within/outside the window, more than 20,000 events and multi-day synthetic streams. Measure decoder and projection state independently.
- Present the Logs tab as a bounded live view. Do not promise a complete downloadable archive or assume evicted Client history survives in Engine transport storage. The owner wants ephemeral activity: do not add a server-side archive or historical pagination service. Existing temporary transport retention remains unchanged; durable storage/export would need a separate future owner request.
- Build/test a pure bounded reducer for occurrence rows, revision handling, late terminal records, unknown versions, bad shapes, replay and truncation. Active/failure summaries and raw history share the total entry/byte bounds; routine eviction preserves summaries preferentially, but summary overflow is bounded and disclosed.
- Use the owner-approved 180-second threshold since the last fresh update, not operation start. Test a 30-minute call with fresh 60-second heartbeats: it stays active throughout. Test dropped terminal records during an ongoing run: freeze elapsed time and show “No recent update; call may still be running” (or “operation” for other work), never failure. Establish actual fresh-observation evidence before resuming timers; replay receipt, revision advancement and connection heartbeat alone do not qualify. If the current transport cannot prove freshness, keep restored rows unknown and specify any additive Engine evidence with OME-1161 before readiness.
- Exercise simulated multi-day replay/retention gaps and a fresh notebook. Distinguish retained summaries from reconstructed evidence; never fabricate active work or completeness. A local elapsed timer does not refresh last-received activity, and stops on disconnect or terminal/run-end observation.
- Use existing Candidate/run context for grouping. Do not infer Case/member roles or fabricate joins between activity occurrences and node-level accounting.
- Design the actual tab/row/expanded detail states using SFDS app tokens, including empty/unknown support, failure, partial history and ended-without-terminal states. Owner reviews the visual result before readiness.
- Keyboard interaction, focus/scroll stability, bounded rendering, accessible announcements, light/dark modes and high-volume fixtures are acceptance, not polish left for later.
- Decide whether explicit feature advertisement is required. A quiet run is not evidence of missing support. Any contract needed for advertisement gets its own reviewed Engine/Client split before implementation.

Run Client gates and required visual/accessibility verification. No Report format or Client scoring changes.

## 5. End-to-end release evidence

Use the same tiny fake-provider evaluation locally and through the hosted stream path. Observe safe loading, Candidate activity, model waits/failure, grading checkpoints, aggregation and existing final result in the widget while exercising overlap and loss.

One test fixture deliberately fails loading before any paid call; another fails a model call; another fails grading; another fails aggregation. Preserve original error handling and final truth in each. Logging faults or full buffers must not introduce a new failure or paid call.

Mark full-stage delivery only after the declared board matrix and Client experience pass. Capture screenshots/recordings with synthetic public fixtures and no private materials. Durable run-log storage/export, criterion-level detail and provisional scores are not part of this acceptance. The live-view release does not wait for durable export.

## 6. Reconcile existing future work

OME-932 contains historical Engine-only recorder/factory/discovery wording. Before that deferred implementation, propose wording aligned with its approved evaluation lifecycle and canonical scorer requirements; do not silently assert a node log scope can replace evaluation-scoped state. OME-1100/1101's actual state and canonical hooks must be rechecked then.

OME-699 handles exact semantic ownership with Engine/Client children. OME-700 handles criterion/pass detail with volume and identity rules. Their work enriches the same user experience without replacing the base Logs tab.

## Closure discipline

Each implementation finishes with green required checks, independent review, draft-to-ready approval, PR merge, matching task mirror and Linear close evidence. Merging this proposal does not close OME-887 or its delivery children. No merge is requested by this design preparation.

## Privacy follow-up boundary

Aggregate activity is a separately scoped Engine/Client contract if scheduled: run-level counts, duration quantization and safe publication cadence need owner agreement. No per-case records with merely stripped identifiers, no undefined limited mode, and no server-side archive. Full/off is included in OME-1161; aggregate implementation is not a prerequisite.
