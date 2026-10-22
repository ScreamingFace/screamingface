---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-10-22
finished:
---

# e2e-workbench-u7-debug-notebook — a failing notebook that teaches debugging with telemetry

## Intent

`debug_failing_run.ipynb`: a fusion with one unservable member fails on purpose; the tutorial
walks from the symptom (report) to the root cause (SDK telemetry, trace id, gateway logs) and
shows the fixed recipe. The lane runs it on replay as an expected-failure test (spec §3.7).
Plan: `docs/plan/2026-10-22-e2e-workbench-u7-debug-notebook.md`.

## Planned changes

- Task 1 (done, `7ce1e347f`): spec §3.7, `workbench/expectation.py`, verdict/bundle wiring.
- Task 2 (this entry): discovery only, no code. Findings below.
- Task 3: `build_notebooks.py` `debug_failing_run` + generated notebook.
- Task 4: UI (bundle page, Telemetry highlights, run-form label).
- Task 5: real replay lane + UI smoke + README.

## Test plan

- Task 2 has no code, so no RED/GREEN. The proof is the 3 identical real runs below, plus a
  dry run of `expectation.judge_expectation` over each run's `report.json`/`events.jsonl`.

## Findings (Task 2, 2026-10-22, replay stack, keyless, 0 spend)

Method: a scratch script (not committed) booted `workbench.targets.start_target("replay")`
with an `OtlpReceiver`, ran `client.evaluate(candidate, benchmark="ifeval", limit=1,
on_event=EventRecorder(...))`, then `recorder.finish(report)`. One fresh stack per run.

Candidate:

```python
sf.Fusion(
    [
        sf.Model("openrouter/mistralai/ministral-3b-2512", prompt=ANSWER,  # golden member 1
                 params={"max_tokens": 8192, "temperature": 0.0}),
        sf.Model("openrouter/openai/gpt-5.5", prompt=ANSWER),             # unservable on replay
    ],
    name="debug_unservable",
    synthesizer=sf.Model("openrouter/deepseek/deepseek-v4-flash", prompt=JUDGE,  # golden judge
                         params={"max_tokens": 8192, "temperature": 0.0}),
)
```

`ANSWER`/`JUDGE` are the golden `member_specs[0]`/`judge_spec` prompts. The tape
(`ifeval.snapshot.gz`, 177 rows) holds only `phi-4` (66), `ministral-3b-2512` (66) and
`deepseek-v4-flash` (45).

### Probe 1: a model id outside the Engine catalog is refused before any run

`openrouter/screamingface/unservable-debug-model`: `client.evaluate` raised
`PlanningError`, code `provider_not_credentialed`, `permanent=True`, `trace_id=None`,
message "your account holds no usable OpenRouter credential on this gateway — connect an
OpenRouter API key first". No run, no trace, no gateway chat line. This is a preflight refusal,
not a `candidate`-stage failure, so it cannot satisfy the verdict (no trace chain). The
unservable id must be a **declared Engine route that is absent from the tape**.

### Probe 2 + 3 determinism runs: `openrouter/openai/gpt-5.5` (a declared route, used by `test_failures.py`)

The probe and all 3 runs were identical, apart from the ids:

| run | trace id |
|-----|----------|
| 1 | `953f959699b4f69c700565418efc2db3` |
| 2 | `008db4a867e18fcdcf65d7c885a16611` |
| 3 | `fd751e325e5a53bbe450fa4ebcdbffd7` |

- **`evaluate()` does not raise.** `evaluate_error is None`. The run terminates `succeeded`
  (the `terminated` event and the `url4.run` span `url4.run.status=succeeded`). The candidate
  has `score=None`, `cache_hits=1`, and `failures=()` at the candidate level.
- **Failure code + stage (the declaration for Task 3):** `failure_codes: ["upstream_error"]`,
  `stage: "candidate"`. Case 1 is `status='failed'`, `output=None`, with one
  `Failure(stage='candidate', code='upstream_error', message='aigateway request failed with status
  404', retryable=False)`, `metadata.source_error = {kind: CandidateExecutionError, code:
  upstream_error, retryable: False, source_code: profile_not_found}`. In `report.json` it
  sits at `candidates[0].cases[0].failures[0]`.
- **The healthy member ran, but its output is not in the report.** With the default
  `quorum="all"`, the failed member fails the whole case before the synthesizer runs, so the
  case `output` is `None`. The proof that it ran: `cache_hits=1`, the `Model call completed`
  Log (`finish_reason=stop`) for ministral, and 2 `Usage` events (`scope=self` and
  `scope=subtree`), both `openrouter/mistralai/ministral-3b-2512` with all counts 0 and
  `cost_usd "0"`. Task 3 section 2 can't show "the healthy member produced output" from the
  report. It must use Usage, the cache hit or the completed Log instead.
