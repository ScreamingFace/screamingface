---
ticket: OME-901
stack: repo
status: done
started: 2026-08-27
finished: 2026-08-27
---

# OME-901 — Audit runtime-accounting lineage

## Intent

Trace cost, token, timing, cache, execution-identity, operation-identity, benchmark-role, and
case-identity facts from their authoritative producer through URL4, ScreamingFace Engine,
benchmark envelopes, the Python Client, the final Report, and the UI. The audit must distinguish
facts that are produced, forwarded, aggregated, exposed live, retained, derivable, ambiguous, or
discarded before any implementation design is proposed.

## Planned changes

- Record the evidence-backed lineage matrix in this ledger.
- Add characterization evidence only when static source inspection cannot prove a seam.
- Do not modify production code or Linear descriptions.

## Test plan

- Characterize a solo model call.
- Characterize a Fusion with distinct model routes.
- Characterize identical model routes reused across operations.
- Trace synthesis and benchmark grading independently.
- Trace concurrent cases, retries/tool loops, cache hits, failures, and refusals.
- Verify live Client Events separately from `_RunOutcome`, `Report`, and UI retention.

## Acceptance

- Every relevant field has an authoritative source location and every handoff is cited.
- Every field is classified as exact, derivable, ambiguous, aggregated, or lost at each seam.
- The smallest justified landing set is stated without assuming a new URL4 or Engine capability.

## Evidence matrix

### Classification vocabulary

- **P** — produced at this layer; **F** — forwarded without changing its meaning; **Σ** —
  aggregated; **L** — exposed on the live Client event callback; **R** — retained after the run in
  `_RunOutcome`, `Report`, or final UI; **D** — derivable from other retained facts; **A** —
  ambiguous/incomplete despite having a value; **X** — discarded before this layer; **U** — not
  produced for this execution path.
