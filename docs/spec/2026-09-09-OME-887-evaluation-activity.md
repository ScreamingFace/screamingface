---
ticket: OME-887
status: proposed
created: 2026-09-09
source_revision: b47853ea5dc1938360362fd46edf28b7d951fde1
---

# Evaluation activity that explains the work

## Decision requested

Approve a shared Engine/Client activity contract and the delivery split below. The user requested useful visibility across case loading, answering, grading and aggregation, with detail available without overwhelming the default view. This document is a proposal, not approval to implement its schema, bounds or UI choices. It supplements the approved OME-934 Log transport design; it does not replace scoring, accounting or semantic-attribution contracts.

**Recommendation:** one small Engine activity module, explicit instrumentation in the code that owns the work, and one Client projection into the existing widget. Reuse URL4 Logs and the existing Engine bridge. Do not create a second event bus, parse ordinary logger output, infer phases from URL4 expressions, or move Benchmark logic into the Runner.

## Researcher experience

The Logs tab answers: what is working, what is taking time, what failed, and what evidence is available? Major stages are represented by real observations, not a single global phase indicator. Cases, model calls and grading work can overlap. A message about one operation does not imply other work stopped.

Illustrative timeline, not a promise that every board already exposes these facts:

| Activity | Compact view | Expanded facts |
| --- | --- | --- |
| Case data read and validated | Case data loaded | Benchmark ID; available case count; duration of this loader invocation |
| Candidate execution | Answer produced | Invocation outcome and duration; exact Case ID only if supplied by the owner |
| Model request | Model call still running — 60 s | Model ID; local invocation ID; elapsed request time |
| Grading task preparation | Grading tasks prepared | Exact Case ID where present; number of prepared tasks |
| Grading reduction | Grading result ready | Actual reducer duration; known outcome; no invented total grading duration |
| Final aggregation | Aggregation completed | Selected/result counts actually known at this point; duration |
| Evaluation run terminal | Run finished / failed / stopped | Existing authoritative lifecycle and final Report link |

Fast operations produce one compact row in the default view. Start/update records update that operation's row; failures and long waits remain prominent. Expand a row for facts and received history. Repeated heartbeats update elapsed time rather than append visible rows. Advanced detail may show received records, but it is not a complete execution audit.

The sample intentionally omits an exact global “grading 6/12” progress value: criterion-level progress is OME-700, and provisional Case/scoring snapshots are OME-932. The initial activity view provides coarse stage checkpoints without waiting for either feature.

## Evidence and placement

Inspected at `b47853ea` (PRs 877 and 884 merged):

| Owner | Existing code and available facts | Proposed observation |
| --- | --- | --- |
| Benchmark data loader | `benchmarks/healthbench/runtime.py::_cases` performs preflight, reads baked case data and selects its board cases; other board runtimes own their own loaders | `case_loading` scope around the actual loader/preflight; report loaded/available counts separately from selected evaluation count |
| Candidate adapter | `benchmarks/candidate_adapter.py::_CandidateInvocation.__call__` invokes the Candidate recipe; `benchmarks/invocation.py` preserves typed outcomes | `answering` scope around the real invocation; classify and emit inside `benchmarks/invocation.py` before `_encode`, where the typed outcome exists. The outer adapter receives serialized text; do not reparse it or change the return interface solely for logging |
| Model adapter | `runner/connector.py::_logged_round_trip` already observes response, duration and safe error code; `_in_flight_heartbeat` writes server logs; `_post_completion` owns local retries | `model_call` scope and observed retry updates; reuse facts at source, not logger strings |
| Benchmark grading | Board task-preparation/verdict/case-evaluation handlers, `benchmarks/rubric_check.py::check_surface`, shared `benchmarks/evaluation.py` endpoint adapters | `grading_prepare`, `grading_check` and `grading_reduce` scopes/checkpoints only where the handler owns that work |
| Case outcome | `benchmarks/case_execution.py` preserves Candidate and grading outcomes; existing Client terminal Case-span counting exists | Reuse baseline completion; leave cumulative typed progress to OME-932, rather than introduce a second completion counter |
| Aggregation | `benchmarks/evaluation.py::aggregate_endpoint`, board aggregate functions and `benchmarks/aggregation.py::finalize_candidate_result` | `aggregation` scope at the actual aggregate call; never run the scorer again to log a result |
| Run lifecycle | Existing `Started`, `Result`, `Terminated` events and Client evaluation state | Reuse directly; no optional Log is evidence of final success or final score |

