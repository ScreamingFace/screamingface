# Contracts: E4b part 3, signal sources v1

One section per connection. Path prefixes as in [erd](erd.md).

## C1 Declaration — SDK → engine, combine spec `signals` (url4 intent, JSON)

- **Shape.** Optional top-level key of `screamingface.combine-spec.v1` (additive, no new id):

  ```json
  "signals": {
    "<name>": {"source": "logprob", "form": "mean" | "sum" | "prob"}
            | {"source": "entropy", "top_logprobs": 1..20}
            | {"source": "verbalized", "pattern": "<RE2, 1..256 chars, exactly 1 group>", "ignore_case": false}
  }
  ```

  `<name>` matches `^[a-z][a-z0-9_]{0,31}$`, is not an E4a key, and does not start with
  `logprob`, `entropy`, `verbalized` or `consistency`. At most 8 names, at most one `entropy`.
  [stated ans:Q1]; [proposed] (rules)
- **Policies.** The spec is closed (`extra="forbid"`) [existing E/combine/spec.py:95]. `weights`, a
  reduce arg or the signal read may name a declared name; the key check moves from
  `is_signal_key(key)` to `is_signal_key(key) or key in spec.signals` at the plan level
  [existing E/combine/endpoint.py:381-397]. Without the key, the bytes do not change. [implied]
- **Failure behavior.** Any rule break is `combine_spec_invalid`, and the message never echoes a name
  or a pattern. [existing ET/test_combine_spec.py:335-347]
- **Contract tests.** DS#9, DS#10, VB#4, EN#6, RC#2–6.

## C2 Request params and preflight — SDK → url4 member call → engine → gateway body

- **Shape.** Member params `logprobs=true` and, with `entropy`, `top_logprobs=<k>`. The engine sends
  `"logprobs": true, "top_logprobs": k` in the chat body. [existing S/_evaluation/policy.py:18-29];
  [existing E/world/request_parameters.py:172-189]
- **Policies.** The injected params go into `parameter_assignments`, so the SDK preflight checks them
  against the gateway parameter catalog before any spend. [existing S/_evaluation/model_parameters.py:153-225];
  [proposed] (orchestrator decision). They are part of the call fingerprint `(path, params)` that
  `sources` use [existing S/_evaluation/combine_sources.py:20-30] and of the gateway cache key
  [existing G/plugins/openrouter_provider/parameters.py:241-256]. The SDK never emits `top_logprobs`
  alone; the gateway refuses that [existing G/plugins/openrouter_provider/plugin.py:312-318].
- **Failure behavior.** A model that the catalog marks unsupported: `unsupported_model_parameter`
  before any call (LC-E4). Any other model: see C4.
- **Contract tests.** LC#1, LC#15, LP#6, EN#8.

## C3 Reply logprobs — gateway → engine (HTTP response, OpenAI shape)

- **Shape.**

  ```json
  {"choices": [{"message": {...}, "logprobs": {"content": [
    {"token": "...", "logprob": -0.1, "bytes": [..], "top_logprobs": [{"token": "...", "logprob": -0.1, "bytes": [..]}]}
  ]}}]}
  ```

  The engine reads only `logprob` and `top_logprobs[].logprob`. [proposed]
- **Policies.** Untrusted input. Token values and top lists are validated apart (erd §3). A value must
  be a finite number ≤ 0. A bad shape gives None, with a warning that names the exception type only.
  [proposed]; [existing E/world/connector.py:1380-1389] (fail-open precedent)
- **Failure behavior.** No `logprobs` in a 200 reply → None and one count-only warning per step
  (LC-E3). Not a member failure.
- **Contract tests.** LC#3–6, LC#14, LC#17, EN#1–5, EN#11–12, against the fixture recorded in unit 1.

## C4 Refusal — gateway (HTTP 4xx) → engine failure code

- **Shape.** The gateway answer to an OpenRouter refusal under `require_parameters`, recorded in
  unit 1. [proposed]
- **Policies.** `_raise_for_status` raises from the response only [existing E/world/connector.py:1596-1637].
  `_observed_round_trip` holds the request body: it catches that `ResolutionError` and, when
  `body.get("logprobs") is True` and the error matches the recorded refusal, raises
  `ResolutionError(<fixed engine text>, code="logprobs_unsupported", permanent=True)` before
  `observation.failed`. Every other error keeps today's mapping. No retry. `logprobs_unsupported` is in
  `ENGINE_ERROR_CODES`, so an upstream cannot send it itself. [stated ans:Q5]; [existing E/error_text.py:63-96];
  [proposed]