- **E** means exact relative to the producer evidence and its declared contract. It does not mean
  the provider supplied evidence it never supplied. In particular, OpenRouter credits are treated
  as USD 1:1 by an explicit owner decision which the Engine says it cannot verify
  (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:39-48`).
- “Retained” means reachable from the returned/saved `Report`, not merely observable while the
  callback is running. A public `Event` is therefore **L** but not automatically **R**.

### Producer availability (before any benchmark attribution)

| Execution/provider shape | What the authoritative Gateway currently produces | Classification |
|---|---|---|
| Non-streaming OpenRouter | One bounded record per observed provider send, including token evidence, provider/request/served-model identity, provider response id, outcome, HTTP status, body-complete latency, redirect count, direct OpenRouter-credit amount/source, and extension facts. Raw JSON `Decimal`/`int` is required for exact direct cost; converted monetary floats are rejected (`apps/aigateway/src/aigateway/plugins/openrouter_provider/usage_accounting.py:69-119`, `:162-195`; canonical record shape at `apps/aigateway/src/aigateway/plugins/taxonomy/types.py:414-499`). | **P/E**, subject to the response bounds below. |
| Non-streaming Anthropic | Inclusive input/output totals, uncached/cache-read/cache-write/TTL subsets, provider-reported thinking tokens when available, service tier, served model/id, and bounded tool-use facts. Anthropic has no response-authored direct cost, so cost is explicitly `absent` (`apps/aigateway/src/aigateway/plugins/anthropic_provider/usage_accounting.py:72-158`, `:181-216`). | Tokens/identity **P/E** when reported; cost **U**. |
| Direct OpenAI and every provider other than Anthropic/OpenRouter | The default strategy is unsupported; only Anthropic and OpenRouter contribute a strategy (`apps/aigateway/src/aigateway/plugins/taxonomy/session.py:76-90`; contribution search is exhausted by `apps/aigateway/src/aigateway/plugins/anthropic_provider/plugin.py:250-274` and `apps/aigateway/src/aigateway/plugins/openrouter_provider/plugin.py:475-501`). Direct OpenAI explicitly contributes only a cache-reference no-op, not an accounting strategy (`apps/aigateway/src/aigateway/plugins/openai_provider/plugin.py:153-163`). | Attempt accounting/cost/cache token classes **U**. The Engine may still use the final converted response's input/output totals as an unpriced fallback. |
| Streaming chat | The chat route bypasses `begin_accounting` for streaming before the cache stage (`apps/aigateway/src/aigateway/routes/chat.py:282-289`), and early/normal streaming bypass is pinned by `apps/aigateway/tests/unit/usage_accounting/test_chat_route_accounting.py:287-301`, `:389-423`. | Gateway accounting **U**. Current benchmark connector calls are non-streaming. |
| Gateway response-cache hit | No provider attempt exists. `_aigw.usage_accounting.attempts=[]`, `observed_new_attempts=0`; any replayed usage is a historical final-response reference with `incurred_in_current_request=false`, never current spend or avoided-cost proof (`apps/aigateway/src/aigateway/routes/chat.py:330-351`; `apps/aigateway/src/aigateway/plugins/taxonomy/types.py:502-533`; test `apps/aigateway/tests/unit/usage_accounting/test_handoff_contract.py:141-169`). | Current provider consumption/cost **P/E = 0**; historical token evidence **P/R-at-Gateway only**, not current accounting. |

Accounting is opened per non-streaming Gateway request with a new `gateway_call_id` and a
request-local collector (`apps/aigateway/src/aigateway/plugins/taxonomy/session.py:93-141`). Every
local provider-send admission gets a unique attempt id, monotonic sequence, dispatch index,
attempt index, and monotonic start; redirects are folded into the same attempt
(`apps/aigateway/src/aigateway/plugins/taxonomy/collector.py:111-208`). Completion records body-read
latency, status/outcome, and raw evidence (`collector.py:228-262`); conversion failures retain the
already-billed attempt (`collector.py:293-365`). The HTTP hooks observe each local send and read its
body before completion (`apps/aigateway/src/aigateway/core/usage_accounting/hooks.py:166-236`).

The handoff is deliberately bounded: at most 64 attempts are rendered; extensions are shed first,
then tail attempts, and any shedding marks capture/direct-cost partial
(`apps/aigateway/src/aigateway/plugins/taxonomy/render.py:21-24`, `:97-117`, `:138-193`). Cost
subtotals are emitted only when capture is complete and no attempt was omitted
(`render.py:71-90`, `:147-190`). Thus **E** below always means no partial/omitted producer evidence.

### Field-by-field lineage

| Field or fact | AI Gateway → Engine connector | URL4 observation → Engine wire | Client live event | `_RunOutcome` → `Report` → UI | Final classification |
|---|---|---|---|---|---|
| Provider-authored direct cost | Gateway **P/E** per attempt as status + canonical amount + unit + source, and **Σ/E** only across identical unit/source groups (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:250-309`; `apps/aigateway/src/aigateway/plugins/taxonomy/render.py:30-55`). Engine accepts only one complete OpenRouter-credit subtotal and converts it 1:1 to `Decimal` USD; cache hit becomes exact zero; every other shape becomes `None` (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:135-187`). Unit, direct-cost status/source, per-attempt amounts, and provider cost extensions are **X** at this handoff. | One USD/`None` value is **F** per Gateway round trip on `url4.observe.Usage`; one node span and the run subtree **Σ** all such values, with any unknown poisoning cost to `unpriced` (`packages/url4/src/url4/observe.py:67-99`; `apps/screamingface-engine/src/screamingface_engine/runner/executor.py:415-471`, `:513-535`, `:581-600`). Wire carries authoritative `total_usd`; all class-specific USD components remain zero/absent (`packages/url4/src/url4/streaming/protocol/taxonomy.py:36-72`). | `sf.events.Usage(scope=self|subtree)` **L** exposes provider, model, pricing version, trace envelope, and total USD/`None` (`packages/screamingface/src/screamingface/events.py:168-190`; decoder `packages/screamingface/src/screamingface/_engine/contract.py:358-430`). | `_RunOutcome.root_usage` retains only the root subtree `sf.Usage`, dropping provider/model/pricing/span (`packages/screamingface/src/screamingface/_core/ports.py:32-48`; `packages/screamingface/src/screamingface/_engine/contract.py:175-179`, `:223-233`). `CandidateResult.usage` **R** copies it; `Report.usage` **Σ** poisons cost if any candidate is unknown (`packages/screamingface/src/screamingface/_evaluation/results.py:111-151`; `packages/screamingface/src/screamingface/report.py:331-346`, `:533-555`). Final UI shows candidate/report total or dash (`packages/screamingface/src/screamingface/_ui/report_view.py:236-258`, `:262-297`). | Candidate/run total **R/E** only when every observed call is priced or a proven hit. Per-attempt/per-operation/per-case/per-role cost **X**. Any unpriced call makes final total unknown, correctly; live UI has a separate caveat below. |
| Inclusive input tokens | Gateway **P/E** per rendered attempt with evidence status/source (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:118-145`, `:163-228`). Engine **Σ** across every rendered attempt, failures included (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:190-250`; test `apps/screamingface-engine/tests/unit/test_accounting.py:246-258`). If any attempt is unknown, `_report_usage` falls back to the final converted response's `prompt_tokens`, then to zero (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:323-332`, `:401-419`). It does not inspect `capture_status`/`omitted_attempts`. | URL4 requires an integer and **F/Σ** it per round trip, span, and subtree (`packages/url4/src/url4/dag/node.py:357-396`; `apps/screamingface-engine/src/screamingface_engine/runner/executor.py:415-471`, `:581-600`). | Span input and self/subtree Usage input are **L** (`packages/screamingface/src/screamingface/events.py:114-165`, `:168-190`). | Root value is **R** in Candidate/Report and final UI totals input+output (`packages/screamingface/src/screamingface/_report_primitives.py:16-58`; `packages/screamingface/src/screamingface/_ui/report_view.py:860-871`). | **E** only if every billed attempt was rendered and reported input. Otherwise **A**: terminal-only fallback or zero can undercount retries while looking exact downstream. |
| Inclusive output tokens | Same path and conditions as input; Gateway output has total + reasoning subset (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:148-160`). Connector falls back to final `completion_tokens`, then zero (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:409-414`). | Same integer **F/Σ** path. | **L** on Span and Usage. | **R** in Candidate/Report/UI. | **E** only with complete rendered attempt evidence; otherwise **A** for the same terminal-only/zero fallback. |
| Uncached input | Gateway **P/E** when the provider can distinguish it (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:118-145`; OpenRouter derivation `apps/aigateway/src/aigateway/plugins/openrouter_provider/usage_accounting.py:60-95`; Anthropic mapping `apps/aigateway/src/aigateway/plugins/anthropic_provider/usage_accounting.py:72-147`). | `CallAccounting` has no field for it (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:60-78`). | **X**. | **X**. | Lost at Gateway → Engine. |
| Cache-read tokens | Gateway **P/E** per attempt when reported. Engine **Σ** rendered attempts and poisons the Gateway-call value on unknown (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:190-250`). | URL4 preserves `int|None`, but Engine wire converts per-span unknown to zero; run aggregation adds reported counts and ignores unknown because the wire cannot express optionality (`packages/url4/src/url4/observe.py:81-99`; `apps/screamingface-engine/src/screamingface_engine/runner/executor.py:231-247`, `:315-337`, `:415-471`, `:581-600`; wire integer default at `packages/url4/src/url4/streaming/protocol/taxonomy.py:19-23`). | Priced frames expose the integer, including flattened/partial zero. On `pricing_version="unpriced"`, Client deliberately converts the whole class to `None`, even if the wire carried known counts (`packages/screamingface/src/screamingface/_engine/contract.py:393-421`; pinned by `packages/screamingface/tests/test_engine_cost_breakdown_warning.py:135-147`). | Root **R** as integer only for priced runs; **R=None** for unpriced runs. Final Report UI does not display cache-token classes. | **A** when priced unless all calls reported the class; **X-as-None** when any cost is unpriced. Exact zero on a proven response-cache hit. |
| Cache-creation/write tokens | Same path as cache read; Gateway `cache_write` is renamed `cache_creation` by the connector (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:190-204`). | Same unknown→zero wire flattening and known-subtotal run sum. | Same priced integer / unpriced `None`. | **R** in Report JSON, not final UI. | Same **E/A/X** conditions as cache read. |
| Cache-write TTL breakdown | Gateway **P/E** as `(ttl_seconds,tokens)` rows and validates their sum (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:105-145`, `:207-216`; Anthropic producer `apps/aigateway/src/aigateway/plugins/anthropic_provider/usage_accounting.py:55-69`). | No Engine/URL4 field. | **X**. | **X**. | Lost at Gateway → Engine. |
| Reasoning tokens | Gateway **P/E** only when provider raw evidence is authoritative; Anthropic deliberately refuses LiteLLM's converted estimate (`apps/aigateway/src/aigateway/plugins/anthropic_provider/usage_accounting.py:72-147`). Connector **Σ** rendered attempts with unknown poison. | Same optional-class unknown→zero wire flattening and run known-subtotal aggregation as cache tokens. | Same priced integer / unpriced `None`. | **R** in Report JSON, not final UI. | **E** only with complete reporting and priced run; otherwise **A** or **X-as-None**. |
| Requested model | Gateway **P/E** per attempt (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:449-499`), but `read_aigw` does not retain that field. Engine independently knows the decoded route model and reports it (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:560-581`, `:401-419`). | URL4 Usage `model` is explicitly requested model; Span preserves it (`packages/url4/src/url4/observe.py:67-80`; wire `packages/url4/src/url4/streaming/protocol/signals.py:62-71`). CostUsageData's `model` also contains this requested model despite its `gen_ai.response.model` serialization alias (`apps/screamingface-engine/src/screamingface_engine/runner/executor.py:516-525`). | **L/E** as `Span.request_model`; **L** as `Usage.model`. | Per-call value **X**. `CandidateResult.models` **R** is the compile-time route set, not a runtime-call ledger (`packages/screamingface/src/screamingface/report.py:156-175`, `:257-281`). | Runtime requested model **L/E**, not **R**; static candidate model set **R/E**. |
| Served/response model | Gateway **P/E** when provider says it; Engine chooses the terminal rendered attempt (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:207-250`). A bounded response that omits the real tail makes that “terminal” selection partial. | URL4 preserves `None` as “provider did not say” (`packages/url4/src/url4/observe.py:73-99`), but Engine Span deliberately echoes the requested model when response model is absent (`apps/screamingface-engine/src/screamingface_engine/runner/executor.py:485-507`). A span containing several calls uses the last non-null served model (`executor.py:458-471`); in an Evaluation that includes every member and synthesizer call inside one outer Candidate span, not merely one tool loop. | `Span.response_model` **L**, but **A** when it is the request echo or the final model among several Candidate operations; no field distinguishes either case. | **X** from `_RunOutcome`/Report. | **L/E** only for a one-call span when Gateway reported it and no attempt was omitted; otherwise **L/A**; **X** after live events. |
| Provider | Gateway **P/E** per attempt; Engine selects the terminal rendered attempt, else derives from its model-route catalog (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:239-250`; `apps/screamingface-engine/src/screamingface_engine/runner/connector.py:401-419`). | Per-round-trip Usage **F**; a span containing several calls is last-wins. Actual Candidate member/synthesis calls all share the outer `/benchmarks/candidate` span, so its provider is merely the final call's provider. Subtree is the sole pair or literal `mixed/mixed` (`apps/screamingface-engine/src/screamingface_engine/runner/executor.py:458-471`, `:581-607`). | **L** on Span/Usage. | Runtime provider **X**. A provider prefix may be **D** from static model routes but is not retained provider evidence. | **E** when a one-call span has Gateway terminal evidence; otherwise **D/A** from final-call/catalog data; no retained runtime provider. |
| Gateway/attempt identities and outcomes | `gateway_call_id`, attempt id/sequence, dispatch+attempt indices, transport, outcome, HTTP status, latency, provider response id, redirect hops, and failure code are **P/E** (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:449-499`; metadata envelope `apps/aigateway/src/aigateway/plugins/taxonomy/render.py:167-190`). | `CallAccounting` retains none of them (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:60-78`, `:207-250`). | **X**. | **X**. | Entire attempt ledger is lost at Gateway → Engine after its token/cost roll-up. |
| Provider attempt latency | Gateway **P/E** measures monotonic admission to completed response body; incomplete bodies stay `None` (`apps/aigateway/src/aigateway/plugins/taxonomy/collector.py:228-262`). | **X**. URL4/Engine creates a different node-span interval: UTC time when the bridge drains `NodeStarted` to when it drains `NodeFinished`, encompassing the whole node/tool loop and queue delay, not provider latency (`apps/screamingface-engine/src/screamingface_engine/runner/executor.py:344-370`, `:474-508`). | Node interval **L/E-as-bridge-interval**, **A** as provider/network latency. | Per-span interval **X**. `_RunOutcome` keeps Started/Terminated CloudEvent times and Report derives only candidate/report wall duration (`packages/screamingface/src/screamingface/_engine/contract.py:159-167`, `:223-233`; `packages/screamingface/src/screamingface/report.py:223-255`, `:331-341`). Member duration is always populated `None` by current result construction (`packages/screamingface/src/screamingface/_evaluation/results.py:137-147`). | Provider timing **X**; live node timing **L**; candidate wall time **R**; per-operation/case/member timing **X**. |
| Cache status/reason | Gateway **P/E** per response. Engine reads the response headers, not historical `_aigw.cache.reference`, and reports one `ModelResponse` per consumed round trip (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:300-320`, `:480-526`, `:577-585`). | URL4 emits per-round-trip status/reason. Engine Span is last-wins whenever several calls share it. That includes a tool loop and, in an Evaluation, every member/synthesis call inside one outer Candidate span. Run cache counters still record every round trip and become a closing Log (`packages/url4/src/url4/observe.py:102-137`; `apps/screamingface-engine/src/screamingface_engine/runner/executor.py:387-413`, `:610-670`). | Span's last status/reason and run Log counts/reasons are **L**. Live notebook UI derives hit rate/fully-cached state (`packages/screamingface/src/screamingface/_ui/evaluation_state.py:88-122`, `:198-228`; display `packages/screamingface/src/screamingface/_ui/evaluation_view.py:183-204`, `:286-294`). | **X** from `_RunOutcome`/Report/final Report UI. Zero tokens/cost remains but is not distinguishable there from another genuinely zero call. | Per-round-trip detail is already **Σ/A** by the time the Span reaches the Client; the run Log is **L/Σ/E** for counts; final cache provenance **X**. |
| Trace/span hierarchy | URL4 **P/E** creates one trace id/root and random span id + parent per node (`packages/url4/src/url4/observe.py:29-56`; executor `packages/url4/src/url4/dag/executor.py:154-213`). The task-local sink binds each concurrent sibling to its own span (`packages/url4/src/url4/observe.py:172-196`, `:225-249`; test `packages/url4/tests/unit/test_usage_sink.py:125-159`). | Wire carries the span id in W3C `traceparent` and non-root parent as `url4.parent=<id>` in `tracestate`; self usage and Span share the same span reference (`packages/url4/src/url4/streaming/lifecycle.py:114-170`; `packages/url4/src/url4/streaming/trace.py:13-18`). | Raw traceparent/tracestate are **L** on every public Event; span/parent IDs are **D/E** by parsing (`packages/screamingface/src/screamingface/events.py:21-49`). | **X** from `_RunOutcome` and Report. | Exact live correlation between a Span and its self Usage exists; it is not retained. |
| Source/provenance | Gateway usage evidence source, direct-cost source, pricing context, response id, and extension fact sources are **P** (`apps/aigateway/src/aigateway/plugins/taxonomy/types.py:163-309`, `:414-499`). | All are **X** except normalized provider/request/served model and USD. A different CloudEvent `source` is **P/E** as `/trace/<topic>/node/<runner-node>` and is identical for all frames from that runner, not a DAG operation/source binding (`packages/url4/src/url4/streaming/protocol/envelope.py:7-33`; `packages/url4/src/url4/streaming/lifecycle.py:50-67`). | CloudEvent source **L**. | All provenance/source fields **X** from `_RunOutcome`/Report. | Provider evidence provenance lost at Gateway → Engine; runner producer source live-only and cannot identify operation/case/role. |
| Logical operation id/kind/params | Client compilation **P/E/R** creates stable `OperationInfo.id/kind/depends_on`; Candidate privately also holds operation parameter assignments (`packages/screamingface/src/screamingface/operation.py:9-39`; `packages/screamingface/src/screamingface/_evaluation/model.py:21-50`, `:96-150`). Engine separately records terminal model calls as `(path, sorted params, output, finish_reason)` (`apps/screamingface-engine/src/screamingface_engine/operation_calls.py:17-85`). | URL4 span detail selects only the first string `target/path/text/body`, so a model span contains the route path but not params, authored source binding, or stable operation id (`packages/url4/src/url4/dag/executor.py:216-223`). Usage has no operation field. | Route path + node kind + span are **L**; operation id is **X**. Unique route can be **D** only under extra static/cardinality assumptions; same route with different params is already **A** because params are absent. | Case `OperationOutput`/`CaseOperation` **R** only operation id, terminal output, finish reason—never accounting (`apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py:182-197`, `:210-245`; `packages/screamingface/src/screamingface/case_result.py:224-256`). Current `MemberResult` runtime fields are explicitly constructed as `None` (`packages/screamingface/src/screamingface/_evaluation/results.py:137-147`). | Static operation graph/output **R**; runtime accounting-to-operation join **X/A**. |
| Nested Candidate observation boundary | The Benchmark calls `/benchmarks/candidate`, whose adapter evaluates the complete Candidate with `Url4Node.evaluate()` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_adapter.py:22-44`; `benchmarks/invocation.py:27-67`). | `Url4Node._run_text` constructs a fresh `ExecutionContext` with no observer (`packages/url4/src/url4/peer/server.py:363-392`). The nested executor therefore emits no member/synthesis `NodeStarted` or `NodeFinished`; its connector calls inherit the outer Candidate node's task-local usage/response sinks, which remain bound for that whole endpoint resolve (`packages/url4/src/url4/dag/executor.py:176-213`; `packages/url4/src/url4/observe.py:181-249`). A local synthetic probe confirmed one outer Usage event for a nested model call. | The Client sees one `/benchmarks/candidate` Span and one self Usage aggregate per Case, not one Span/Usage per member or synthesizer. Provider/model/cache/refusal fields on that Span are final-call/last-wins while numeric usage is the sum. | The aggregate contributes correctly to root total, then only the root subtree survives. Operation outputs are captured through a separate Engine recorder and do not restore the accounting split. | This is the first Evaluation-specific coalescing boundary. Member/synthesis accounting is already **Σ/A** before the Engine wire; Client retention alone cannot separate it. |
| Benchmark role (generation/member/synthesis/grading) | Candidate role is present in the authored benchmark/Candidate graph. Grading results retain a model `EvidenceProducer(type,id)` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py:46-63`; Client retention `packages/screamingface/src/screamingface/case_result.py:36-114`). | Usage/Span carries no role. Candidate and judge both use the same `_ModelEndpoint`/relative-model route path; if they use the same model there is no wire discriminator. | Full Started URL4 + topology is **L/D**, but dynamic rows/retries/repeated routes make role attribution non-contractual and sometimes **A**. | Candidate operation kinds and grading producer are **R** on separate result objects; accounting is only candidate-root total. | Role facts **R**; role-accounting join **X**. Same candidate/judge model is not exactly separable. |
| Case identity | Benchmark **P/E** carries `case_id` beside Candidate Invocation and grading in a strict case-execution envelope (`apps/screamingface-engine/src/screamingface_engine/benchmarks/case_execution.py:22-83`, `:86-105`). | Case id travels in runtime context/intent/result payload, none of which is included in Usage or Node detail. | Live UI recognizes the `/benchmarks/case-execution` route and increments an anonymous completion counter; it does not learn a case id (`packages/screamingface/src/screamingface/_ui/evaluation_state.py:157-174`). | `CaseResult.case_id` **R/E**, with output/refusal/grade/failures/operation outputs (`packages/screamingface/src/screamingface/case_result.py:259-334`; decoder `packages/screamingface/src/screamingface/_evaluation/results.py:223-301`). No accounting fields exist in the case envelope/result. | Case identity **R/E**; case-accounting join **X**. Ordering/topology is at most **D/A**, not an exact key. |
| Finish reasons/refusal | Connector reports each consumed round trip before refusal classification; terminal successful operation recording happens only after unusable/refusal checks (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:529-602`). | URL4 `ModelResponse` is per round trip. Engine Span retains ordered non-null finish reasons and last refusal; cost is separately aggregated on the same span (`packages/url4/src/url4/observe.py:102-137`; `apps/screamingface-engine/src/screamingface_engine/runner/executor.py:273-296`, `:387-413`, `:474-535`). In an Evaluation, the outer Candidate Span combines these across every nested member/synthesis call. | **L/E** for the reported list/last value, but their association to one operation or one round-trip cost is **A**. | Case/Candidate terminal finish/refusal **R/E** (`apps/screamingface-engine/src/screamingface_engine/benchmarks/invocation.py:27-67`; `packages/screamingface/src/screamingface/case_result.py:259-334`). Accounting join is gone. | Outcome retained; accounting relation is not exposed at member/round-trip/case granularity. |
| Run/Candidate identity | Engine lifecycle **P/E** supplies one run subject/trace. Client evaluation internally binds each concurrent transport run to its `Candidate` before forwarding events (`packages/screamingface/src/screamingface/_evaluation/runner.py:200-221`, `:352-428`). | All frames carry the run subject and source. | Public Event has `run_id` but no Candidate name. Built-in progress is exact because its private observer closure already knows the Candidate; a user's callback sees only Event. | `_RunOutcome.run_id` and `CandidateResult.run_id/name` **R/E**, enabling after-the-fact mapping (`packages/screamingface/src/screamingface/_core/ports.py:32-48`; `packages/screamingface/src/screamingface/report.py:156-175`). | Run→Candidate **R/E** after result construction; public live callback Candidate identity is **D/A** for concurrent identical expressions. |

### Execution-shape audit

| Required shape | What current code proves |
|---|---|
| Solo generation | The model endpoint reports one Usage/ModelResponse per Gateway round trip (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:373-420`, `:529-602`). In an Evaluation those events attach to the outer `/benchmarks/candidate` Span because the Candidate's nested executor has no observer. The final Candidate root total is retained. A solo Candidate deliberately emits no `operations` payload, so there is no retained runtime operation attribution (`apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py:55-67`; test `apps/screamingface-engine/tests/unit/test_operation_output_capture.py:184-189`). |
| Fusion with distinct routes/params | URL4 itself gives directly-observed concurrent siblings distinct spans with no ContextVar cross-talk (`packages/url4/tests/unit/test_usage_sink.py:125-159`), but actual Benchmark Candidate execution is nested and emits no inner spans. All member/synthesis accounting attaches to the one outer Candidate span. The separate output recorder can exactly join `(path,sorted params)` to `op_model_N`/`op_synthesis_N` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py:55-99`; test `apps/screamingface-engine/tests/unit/test_operation_output_capture.py:128-142`, `:239-272`). Accounting does not use that recorder, so distinct output attribution does not imply distinct cost attribution. |
| Identical model operations | Executions still have distinct random span ids, so work is not collapsed. But two operation bindings with identical path+params have no semantic discriminator. Output attribution copies one result to both only if every captured `(output,finish_reason)` is identical; divergent results become null (`apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py:78-99`; test `apps/screamingface-engine/tests/unit/test_operation_output_capture.py:145-165`). Accounting is therefore **A** between the identical operations even when output happens to be identical. |
| Synthesis | Direct named `synthesis_N` sources use the same fingerprint/output path as members and are retained as `op_synthesis_N` when unambiguous (`apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py:42-46`, `:102-125`). The nested Candidate executor emits neither member nor synthesis spans, so synthesis accounting is folded into the same outer Candidate span before the wire. Nested Recipe values also have no direct output fingerprint and remain null (`operation_outputs.py:119-125`). |
| Grading | HealthBench/GDPval invoke Candidate once per case then one judge call per rubric item, with nested judge retries (`apps/screamingface-engine/src/screamingface_engine/benchmarks/healthbench/exam.py:167-233`; `apps/screamingface-engine/src/screamingface_engine/benchmarks/gdpval/exam.py:155-229`). DRACO invokes Candidate once then seeded judge passes per criterion with `retry=2` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/draco/exam.py:168-285`). Grader model nodes belong to the directly observed outer Benchmark graph, so their generic spans remain individually live; Candidate generation/synthesis is already coalesced into one Candidate span. Judge evidence retains producer model and case/check identity, but Usage/Span has no case or grader-role key, so neither side can be exactly joined—especially when the same model route appears in Candidate and grading roles. |
| Concurrent cases | **U in current built-in protocols.** The outer case iterator explicitly sets `concurrency=1` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/protocol.py:67-97`). It is incorrect to describe current benchmark cases as concurrent. Within a case, rubric/criterion iteration uses URL4's default bounded concurrency of 8 (`packages/url4/src/url4/dag/nodes.py:95-102`), and multiple Candidate roots run concurrently up to 8 (`packages/screamingface/src/screamingface/_evaluation/runner.py:43`, `:352-428`). These concurrency paths have exact span isolation but still no case/role/operation key. |
| Gateway/LiteLLM retries | Gateway observes each local send with dispatch/attempt indices and can retain billed failed attempts. Engine sums token classes across every rendered attempt, failures included, and takes the already-summed direct cost once from request economics (`apps/screamingface-engine/src/screamingface_engine/runner/accounting.py:207-250`; tests `apps/screamingface-engine/tests/unit/test_accounting.py:246-268`). Downstream sees one Usage for that Gateway HTTP round trip: attempt count/outcome/latency is **X**. |
| Engine→Gateway transport retry | Connector retries one `httpx.TransportError` once (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:70`, `:423-455`). A failed try returns no Gateway body, so it produces no `_report_usage`/`_report_response`; if the Gateway/provider did work before the response was lost, that work is unknowable to Engine and **X**. The later successful response is the only reported round trip. |
| URL4 `;retry=` / judge redraw | Each Guard attempt evaluates its inner subtree with a fresh Executor, hence fresh spans; transient errors retry, permanent errors do not (`packages/url4/src/url4/dag/nodes.py:487-549`; fresh executor `packages/url4/src/url4/dag/executor.py:284-292`; retry tests `packages/url4/tests/unit/test_dag.py:607-644`). Every emitted Usage is added to run totals before node status is known (`apps/screamingface-engine/src/screamingface_engine/runner/executor.py:415-471`), so paid failed redraws and the success are **Σ/E** in root tokens/cost. Live spans expose repeated error/success executions, but no retry-attempt number or semantic role is retained. |
| Tool loop | Every Gateway round trip reports Usage and ModelResponse. Directly observed model execution folds those into one model-node span; an Evaluation folds them together with every other nested member/synthesis call into the outer Candidate span. Tokens/cost sum every round, finish reasons preserve order, refusal/cache/provider/model are last-wins, and only terminal content is recorded as operation output (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:529-602`; fold `apps/screamingface-engine/src/screamingface_engine/runner/executor.py:387-471`; cost regression `apps/screamingface-engine/tests/unit/test_run_cost_capture.py:306-329`). Live Client gets one aggregated self Usage plus one Span, not one Usage per Gateway round trip or Candidate operation. Per-round-trip and per-operation cost/model/cache/tool identity are therefore **X/A** downstream. |
| Cache hit and bounded revalidation | A consumed hit is **E** zero current tokens/cost and its status is live. Historical response usage is not counted (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:335-370`; test `apps/screamingface-engine/tests/unit/test_run_cost_capture.py:241-255`). If max-age revalidation discards a hit, connector intentionally does not report the discarded response and reports only the reissued response (`connector.py:480-526`): that first cache hit/HTTP latency is **X** from telemetry, though it incurred no provider tokens/cost. |
| Provider/model refusal | Connector reports Usage and response outcome before `raise_if_unusable`; `_ModelEndpoint` binds the model outcome to the error, and Candidate Invocation catches `provider_refusal` into a typed envelope (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:183-211`, `:581-595`; `apps/screamingface-engine/src/screamingface_engine/benchmarks/invocation.py:37-60`). Thus the refused call's tokens/cost are in live self and successful benchmark-root subtree totals, while Case refusal/finish text is retained. The refused operation itself has no terminal `OperationCall` because recording occurs after the unusable check, so its operation output stays absent; no accounting join survives. |
| Non-2xx Gateway failure | Gateway can attach `_aigw` beside a safe error detail (`apps/aigateway/src/aigateway/plugins/taxonomy/session.py:401-430`). Engine `_raise_for_status` reads only `payload.detail` code/message and raises before JSON/accounting reporting; it ignores the sibling `_aigw` block (`apps/screamingface-engine/src/screamingface_engine/runner/connector.py:513-526`, `:753-782`). Any billed-attempt accounting in that error is **X** at this handoff, and the resulting model-route Span has no model/usage attributes. |
| Failure after earlier paid work | Usage is folded before NodeFinished, so a node/tool/retry that later errors still emits a self cost frame when its span closes (`apps/screamingface-engine/src/screamingface_engine/runner/executor.py:344-370`, `:415-535`). If benchmark `on_error=collect` contains it, the root can succeed and its total reaches Report; the case envelope retains the grading/candidate failure (`apps/screamingface-engine/src/screamingface_engine/benchmarks/protocol.py:12-64`). If the top-level run fails, lifecycle never emits subtree CostUsage or Result—those are success-only—and Client raises without `_RunOutcome`/Report (`packages/url4/src/url4/streaming/lifecycle.py:139-178`, `:209-228`; Client failure boundary `packages/screamingface/src/screamingface/_engine/contract.py:199-233`). Prior self Span/Usage callbacks may already have been **L**, but are not retained. |

### What the Client and the two UIs actually have

1. **Public live callback:** every accepted Started, Log, Span, self Usage, subtree Usage, and
   successful Terminated event is delivered before transport returns
   (`packages/screamingface/src/screamingface/_engine/transport.py:283-302`, `:495-517`). It has the
   richest post-wire data: run/source/sequence/time/trace, node route/kind/status/time,
   provider/request/served model, input/output, finish/refusal/cache, and scoped token/cost Usage.
   It has no Candidate name, operation id/params, benchmark role, or case id. A failed root
   Terminated is constructed and then converted directly to `ExecutionError`, so that root terminal
   event is not returned to the callback (`packages/screamingface/src/screamingface/_engine/contract.py:199-218`).
2. **`_RunOutcome`:** run id, root start/end, result body/media type, and root `sf.Usage` only
   (`packages/screamingface/src/screamingface/_core/ports.py:32-48`). All spans, traces, provider/model,
   cache, source, and scoped self Usage are discarded here.
3. **Final `Report`:** exact Candidate static identity/DAG, exact case/grade/failure/operation-output
   artifacts, candidate wall duration, and root subtree six-field Usage. Current construction sets
   every member `failures`, `duration_ms`, and `usage` to `None`
   (`packages/screamingface/src/screamingface/_evaluation/results.py:111-151`, `:223-373`). The public
   types have member runtime slots, but no current runtime path fills them
   (`packages/screamingface/src/screamingface/report.py:37-92`).
   The generated API notebook currently overclaims that Reports retain “per-Case usage”
   (`packages/screamingface/scripts/build_notebooks.py:407-411`); `CaseResult` has no usage or
   duration field, so that documentation is false today.
4. **Final Report UI:** shows report/candidate total cost, input+output token total, and candidate
   duration; member duration/tokens render dashes because current values are `None`; cache/reasoning
   token classes and provider/model/span are not shown
   (`packages/screamingface/src/screamingface/_ui/report_view.py:236-297`, `:430-451`, `:860-871`).
   Case id, answer, refusal, finish, grading evidence, and failure text are shown separately
   (`report_view.py:638-714`).
5. **Live notebook Evaluation UI:** the private observer knows the Candidate and aggregates Span
   input/output/model-call/cache counters plus priced self costs
   (`packages/screamingface/src/screamingface/_ui/evaluation_state.py:124-228`). It ignores unpriced
   self costs rather than poisoning the displayed sum; when final Report cost is `None`, reconcile
   deliberately leaves the known live subtotal in place (`evaluation_state.py:224-242`; pinned by
   `packages/screamingface/tests/test_live_candidate_progress.py:462-488`). Consequently a mixed
   priced/unpriced run can display an unlabeled known **partial** cost while the authoritative final
   Candidate total is unknown. That number is **L/Σ/A**, not an exact run total.

### Exact joins that do and do not exist

- **Exists live:** URL4 span id ↔ the directly observed node's aggregate self Usage. Both carry the
  same traceparent; parent topology is derivable from tracestate. For nested Candidate execution,
  that exact node is `/benchmarks/candidate`; its self Usage is already the sum of all member and
  synthesis work in that Case.
- **Exists at Gateway only:** Gateway call ↔ ordered provider attempts, including failed attempts,
  exact attempt latency, provider response id, token/direct-cost evidence status/source.
- **Exists in benchmark result only:** case id ↔ Candidate terminal result ↔ grading outcome; and,
  when fingerprinting is unambiguous, operation id ↔ terminal output/finish reason.
- **Does not exist:** span/Usage ↔ stable operation id; span/Usage ↔ case id; span/Usage ↔
  generation/synthesis/grading role; Gateway call/attempt ↔ URL4 span; per-round-trip tool-loop Usage
  ↔ individual finish/cache outcome after Engine folding.
- Because the accounting stream and benchmark identity envelopes never share a join key, no current
  Client decoder, Report projection, or UI-only calculation can recover an **exact** per-operation,
  per-case, or per-role breakdown from retained data. Unique route/order/topology can yield a
  heuristic for some runs, but identical routes, params omitted from spans, repeated cases,
  retries, and tool loops make that heuristic ambiguous. This is a statement about current data,
  not a proposed seam.

### Unknowns that require characterization before anyone relies on them

Static source and existing unit tests prove the declared shapes above, so no production or test
files were changed during this audit. These remaining questions are runtime/provider behaviours,
not facts the source can establish:

1. **Partial/omitted Gateway attempt handoff:** a cross-process fixture with a failed attempt whose
   usage is absent, a successful terminal attempt, and a bounded/omitted tail is needed to measure
   the exact Client-visible undercount/fallback shape. Source proves the risk (`read_aigw` ignores
   capture status and connector falls back to terminal usage), but not which live providers emit
   usage on each failure.
2. **Gateway error accounting:** characterize a 429/5xx/conversion error carrying `_aigw` through a
   real Engine request. Source proves current Engine code ignores it; the test should pin whether
   each deployed Gateway error handler actually emits the metadata for that failure class.
3. **Transport lost-response billing:** no local test can prove whether a provider was billed when
   Engine→Gateway transport failed after request delivery but before a response. Only a correlated
   Gateway/provider fixture can classify that external event; current Engine accounting must remain
   “unknown/lost,” not zero.
4. **Topology heuristic:** if anyone intends to derive case/role/operation from span order or parent
   topology, characterize distinct and byte-identical model routes, same-model Candidate+judge,
   judge redraw, tool loop, refusal, and collected failure in one end-to-end trace. There is no
   contract field that guarantees such a derivation today.
5. **Concurrent cases:** built-ins cannot characterize this because they explicitly serialize
   cases. A custom/future protocol with case concurrency greater than one would need a test proving
   both task-local usage isolation and semantic case attribution. Existing tests prove only the
   first half (span isolation), not a case join.
6. **Mixed priced/unpriced live display:** an end-to-end run should pin the already source-proven
   split where live UI retains a known priced subtotal while root Report cost is `None`; existing
   Client unit coverage pins reconciliation but not a real mixed-provider Engine stream.

### Smallest conclusion justified by current code

- Candidate/run total accounting already exists; no change is needed to show that same total.
- Exact per-operation/case/role accounting cannot be delivered from the final Client/Report/UI data
  alone, and cannot be reconstructed from Gateway attempt metadata alone because the Gateway never
  receives those benchmark identities.
- Retaining the current Client Events would recover generic grader-node facts but still would not
  recover member/synthesis facts: those have already coalesced at the nested Candidate boundary.
- Current evidence does **not** choose an architecture. It proves only the lower bound: any future
  retained breakdown must create an exact accounting↔benchmark-identity join before the current
  `_RunOutcome` reduction, and the Client must retain whatever joined facts are selected. Whether
  that join belongs in existing Engine benchmark/runtime code or requires a URL4 contract change is
  not determined by this audit and needs the design decision that follows it.

### Owner-approved design handoff

The audit establishes the lower bound above; the subsequent design review selected the smallest
retained-Report architecture that satisfies it. The authoritative contract is
`docs/spec/2026-08-27-OME-901-operation-accounting.md`; this section records only the resulting
handoff so this evidence ledger does not preserve a superseded proposal.

- No `packages/url4` or AI Gateway change is required. The generic `Url4Executor` remains
  benchmark-agnostic and unchanged.
- `operation_calls.py` remains the one normalization and capture mechanism, with two deliberately
  isolated owners: a Candidate-local scope for member/synthesis calls and a run scope for canonical
  benchmark grading calls. The run scope is installed by a ScreamingFace Engine composition-root
  streaming `Executor` decorator; it is not a log or URL4 protocol extension.
- One shared `OperationAccounting` value attaches to the existing semantic owners: Candidate
  member/synthesis accounting on `CaseOperation`, and rubric-judge accounting on grading
  `Evidence`. No parallel grading-operation ledger is introduced.
- Candidate operation matching deepens the existing path/parameter projector; accounting is not
  copied across ambiguous equal outputs. Grading uses an ephemeral in-memory request key because
  many Cases share one judge route and execution order is unsafe. No key or explicit operation-id
  parameter is serialized.
- Candidate/root usage remains authoritative. Fields are exact-only; only cost receives an exact
  unattributed remainder when root and attributed costs are known and disjoint.
- The existing Gateway provider-attempt latency is retained as Provider time. It is not wall time;
  no new Engine timer or member duration is introduced.
- OME-901 retains calls that survive into Candidate operations or grading Evidence. Failed-path
  evidence/accounting remains `OME-784` rather than being intercepted here.
- Live semantic publication is not part of OME-901. Existing live cost/cache behavior is pinned
  unchanged; OME-699 may later publish the same semantics without changing this retained model.

The required landing order is one ScreamingFace Engine producer child followed by one Python Client
decoder/projection/completed-Report UI child. That split satisfies the repo's cross-cutting-work
rule without creating a URL4, AI Gateway, or live-delivery child.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the evidence ledger, shared spec/plan, parent/child task mirrors, and design
  ledger; no production or test code changed.
- **Commits:** none yet.
- **Gates:** `git diff --check`; exhaustive static lineage inspection; one local nested-usage probe
  confirmed that Candidate member usage binds to the outer Candidate span when the nested
  `Url4Node.evaluate()` creates an observer-less execution context.
- **Deviations:** the issue's starting premise—that one already-attributed cost frame per operation
  reaches the Client and is merely summed away—was disproven. The audit was expanded through the
  nested Candidate boundary and the existing per-Case operation/Evidence contracts before any
  architecture was proposed. A second adversarial pass removed a parallel grading ledger, a new
  timer, member-duration claims, complete Candidate fingerprints, exact token remainders, and
  failed-path promises from the first draft.

## Fresh-main revalidation — 2026-08-27

Revalidated the conclusions after fetching and rebasing the docs worktree onto `origin/main`
`21c17d53`:

- Public `Span`/`Usage` events still reach Client observers and the live evaluation state still
  consumes them. The correction is explicit: the Client has rich generic live telemetry; it lacks
  a retained semantic operation/Case/Check join.
- `_RunOutcome` still retains only the root result, timestamps, and root usage; Report construction
  still initializes every `MemberResult.usage` and `MemberResult.duration_ms` to null.
- Nested Candidate evaluation still uses observer-less `Url4Node.evaluate()`, so inner member and
  synthesis telemetry is folded into the outer Candidate node before the wire.
- The existing `OperationCall` recorder still retains only path, sorted parameters, terminal
  output, and finish reason. Connector accounting and cache normalization remain the lowest
  ScreamingFace-owned boundary with the needed raw facts.
- Gateway `capture_status`, `observed_attempts`, and `omitted_attempts` prove that attempt-derived
  operation fields must be gated on complete evidence. Gateway already records provider-attempt
  latency, so the revised design does not add a broader Engine request timer.
- `Url4Executor` still implements the generic streaming `Executor` port, creates its drive task
  inside `execute()`, and is wired from the ScreamingFace Engine composition root. The proposed
  recorder decorator remains feasible without a `packages/url4` change, but that feasibility is a
  design conclusion until OME-1030 pins it with cancellation/concurrency tests.
- CorrectiveLoop still evaluates every nested member/judge/coach Recipe with `isolated=True`, then
  decodes the selected Candidate Invocation down to output, finish reason, and refusal. Its outer
  record retains only stop reason and rounds executed, so nested operation records cannot currently
  propagate. The Candidate/root total remains exact; per-operation nested accounting must stay an
  explicit remainder in OME-901.

The approved Client child now requires a same-run regression that pins the distinction this audit
must not lose again: detailed generic events are live-delivered, while `_RunOutcome`/Report retains
only root usage before the new semantic projection is decoded. The test lands in the Client child,
not on this cross-cutting design branch.

Verification: 54 focused Engine tests passed. The focused Client selection passed 82 tests total;
79 passed in the base environment, and the three notebook-widget tests passed after enabling the
declared `notebook` extra. No failure exercised accounting behavior.