Source logging facts do not imply a structured producer already exists. Built-in deployment currently registers DRACO, DRACO-3PASS, IFEval, HealthBench-Worst30, HealthBench-Professional, GDPVal-Text and MedXpert. Each must have an explicit coverage fixture before “full-stage support” is claimed. A board without model-based grading may still have a local checking/reduction stage.

### Scope limitations that affect truthfulness

- Data preparation while building benchmark images (`benchmarks/prepare.py`) is not a notebook evaluation operation. No attempt to stream old preparation logs into a new evaluation.
- The case loader may load more records than the selected evaluation slice. Call the value `loaded_count` or `available_count`; do not label it “cases to evaluate” unless the selection is actually known.
- Grading commonly spans task construction, judge calls and reduction in different DAG nodes. The whole grading wall duration cannot be measured by timing only the reducer. Coarse observations name the work actually enclosed; full Case/role correlation stays with OME-699.
- Existing grading request-key accounting may revoke ambiguous ownership at final reconciliation. It is not automatically a safe live semantic-identity source. Do not export request keys, hashes of private requests or tentative ownership as certain.
- Synchronous handlers run inline in the current URL4 peer. A start Log can be queued, but cannot be delivered while that thread remains blocked. This logging work must not change execution scheduling or move handlers to threads to make an animation look live. Fast synchronous scopes provide measured completion; a materially slow loader needs its own performance design.
- World setup before observed node resolution has no current node sink. Reuse run lifecycle/error reporting and mark detailed stage coverage unavailable there. Do not manufacture a node span or add a second log ingress in this first release. Detailed setup/teardown activity is a separate, explicitly justified extension if later needed.

## One module earns the shared behavior

Proposed new Engine-owned `activity/` module (exact internal files chosen during implementation):

- `contract.py`: versioned scalar record vocabulary, typed operation facts and fixed message templates; standard library only.
- `scope.py`: operation occurrence IDs, monotonic timing, outcome handling, async heartbeat cleanup and record validation. Captures an explicit emitter supplied by its caller.
- `session.py`: bounded per-run rate/burst accounting, suppression diagnostics and lifetime revocation. No payload storage or second queue.

The small producer interface consists of an operation scope and explicit updates/outcomes. It owns repeated timing, validation, limits and cleanup so they are not copied into every Benchmark. Sync handlers use a synchronous scope without background work; async model calls use the same record builder with an async scope that awaits heartbeat cleanup. A normal Python return alone does not prove a successful Candidate answer: the producer supplies its already-decided completed/refused/failed outcome.

Illustrative interface (names not yet a public API):

```python
async with activity.operation(
    emit=current_log_sink(),
    kind=ActivityKind.MODEL_CALL,
    model_id=observed_model_id,
) as operation:
    choice = await existing_round_trip()
    operation.finish(outcome="completed", finish_reason=choice.finish_reason)
```

Benchmark instrumentation supplies its own literal kind and known facts in the same way. It never hands prompts, responses or raw exception objects to the record builder. A safe fixed failure category is selected at the producer that understands the failure.

**Dependency direction:** `benchmarks/*` and the allowed model adapter import the activity module and pass `current_log_sink()` explicitly. The activity module does not import Benchmarks, URL4, HTTP, the Client or a tracing backend. It accepts the callable; it does not discover or inspect an ExecutionContext. Generic `runner/executor.py` continues to forward opaque Log attributes and enforce bridge capacity without stage knowledge.