- **SDK `Log` events at ERROR (`severity_number` 17).** There are 2 per run:
  - `body "Model call failed"`, attributes `sf.activity.model_id
    "openrouter/openai/gpt-5.5"`, `sf.activity.kind "model_call"`, `sf.activity.state
    "failed"`, `sf.activity.failure_code "internal_error"` (**not** `upstream_error`; the
    activity log does not carry the report's code), `case_id "1"`, `parent_id` = the
    answering activity;
  - `body "Answering failed"`, `sf.activity.kind "answering"`, `state "failed"`.
- **SDK `Span` events with `status "error"`.** There are 10 per run, all engine-internal url4
  nodes. The model-bearing one is `/benchmarks/candidate` (`RelUrlNode`), with `provider
  "openrouter"` and `request_model`/`response_model` set to **the healthy member**
  (`ministral-3b-2512`), `cache_status "hit"`, `finish_reasons ["stop"]` and tokens 0. The
  others are `ProcessNode`, `/benchmarks/case-execution`, `grading:…` (MapNode), `TextNode`,
  `StructNode` and `CollectNode`. **No span names `gpt-5.5`**, so filtering failing spans by
  model finds only the healthy model. The failing model is named only by the ERROR `Log`.
  `refusal` is `null` everywhere.
- **Event counts per run:** 43 lines. That is 1 `started`, 13 `log`, 26 `span`, 2 `usage` and
  1 `terminated`. The cache summary Log reads "1 hit, 0 miss, 0 bypass": a 404
  `profile_not_found` is **not counted as a miss**.
- **OTLP spans (`spans.jsonl`) under the run's trace:** the engine's internal spans mirror the
  SDK spans, with the same 10 `status.code "error"`. The gateway has 4 server spans: 2 `POST
  /v1/chat/completions`, `POST /v1/frozen-copies` and `…/seal`. **All 4 are `status.code
  "unset"`, with empty `attributes`.** The 404 chat span cannot be told apart from the cache
  hit, and there is no `http.status_code` or provider span.
- **Gateway log lines** (`aigateway.log`) under `trace_id=<run>`: 3 lines per run.
  - 2 × `INFO aigateway.plugins.taxonomy.session gateway_call_id=call_<id>
    trace_id=<tid> usage accounting started provider=openrouter …`, one per member call;
  - 1 × `INFO aigateway.routes.chat_cache_stage gateway_call_id=call_<id> trace_id=<tid>
    global cache hit provider=openrouter model='openrouter/mistralai/ministral-3b-2512'
    key=…`.

  **The 404 `profile_not_found` refusal logs nothing at the gateway.** The failed call shows
  up only as its "usage accounting started" line: its `gateway_call_id` has no cache-hit
  line. The trace chain is still complete, because both member calls carry `trace_id=` and
  `gateway_call_id=`.
- **Engine log** (`engine.log`): `WARNING screamingface_engine.runner.connector model call
  failed model=openrouter/openai/gpt-5.5 duration=0.0s code=profile_not_found` (and `…
  completed model=…ministral-3b-2512 … finish_reason=stop`). **These connector lines carry no
  `trace_id=` token**, so an exact-token filter on the engine log returns only `run
  scheduled`/`run terminated`. Every engine line is also written twice, because there are
  two handlers.
- **Verdict dry run:** `expectation.judge_expectation(Expectation(("upstream_error",),
  "candidate"), report, events)` returns no reasons on all 3 runs, with observed `failures=[{code:
  upstream_error, stage: candidate}]` and `error_telemetry={spans: 10, logs: 2}`.

### Open for the owner (affects Task 3 / local target)

- **The `local` target conflicts with the owner's decision.** "On local it's a provider
  error" fails for both kinds of id:
  - `gpt-5.5` is a real OpenRouter model, so on `local` with a key it would be **served and
    billed**, and the test would go red as an unexpected pass;
  - a non-catalog id never reaches a provider. It is refused at preflight, on replay at
    least. That is a `PlanningError` with no trace id, which the verdict rejects.

  Task 3 needs one of these decisions: a declared Engine route that OpenRouter does not serve
  (unverified, since checking it needs a paid call); `targets: [replay]` only; or a
  per-target unservable id or expectation.
- **Teaching gaps the notebook must work around, or file as follow-ups:**
  - the failing model has no span of its own;
  - the gateway's 404 chat span is `unset`;
  - the gateway logs no refusal line;
  - the engine's connector lines carry no `trace_id`;
  - the activity Log's `failure_code` (`internal_error`) disagrees with the report's code
    (`upstream_error`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** this ledger (Task 2).
- **Commits:** see `git log`; Task 1 `7ce1e347f`.
- **Gates:** Task 2 is discovery only. 3/3 real replay runs were identical, and the verdict
  dry run returned no reasons on each. Ports 9105, 9106 and 9108 were free afterwards.
- **Deviations:** the discovery used a scratch script, not a notebook, as the plan says
  ("No notebook yet").
