---
ticket: OME-1989
stack: screamingface-engine
status: done
started: 2026-11-20
finished: 2026-11-20
---

# stop-run-on-refused-key — stop a run when the provider refuses the key

## Intent

When a provider refuses a hosted key on every call, the Engine records each refusal as one
failed Case and moves on. On 2026-11-19 one account's 18 runs sent 7,056 Candidate calls that
OpenRouter refused with 403 (its key had been disabled by hand), each back in about 0.3 s,
holding slots on 4 of 6 runner pods and slowing the gateway for other users. The run should
notice, stop sending, and end with one run-level error that names the cause. The gateway's
record of a provider 402/403 should also say why the provider refused, since on the day it
said only `type=APIError`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/refused_key_stop.py` (new) — the
  rule and one run's refusal state.
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py` — the Candidate call
  consults the rule before sending, and reports each answer and gateway refusal to it.
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` — binds the state per
  run; a stopped run ends with the run-level error.
- `apps/screamingface-engine/src/screamingface_engine/error_text.py` — `provider_key_refused`
  joins the engine-authored codes.
- `apps/aigateway/src/aigateway/routes/chat_dispatch.py` — the terminal record of a provider
  402/403 carries the screened reason.
- Tests: `apps/screamingface-engine/tests/unit/test_refused_key_stop.py` (new),
  `apps/aigateway/tests/unit/test_dispatch_failure_records_refusal_reason.py` (new).
- `docs/tasks/2026-11-20-OME-1989-stop-run-on-refused-key.md` (mirror).

## Test plan

- The first `auth_required` (401) or `insufficient_credits` (402) stops the run: 1 gateway
  call for 4 Cases, run-level `provider_key_refused`.
- The same 403 on 5 Cases in a row stops the run: 5 gateway calls for 100 Cases.
- A 403 that belongs to one Case never stops a run: an answer in between, a different refusal,
  or several Attempts of one Case each restart or do not grow the count.
- A judge call is never counted and never refused.
- One run's refusals never reach the next run; a cancelled run stays cancelled.
- The executor ends a stopped run as a failed run with no `Completed` step.
- Gateway: a provider 402/403 logs its status and screened reason; a reason that echoes the key
  is withheld; every other failure logs no reason.

## Acceptance

- A run whose key is refused makes at most 5 gateway calls per model after the refusals start,
  then ends `failed` with `provider_key_refused` and a message naming the cause.
- The Engine does not retry the same refusal (already true: a 403 is permanent).
- The gateway record of a provider 402/403 names the provider's reason, never the key.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus one added entry in the prior
  `apps/screamingface-engine/tests/unit/test_terminal_error_detail.py` (see Deviations).
- **Commits:** `fix(screamingface-engine): stop a run when the provider refuses the key`
- **Gates:** Engine: 218 passed across `test_refused_key_stop.py` (13 new),
  `test_candidate_call_retry.py`, `test_aigateway_connector.py`, `test_terminal_error_detail.py`,
  `test_request_scope_hardening.py`, `test_engine_remote_node_deferred_refusal.py`,
  `test_gateway_error_relay_contract.py`, `test_run_attachment_admission.py`,
  `test_failure_code_conformance.py`, `test_failure_classes.py`. Gateway: 31 passed across
  `test_dispatch_failure_records_refusal_reason.py` (9 new), `test_dispatch_failure_records.py`,
  `test_dispatch_failure_records_handler_error.py`. ruff check, ruff format and pyright clean on
  every touched file. Mutation check: with the executor's scope removed, the run-level test
  fails. The full suites are left to CI.
- **Deviations:**
  - No new gateway code for a provider 403 (the first plan). The SDK refuses a failure code it
    does not know when it reads a Report, so a new per-Case code would break released SDKs.
    The Engine reads the gateway's HTTP status instead, which it already has.
  - The stop refuses each later Candidate call inside the Engine rather than cancelling the
    run. url4 collects every Case's error, so nothing raised in one Case stops its siblings.
    The remaining Cases are still walked, with no gateway call.
  - `provider_key_refused` is not added to `DECLARED_FAILURE_CODES`: it ends a run and never
    lands on a Case of a Report, so the Engine and SDK lists and their conformance tests do
    not move.
  - Prior test edited: one entry, `provider_key_refused`, added to `ALLOWLISTED_CODES` in
    `test_terminal_error_detail.py`. That tuple is the hand-kept second copy of
    `ENGINE_ERROR_CODES`, and adding a code is meant to fail it. Owner approval recorded in
    `.claude/test-change-approvals/OME-1989.json`.
  - A stopped run drops its finished Cases, as every run-level failure does today.
  - 2026-11-21, at push: the rule module first imported url4's `ResolutionError`, which
    `test_only_engine_extensions_import_url4` refuses outside the Engine's allowlisted adapters.
    Fixed by the codebase's own pattern (as `classification` and `attachment_parts` do): the rule
    raises its own `KeyRefused`, and `connector.key_refusal_as_url4_error` turns it into url4's
    error, both before a Candidate call and around the run in the executor. The allowlist test
    is unchanged. Re-gated: 235 passed across `test_url4_executor.py` and the Engine files above.
  - 2026-11-23, review of #2002: the rule counted refused CALLS, so a Candidate that survives a
    refused call was stopped anyway: a quorum Fusion dropping its optional member, a fallback
    Gate (`sf.escalate_if(sf.unanswered())`), and a row policy (`on_error=collect`) inside the
    Candidate. A cached reply also restarted the count. Fixed at the Case boundary: the
    Candidate adapter opens `watch_case_refusals` around each Case; the connector only records
    what each call met. A Case counts when a key refusal left it unanswered (no call answered,
    or it failed with the refusal's own code); only a LIVE answer restarts the counts. New
    fixture `tests/unit/data/gate_contract/fallback_unanswered.url4` is the SDK's compile of
    that Cascade. The 5 new mechanism tests fail on the previous commit and pass now.
    Re-gated: 249 + 72 passed across `test_refused_key_stop.py` (20), `test_url4_executor.py`,
    the connector, retry, error-code, Case-attribution, cascade, quorum and Candidate-adapter
    consumer suites.
  - 2026-11-23, HupBaHa's review of #2002. P2: a 401/402 stopped the run only when its code
    was `auth_required`/`insufficient_credits`; a generic code (`provider_error`,
    `aigateway_http_402`) slipped through. The status is now the authority. P1: a Case
    already started when the stop is set still runs, so concurrent Cases could each send. The
    Benchmark protocol admits one Case at a time (`concurrency=1`), so the bound is 5 refused
    Cases (1 for a 401/402) plus each Case's own Attempts; stated in the rule's docstring and
    pinned by `test_the_benchmark_protocol_bounds_the_stop_to_five_cases`, which runs the real
    protocol with delayed refusals (mutation: `concurrency=8` sends 8 calls, test fails).
    Re-gated: 24 rule tests; 333 across the rule, protocol, adapter, connector, url4-boundary,
    cascade and quorum suites.