Run budget lifetime belongs in a neutral execution wrapper at composition, using the existing `OperationCapturingExecutor` context discipline: bind shared state around each inner advancement/close, never hold a ContextVar token across an outward async-generator yield. Reuse that wrapper for the small session lifetime if it stays cohesive; do not add a chain of pass-through decorators or a new factory/registry. The scope captures the node emitter once so its terminal observation cannot accidentally attach to a nested child. State is revoked on run exit; it is not a process-global current run.

Optional instrumentation must remain opt-in to a valid active sink/session, fail-open for ordinary internal instrumentation faults, and inert otherwise. No timer or producer bookkeeping is started when disabled. Failures in the actual work, including cancellation/process-control signals, propagate unchanged. A logging helper must never retry the work it observes.

## Deployment-owned activity policy

OME-1161 supplies a deployment-owned `full` / `off` policy, fixed for a run and enforced before optional activity emission, including suppression diagnostics. The Client and run inputs cannot escalate it. Public deployments may explicitly select `full`; private/enclave deployment profiles explicitly select `off`. Missing policy resolves to `off`; invalid values are rejected during deployment configuration, never silently upgraded. No provider calls, heartbeat tasks or activity bookkeeping are started merely to report disabled activity.

- `full`: the existing safe v1 contract, still subject to allowlists and rolling bounds. “Full” never permits prompts, answers, rubric text or raw exceptions.
- `off`: no v1 activity records or activity-specific suppression diagnostics. Preserve existing authoritative lifecycle/results/accounting and existing transport behavior. This is not a claim that the whole deployment emits only lifecycle events: existing generic Logs, spans and other telemetry need their own privacy review. Operator/server diagnostics are not made private by hiding the widget.
- `aggregate`: follow-up only; unsupported in the first implementation. It requires genuine run-level observations, explicit count semantics and duration buckets, with no per-case occurrence records. Removing `case_id` from per-case records is insufficient. “Limited” is not a supported alias until its allowlist is defined.

The policy is ScreamingFace-owned and the shared activity module receives the resolved setting through composition. URL4 remains generic. Do not infer deployment tier from data, user labels or model identifiers. No new archive or persistent telemetry store is introduced. Client silence does not establish that policy is `off`; display a disabled state only when policy information is explicitly available through an approved contract.

## Proposed v1 wire contract

Use the existing Log event with `body` generated from fixed safe templates and these flat attributes. No new CloudEvent type, URL4 grammar, graph wrapper or cache-identity change.

| Attribute | Meaning |
| --- | --- |
| `sf.activity.schema` | Exact string `screamingface.activity.v1` |
| `sf.activity.kind` | `case_loading`, `answering`, `model_call`, `grading_prepare`, `grading_check`, `grading_reduce`, or `aggregation` |
| `sf.activity.state` | `started`, `running`, `retrying`, `completed`, `failed`, `cancelled`, or `refused`; legal transitions validated per kind |
| `sf.activity.id` | Random opaque occurrence ID generated on entry; local to this run, unrelated to request contents |
| `sf.activity.revision` | Increasing integer per occurrence, for updates/replay; gaps mean incomplete history, not failed work |
| `sf.activity.elapsed_ms` | Finite nonnegative elapsed time of this explicitly enclosed operation |
| `sf.activity.parent_id` | Optional known enclosing activity occurrence; absence if there is no live explicit scope; not a guessed DAG/Case parent |
| `sf.activity.model_id`, `sf.activity.provider` | Optional observed safe identifiers; do not derive provider from a model name |
| `sf.activity.benchmark_id`, `sf.activity.case_id` | Optional exact public IDs available to that producer; absence otherwise; does not certify complete cross-stage ownership |
| `sf.activity.attempt` | Optional local adapter attempt number starting at 1, only where its retry loop is actually observed |
| `sf.activity.retry_delay_ms` | Optional actual selected local retry delay; no additional retry or provider interaction |
| `sf.activity.finish_reason` | Optional documented allowlisted reason from the response |
| `sf.activity.failure_code` | Optional fixed allowlisted safe code/category; never arbitrary exception text |
| `sf.activity.loaded_count`, `sf.activity.selected_count`, `sf.activity.result_count`, `sf.activity.prepared_task_count` | Optional nonnegative integers, each only when its distinct meaning is known; prepared tasks count actual constructed tasks, not completed criteria |