- **Failure behavior.** `quorum="all"`: the Case fails with `logprobs_unsupported`. Quorum panel: the
  member is left out, and the evidence shows `missing`. The author sees the code through
  `observation.failed(code)` in the activity view (P6, approved, ans:Q12).
  [existing E/world/connector.py:250-251]; [existing E/activity/observer.py:134,160]
- **Contract tests.** LC#9–11, LC#16, RC#9.

## C4b Refusal code — aigateway OpenRouter plugin → client (conditional on unit 1)

- **Applies only when** unit 1 shows that the refusal's status and code also mean another failure.
  [stated ans:Q13]
- **Shape.** `HTTP 4xx` with `detail = {"code": "unsupported_parameters", "provider": "openrouter",
  "message": "<gateway-authored text>"}`. No provider text, as every dispatch error.
  [existing G/plugins/openrouter_provider/dispatch_errors.py:1-11]; [proposed]
- **Policies.** The plugin sets the code only for OpenRouter's refusal of a request under
  `require_parameters`. Not retried. The engine maps `unsupported_parameters` with `logprobs: true` in
  the body to `logprobs_unsupported` (C4).
- **Contract tests.** LC#20 (an aigateway unit test and an engine integration test).

## C5 Member reader — operation calls → combine step (in process)

- **Shape.** `OperationCall.reply_logprobs: ReplyLogprobs | None` (erd §3). The existing reader
  `_read_member_accounting(sources)` returns, per member, the accounting numbers and the reply
  logprobs. [existing E/world/combine.py:73-124]; [proposed]
- **Policies.** One fingerprint index for both kinds of number. A member with exactly one source call
  that matches exactly one recorded call gets its record; any other member gets None for the logprob
  values. [existing E/world/combine.py:107-124]
- **Failure behavior.** No recorder → every value None, one warning (count only).
  [existing E/world/combine.py:81-84]
- **Contract tests.** LC#7, LC#12, LC#19.

## C6 Evidence — engine → SDK (`screamingface.combine-evidence.v1`)

- **Shape.** Optional top-level `declared` (the spec `signals` map); `members[].signals` holds every
  declared name. [stated ans:Q7]
- **Policies.** Additive; absent when nothing is declared, so the bytes of every existing evidence case
  stay the same. The SDK decoder adds `declared` to `_OPTIONAL_EVIDENCE_KEYS`.
  [existing S/_evaluation/combine_evidence.py:39-80]
- **Key order.** With E4b part 2 below this part, the top-level keys are in this order: `signal`,
  `cut`, `declared`, `result`. An evidence that has only one of `cut` and `declared` keeps its bytes.
  [stated owner 2026-10-15, after the restack on part 2; pinned by `ET/test_combine_declared_exclusion.py`]
- **Failure behavior.** An SDK without the key refuses such evidence (strict key sets). The SDK and the
  engine ship together. [implied]
- **Contract tests.** DS#12, DS#15.

## C7 Cache and replay — gateway cache, frozen copy

- **Shape.** The gateway cache stores the whole reply JSON; the frozen copy keys on
  `request_digest(body)`. [existing G/core/request_cache/store.py:269-274];
  [existing E/capture_outcomes.py:93-96]
- **Policies.** A hit returns the stored body, so `reply_logprobs` gives the same numbers (LC-4). A reply
  over 1,000,000 bytes is not cached [existing G/routes/chat_cache_stage.py:322-327]. A frozen-copy
  entry over 2,000,000 bytes (request plus reply) is not stored, and the capture reports `failed`
  [existing G/config.py:158-162]; [existing G/core/frozen_copy/store.py:160-168].
- **Failure behavior.** A cache skip is a live call; the numbers can differ. A frozen-copy skip is a
  reported capture failure. [implied]
- **Contract tests.** LC#8, LC#18.

## C8 Dependency rule

The combine core (`E/combine/`) stays pure and does no I/O; the reply logprobs reach it only through
the member reader port, as the accounting numbers do. [existing E/world/combine.py:1-17] The layering
gate (`run_gates.py screamingface-engine`) enforces it. [existing .claude/sdlc.local.md]

## C9 Rebuild — url4 → SDK Python (`to_python`)

- **Shape.** `decode_combine_spec` accepts the eight E4a keys plus the optional `signals`.
  [existing S/_evaluation/combine_spec.py:19-21,143]; [existing S/url4.py:97]
- **Policies.** The rebuilt Fusion gets `signals=` back. The member params that the declaration
  injects (`logprobs`, `top_logprobs`) are dropped from the members; an authored param on a Fusion
  without such a declaration stays. [proposed] (review M1)
- **Failure behavior.** A spec with an unknown key still fails to decode, as today. [existing S/_evaluation/combine_spec.py:143]
- **Contract tests.** DS#14, DS#16, VB#11, LP#14, EN#13.
