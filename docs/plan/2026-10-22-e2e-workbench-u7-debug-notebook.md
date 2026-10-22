# E2E workbench · Unit 7 — a failing notebook that teaches debugging with telemetry

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `debug_failing_run.ipynb` is a reviewable tutorial. It runs a fusion where one member
uses a model the gateway cannot serve, then walks the reader from the symptom to the root cause
using the report, the recorded SDK telemetry, the trace id and the gateway logs. Then it shows the
fixed recipe. The harness runs it on replay in CI as an **expected-failure** test.

**Spec:** `docs/spec/2026-10-16-e2e-notebook-workbench.md`. Task 1 adds §3.7, "Expected-failure
scenarios".
**Depends on:** unit 6, which provides the `events.jsonl`, `spans.jsonl`, `report.json` and
`accounting.json` recorder and the Telemetry UI.

## Owner decisions (2026-10-22)
- **The failure is an unservable member model.** On replay that's a cache miss at the keyless
  gateway; on local it's a provider error. The healthy member still runs.
- **It runs in CI as a guarded expected-failure test.** It passes only when it fails exactly as
  declared and the evidence is complete.

## Global Constraints
- **Keyless on replay.** The healthy member must be a model and prompt the ifeval tape recorded,
  so it hits the cache. The unservable member must miss deterministically and must never trigger
  a live call: the replay gateway has no keys, and a miss is already a hard refusal there.
- **Notebook metadata** declares
  `workbench: {targets: [replay, local], expect: {outcome: "fail", failure_codes: [<code>],
  stage: "candidate"}}`. The real code is discovered in Task 2, never guessed.
- **The verdict passes only if all hold:**
  1. the notebook raised nowhere else, and its asserts about the failure held;
  2. the declared failure code appears in the report;
  3. the trace chain is complete: every trace id is in engine and aigateway, with call ids;
  4. the telemetry captured the error: at least one `Span` event with a failing or refused status,
     or a `Log` at ERROR level, for that run.

  Any other outcome is red, including an unexpected pass, a different failure code, or missing
  evidence.
- **Redaction** applies to everything, as in unit 6.
- **The builder rules stay:** the notebook is generated, committed without outputs, and has
  exactly one result cell and marker.

## Tasks
1. **Spec and expected-failure verdict.** Add §3.7. In `verdict.py`, handle `expect: fail`:
   compare the declared and observed failure codes and stage, and require the evidence chain and
   the error telemetry. Unit-test each red case: unexpected pass, wrong code, missing evidence, and
   no error telemetry. Include the expectation and the observed failure in `trace.json` and the
   summary row ("expected FAIL ✓").
2. **Discover the real failure.** Run the candidate with an unservable member on the replay stack,
   once, keyless. Record the exact failure code, stage, the `Span` and `Log` shape, and the
   gateway log lines. Pick the unservable model id (for example a `openrouter/<vendor>/<model>`
   absent from the tape) and confirm it is deterministic across 3 runs.
3. **Builder and notebook.** Add `debug_failing_run` to `build_notebooks.py`. Its sections, in
   markdown plus code:
   1. Run the fusion. A healthy golden member plus the unservable member.
   2. Symptom. `report` shows which cases failed, with code and stage. The healthy member still
      produced output.
   3. The trace id for the run, or from the raised error.
   4. Telemetry.
      - Load the recorded events and filter to failing `Span`s and ERROR `Log`s.
      - Show model, provider, finish reason and error type.
      - Show `Usage` per model, to prove the healthy member ran.
   5. Follow the trace. Explain that the gateway lines carry `trace_id` and `gateway_call_id`,
      and point at the UI bundle page. Inside the notebook, show how to filter a log excerpt by
      trace id with the same exact-token rule the verdict uses.
   6. Root cause and the fixed recipe. Use the same fusion with a servable member. Leave it as a
      markdown code block, not executed, so the run stays failing by design.
   7. The single result cell, emitting trace ids and failure codes.

   Regenerate the notebook and keep the builder check green.
4. **UI.** On the bundle page, show expected-failure bundles as "expected FAIL ✓", or "✗" with
   the reason. In the Telemetry section, highlight failing spans and ERROR logs and link each to
   its gateway log lines by `gateway_call_id`. In the run form, label the notebook "(fails on
   purpose: debugging example)".
5. **Real proof.**
   - The replay lane with `REQUIRE_ALL=1`: `test_notebook[replay-debug_failing_run]` passes as an
     expected failure, alongside quickstart.
   - A UI smoke on a separate port: start both notebooks, open the debug bundle, and confirm that
     the failing span is highlighted and linked.
   - Update the README section "Debugging a failing run" and the ledger.

## Review Focus
1. If the unservable model accidentally becomes servable (a tape re-bless), the test must go red
   ("unexpected pass"), never green.
2. If the failure code changes (an SDK or engine refactor), the test goes red, naming the old
   and new codes.
3. The tutorial's log filtering must use exact `trace_id=` tokens, not a substring match. The
   notebook teaches the same rule the verdict enforces.
4. No secret appears in the tutorial's printed outputs on a local run, where the provider's error
   text can include request details.