Optional suppression snapshot attributes are `sf.activity.suppressed.invalid`, `sf.activity.suppressed.oversize` and `sf.activity.suppressed.rate`. Each is a nonnegative integer, saturating at 9,007,199,254,740,991 (the JavaScript safe-integer maximum). Emit all three together as a cumulative run-local snapshot on the next admitted record after a counter changes. Consumers take per-reason maxima, never sum snapshots across records or replay. These counters cover producer suppression only, not sink or bridge loss.

Only `model_call` may emit `retrying`; only `model_call` and `answering` may emit `refused`. All kinds may emit start, measured completion or safe failure/cancellation. `running` is restricted to an active async scope; terminal emission happens at most once. Case IDs preserve their existing public string/integer type; numeric facts reject booleans, negative and nonfinite values.

Terminal records repeat identifying facts and elapsed time, so they remain intelligible if the start was dropped. A refusal is distinct from infrastructure failure; neither means an overall evaluation failed. Nested tool/model round trips each have an occurrence; a URL4-level retry creates another occurrence unless its owner supplies a trustworthy relation. Do not call the local transport attempt count a global provider retry count. Model-call duration measures the Engine operation, including local waiting/retries, not necessarily provider compute time.

Identifiers must come from the configured public model/Benchmark catalog or the owning public Case contract; arbitrary URLs, user labels, filesystem paths and private request hashes are not safe identifiers merely because they are short strings. Unknown failure/finish categories remain absent or map to a fixed generic category.

Body text is explanatory. Consumers branch only on versioned structured fields. Unknown versions remain generic Logs, marked unsupported for structured grouping. Recognized malformed activity records do not break execution or existing `on_event` delivery; the activity projection rejects their typed interpretation and increments a bounded invalid-record count. IDs are correlation labels, not authority for billing, scoring or Case completion.

Use existing spans/usage/cache evidence for those details in the widget. Do not copy token/cost totals into every activity update. Do not join one model occurrence to a whole node's aggregate usage unless identity proves that relationship; display node-scoped metrics separately when that is all we have. Do not copy raw existing Log bodies into the safe activity tab by default.

## Proposed limits and loss semantics

These values require owner approval; they make implementation and load tests concrete:

- Activity Log body plus attributes: at most 4 KiB in UTF-8 JSON; body at most 256 characters; identifiers at most 128 characters. Reject oversized/invalid records whole; no payload in diagnostics.
- Async heartbeat interval: fixed 60 s while an eligible async operation is active, with no exponential backoff. This intentionally changes the existing connector heartbeat policy; use one owned heartbeat loop, not an additional timer alongside the old loop. Heartbeats mean the Engine operation is still awaiting completion, not proof that the provider is making progress. Completion, failure, cancellation and observed retry updates emit when observed without waiting for a heartbeat. Delayed event-loop scheduling or rate/delivery suppression can delay or drop a heartbeat; 60 s is the intended emission cadence, not a delivery guarantee. Do not replay missed timer ticks in a catch-up burst. Cancellation cancels and awaits owned heartbeat tasks before terminal emission/scope exit; instrumentation cleanup cannot replace the original error.
- Per-run activity rate: token bucket at 100 records/s, burst 200. There is no lifetime limit on the number of emitted activity records; long runs remain eligible to emit throughout execution. Each operation has a constant-size current record, not retained history. Rate suppression leaves execution unchanged and does not cap authoritative spans/results. Tokens replenish continuously; a temporary burst does not disable later logging. Sustained overload can continue suppressing records. Favor terminal outcomes (including failures) and observed retries over repetitive running updates using bounded admission capacity within the same total rate/burst limits; no priority class bypasses size validation, bridge bounds or evaluation cancellation. The allocation must be specified and tested in OME-1161 before implementation readiness; do not add a waiting queue or delay the work to obtain a token. A total emission limit may be reconsidered separately if operational evidence warrants it.
- Producer suppression counters: fixed reasons only (`invalid`, `oversize`, `rate`), the saturation and snapshot fields specified above, no IDs/payload retention. Include snapshot bytes in the 4 KiB limit; reserve space before admission, with no recursive diagnostic emissions. After rate recovery, the next accepted record carries changed cumulative totals. No extra “guaranteed final Log” is promised under delivery pressure. Client silence cannot establish completeness.
- Structured bridge-loss evidence: OME-1161 extends the existing run-scoped closing Log in `runner/executor.py::_closing_logs` with `sf.telemetry.schema="screamingface.telemetry.v1"`, `sf.telemetry.loss.scope="engine_bridge_logs"`, and `sf.telemetry.loss.dropped_total` (nonnegative integer, saturating at 9,007,199,254,740,991). This is a cumulative count of all Logs dropped by this Engine bridge, not solely v1 activity. No IDs, payloads, node timing or private content. Preserve the explanatory body, but OME-1135 interprets only the attributes and takes the maximum snapshot, never sums replayed totals. Emit only when nonzero, using the existing closing diagnostic path and lifecycle ordering; no new event kind or second ingress. The first implementation exposes this at closure, not as guaranteed live loss notifications. Its absence does not certify loss-free delivery. Under `off`, this change adds no activity-facing diagnostic; any pre-existing generic closing diagnostic remains governed by the existing telemetry policy. URL4 process-wide sink counters remain separate and are never added to run totals.
- Client: retain at most 2,000 received activity records and an 8 MiB serialized-record budget per evaluation, applying the stricter cap. Keep rolling received history plus compact summaries of active operations and important failures. Bound their combined retained records/summaries to 2,000 entries and their combined serialized data to 8 MiB, including indexes with bounded cardinality; these are shared ceilings, not fresh budgets for each view. Prefer eviction of old routine history before active/failure summaries. If summaries alone reach capacity, evict the oldest summaries too and disclose that some operations/failures are no longer shown. No permanently pinned unbounded map. Count local truncation without retaining discarded IDs; keep existing authoritative evaluation state separate. Refresh visible state at most 5 times/s; delivery to existing event callbacks keeps its existing semantics.

### Bound decoding before projection

OME-1135 must replace `_engine/contract.py::_RunState._event_ids`, which currently retains every sequenced event ID, before claiming bounded activity memory. Preserve the scalar per-run sequence cursor for replay rejection (`sequence <= last_sequence`) and existing gap/run/source validation. Proposed collision-check window: at most 4,096 recent accepted IDs and 1 MiB of UTF-8 ID data, evicting oldest entries under either limit. IDs too large for this auxiliary window are not retained; do not reject otherwise valid evaluation events solely because tracking capacity is full. Apply this to all accepted sequenced event kinds, not only activity. Auxiliary collection cardinality is bounded separately from the widget's 2,000-entry / 8 MiB projection budget.

This deliberately bounds cross-sequence ID-reuse detection to retained IDs. It does not guarantee lifetime uniqueness validation after eviction. Replay at already-accepted sequence numbers is still suppressed without retaining their IDs, and each newly accepted sequence follows the existing callback path. Reused IDs at new sequence numbers outside the window may no longer be detected; this compatibility tradeoff requires explicit review in the Client contract and regression tests before implementation readiness. Do not claim lifetime exactly-once delivery by event ID. No approximate membership filter that can falsely discard authoritative events. Test multi-day streams through the actual decoder plus projection, including authoritative events, not only reducer fixtures.

Hitting any activity-specific size, admission or display limit suppresses that optional record or evicts retained telemetry; it must not raise an evaluation error, block the work, retry a model request or change its result. An oversized record does not poison later valid records. Ordinary instrumentation faults fail open; original work errors and cancellation still propagate. This is a requirement to verify, not a claim that all existing transport/infrastructure failures are harmless.

Detail controls filter what is displayed, not what work is executed. This is bounded optional telemetry, not “everything forever” or a guaranteed downloadable audit. At run termination, incomplete operations become “run ended; operation outcome not observed,” not fabricated successes/failures. A later valid terminal record can complete a row whose start was lost. Never increment authoritative case counts or compute scores from these messages.

## Live view and durable export boundary

Owner direction: activity is ephemeral. Do not add a server-side activity archive, persistence layer or historical pagination service. The Client memory limits bound the recent live view; older entries may be discarded and unavailable later. This does not stop new activity emission. Existing temporary transport retention remains unchanged.

The Logs tab is a bounded live activity view. Its rolling history is not a durable run-log archive, and removing an old row does not imply that an exportable copy exists elsewhere. The existing Engine event streams have their own retention and cleanup policies; they are temporary delivery/replay storage, not a promised complete archive. This proposal changes none of those existing settings.

Durable run-log storage and export are outside this design and are not requested delivery work or prerequisites. If the owner later requests them, a separate proposal must define where received events are persisted, retention and retrieval/export behavior, and how known losses are disclosed. It must not describe an export as complete when records were suppressed before delivery or lost in buffering. The Logs tab must not promise a complete downloadable history until that contract is implemented.

## Operation freshness

An operation row represents the last observed state, not proof the work is still active. A fixed heartbeat cadence is not a completion guarantee. Proposed freshness timeout: 180 seconds (three intended heartbeat intervals), pending owner confirmation. On timeout without a demonstrably fresh update, change an unterminated row to “outcome unknown — no recent update” and stop extrapolating elapsed time. Preserve the last measured elapsed value and observation time; do not infer failure, completion, provider progress or a cancellation request. Apply this also to synchronous start records, which have no guaranteed intermediate heartbeat.

A later valid terminal record resolves an unknown row even if historical. A new nonterminal observation can restore an active display only with evidence that it is fresh; a higher revision or recent receipt time alone is insufficient. Replay never refreshes the deadline merely because it arrived now. Stop timers on disconnect; keep them stopped through replay.

OME-1135 must distinguish historical delivery from fresh observation before enabling resumed timers. Use an explicit transport live/replay boundary if available, together with observation-age evidence; do not invent such a boundary from silence, a sequence gap closing, or a connection-level heartbeat. Where timestamp evidence is used, it must describe producer observation time rather than delayed relay receipt and have a documented clock-skew allowance. This requirement applies to delayed ordinary delivery as well as reconnect replay. The current contract does not yet establish that observation-age evidence: until an approved mechanism exists, replayed/restored rows remain “outcome unknown” instead of resuming extrapolation. Any required additive Engine observation timestamp or transport signal must be specified with OME-1161 before consumer implementation readiness, without a new store or URL4 domain behavior.

Tests must cover a dropped terminal during an otherwise healthy days-long run, stale replay arriving just after reconnect, repeated duplicate heartbeats, disconnect/reconnect without fresh evidence, late terminals, fresh updates after timeout, unavailable/skewed clocks and ordinary work that outlives the freshness window. None changes the actual evaluation.

## Client projection and coverage honesty

OME-1135 adds a pure bounded activity reducer and presentation to the existing widget. Decoder/projection tests can be written before visual implementation. Preserve existing Candidate progress, callbacks, cost view, final Report and error behavior.

- Display elapsed time from the last measured operation elapsed value plus local monotonic time while observation remains fresh under the policy above; stop advancing on terminal observation, known run end or disconnection. Reconnection alone does not restart a timer from a stale summary; require fresh evidence for that operation under the policy above. Label it as elapsed time, not provider progress. Show last received activity separately using local receipt time; a rendered timer tick must never reset that freshness marker or generate a synthetic Log.
- Reconnect through the existing stream resume/replay contract. Fold replayed records idempotently by occurrence/revision; preserve bounded summaries only when the same Client instance still holds them. If retention or the reconnect response exposes a gap, mark history partial. A newly opened notebook must not claim to reconstruct earlier active operations or failures from silence; show only recovered evidence and existing authoritative run state. Full reconstruction after retention expiry is not promised; do not add storage or snapshots to achieve it within this work. Simulated multi-day reconnect tests must exercise retention eviction, not just short disconnects.
- Default view: recent stage completions, active long waits, retries and failures; routine start rows compact/update in place. Expand for safe facts and available history; optional advanced received-record view.
- Group primarily by the existing Candidate/run context. Group within it by activity occurrence; Case/member grouping only with exact typed provenance. Never infer answering/grading from a model, endpoint name or message text.
- Before the first recognized record: “No structured activity received yet.” Silence is not proof of either unsupported capability or idle work. At run end with no records: “No structured activity received for this run.” Say “unsupported” only with explicit negotiated/deployment evidence. Reliable feature advertisement remains a focused design decision for OME-1135 if that stronger status is required; do not invent capability by timing out.
- Surface partial history when producer suppression, bridge loss or local truncation is known. No claim of complete history when those signals themselves may have been lost.
- App-register SFDS styling, accessible keyboard tabs/expansion, preserved focus and scroll position, and polite bounded announcements. Do not announce every heartbeat to screen readers. Visual spec/owner review stays in OME-1135; this is its behavior contract, not a finished mockup.

## Delivery boundaries and review gates

1. This docs-only proposal is owned by the existing OME-887 epic; no product implementation is authorized by preparing it.
2. OME-1161 remains the Engine activity module plus model-call producer, with its schema/limits approved before code. It must not silently become the whole Benchmark instrumentation ticket.
3. Propose a separate Engine child under OME-887 for Benchmark loader/answering/grading/aggregation instrumentation. Reuse shared endpoint adapters where the facts are available, with board-local hooks only for real variations. File after scope approval; do not create a mega-ticket spanning Engine and Client.
4. OME-1135 owns independent strict Client activity decoding, bounded projection and Logs-tab presentation. Consumer and producers can proceed in parallel after the schema freezes. A first model-only slice may be tested but is not called full-stage delivery.
5. OME-699 owns stable semantic operation/member/role enrichment and its Engine/Client children. Local explicit IDs in these records do not replace its contract. A grouping requirement that needs it becomes an explicit dependency, not a heuristic.
6. OME-700 remains optional criterion/judge-pass progress. OME-932 remains cumulative terminal Case outcomes and Benchmark-native provisional scores; do not recompute grades in the activity module. Its older Engine-only factory/discovery wording needs a separate reconciliation before implementation, not revival of PR 692.
7. Generic source/collection event proposals OME-558/562 remain separate. This design does not require them or another URL4 change. If actual integration needs one, stop and scope the missing capability explicitly.

## Acceptance scenarios

- Every registered board has a tiny fake/local fixture that exercises its applicable loading, answering, grading and aggregation hooks, with exact coverage declared. Failure before/during each hook preserves the original result/error.
- Model fixture covers completion, refusal, safe failure, observed transport retry, async long wait and cancellation. No provider/Gateway behavior is inferred from a timeout alone.
- Concurrent runs, nested Candidate work and multiple calls in one node keep occurrence/parent identity correct. A sibling or a later run cannot reuse an expired sink/session; ambiguity remains absent.
- Missing sink/session creates no tasks, subscriptions or I/O. Instrumentation errors cannot change results, calls made, retry counts, graph/cache identity, scores or report serialization.
- Sync handler tests explicitly verify eventual start/completion delivery, without claiming a heartbeat while the event loop is blocked.
- Fake local and hosted streams deliver the same versioned records through real URL4 → Engine bridge → wire serialization → independent Client decoding/projection. No Engine filesystem access from the notebook.
- Pressure tests exercise record size, rates, long runs, dropped starts/terminals, replay, out-of-order receipt and UI truncation; final results remain authoritative. Event sequence orders transport receipt, not a fabricated global stage order.
- Existing tests remain unchanged. Each implementation runs its stack gates; Client work includes accessibility and both themes under the established brand rules.

## Owner decisions to confirm before implementation

- Is the proposed coarse major-stage timeline sufficient for the first full-stage release, with exact grading-wall-time/member grouping and criterion counts later?
- Approve or adjust the proposed v1 vocabulary and concrete capture/retention limits.
- Accept honest unknown/no-records capability states initially, or separately design explicit capability advertisement before the Logs tab ships?

Discuss these one at a time. This proposal does not declare them settled.
