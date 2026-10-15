# Contracts: E4b part 3, signal sources v1

One section per connection. Path prefixes as in [erd](erd.md).

## C1 Declaration — SDK → engine, combine spec `signals` (url4 intent, JSON)

- **Shape.** Optional top-level key of `screamingface.combine-spec.v1` (additive, no new id):

  ```json
  "signals": {
    "<name>": {"source": "logprob", "form": "mean" | "sum" | "prob"}
            | {"source": "entropy", "top_logprobs": 1..20}
            | {"source": "verbalized", "pattern": "<RE2, 1..256 chars, >= 1 group>", "ignore_case": false}
  }
  ```

  `<name>` matches `^[a-z][a-z0-9_]{0,31}$`, is not an E4a key, and does not start with
  `logprob`, `entropy`, `verbalized` or `consistency`. At most 8 names, at most one `entropy`.
  [stated ans:Q1]; [proposed] (rules)
- **Policies.** The spec is closed (`extra="forbid"`) [existing E/combine/spec.py:82-84]. `weights`,
  a reduce arg or the signal read may name a declared name; the key check moves from
  `is_signal_key(key)` to `is_signal_key(key) or key in spec.signals` at the plan level
  [existing E/combine/endpoint.py:381-397]. Without the key, the bytes do not change. [implied]
- **Failure behavior.** Any rule break is `combine_spec_invalid`, and the message never echoes a
  name or a pattern. [existing ET/test_combine_spec.py:335-347]
- **Contract tests.** DS#9, DS#10, VB#4, EN#6, RC#2–6.

## C2 Request params — SDK → url4 member call → engine → gateway body

- **Shape.** Member params `logprobs=true` and, with `entropy`, `top_logprobs=<k>`. The engine sends
  `"logprobs": true, "top_logprobs": k` in the chat body. [existing S/_evaluation/policy.py:18-29];
  [existing E/world/request_parameters.py:172-189]
- **Policies.** The params are part of the call fingerprint `(path, params)` that `sources` use
  [existing S/_evaluation/combine_sources.py:20-30] and part of the gateway cache key
  [existing G/plugins/openrouter_provider/parameters.py:241-256]. `top_logprobs` without `logprobs`
  is refused by the gateway [existing G/plugins/openrouter_provider/plugin.py:312-318]; the SDK never
  emits it alone. [implied]
- **Failure behavior.** See C4.
- **Contract tests.** LC#1, LP#6, EN#8.

## C3 Reply logprobs — gateway → engine (HTTP response, OpenAI shape)

- **Shape.**

  ```json
  {"choices": [{"message": {...}, "logprobs": {"content": [
    {"token": "...", "logprob": -0.1, "bytes": [..], "top_logprobs": [{"token": "...", "logprob": -0.1, "bytes": [..]}]}
  ]}}]}
  ```

  The engine reads only `logprob` and `top_logprobs[].logprob`. [proposed]
- **Policies.** Untrusted input: each value must be a finite number; any other shape gives
  `ReplyLogprobs = None` for that call, with a warning that names the exception type only.
  [proposed]; [existing E/world/connector.py:1380-1389] (fail-open precedent)
- **Failure behavior.** No `logprobs` in a 200 reply → None (LC-E3). Not a member failure.
- **Contract tests.** LC#3–6, LC#14, EN#1–5, against the fixture recorded in unit 1.

## C4 Refusal — gateway → engine (HTTP 4xx) → failure code

- **Shape.** The gateway answer to an OpenRouter refusal under `require_parameters`. Not yet known:
  unit 1 records it on the local stack. [proposed]; see [logprob-capture](prd/logprob-capture.md) §6
- **Policies.** When the request body has `logprobs: true` and the answer matches the recorded
  refusal, the engine raises `ResolutionError(code="logprobs_unsupported", permanent=True)`. Every
  other error keeps today's mapping [existing E/world/connector.py:1595-1637]. No retry.
  [stated ans:Q5]
- **Failure behavior.** `quorum="all"`: the Case fails with `logprobs_unsupported`. Quorum panel: the
  member is left out (`missing`). [existing E/combine/spec.py:323-351]
- **Contract tests.** LC#9–11, RC#9.

## C5 Reply logprobs reader — operation calls → combine step (in process)

- **Shape.** `OperationCall.reply_logprobs: ReplyLogprobs | None` (erd §3). A new port
  `LogprobReader(sources) -> {member: ReplyLogprobs | None}` beside `AccountingReader`.
  [existing E/world/combine.py:73-124]; [proposed]
- **Policies.** The same fingerprint index as the accounting reader. A member with exactly one source
  call that matches exactly one recorded call gets its record; any other member gets None.
  [existing E/world/combine.py:107-124]
- **Failure behavior.** No recorder → every value None, one warning (count only).
  [existing E/world/combine.py:81-84]
- **Contract tests.** LC#7, LC#12.

## C6 Evidence — engine → SDK (`screamingface.combine-evidence.v1`)

- **Shape.** Optional top-level `declared` (the spec `signals` map); `members[].signals` holds every
  declared name. [stated ans:Q7]
- **Policies.** Additive; absent when nothing is declared, so the bytes of every existing evidence
  case stay the same. The SDK decoder adds `declared` to `_OPTIONAL_EVIDENCE_KEYS`.
  [existing S/_evaluation/combine_evidence.py:39-80]
- **Failure behavior.** An SDK without the key refuses such evidence (strict key sets). The SDK and the
  engine ship together. [implied]
- **Contract tests.** DS#12, DS#15.

## C7 Cache and replay — gateway cache, frozen copy

- **Shape.** The gateway cache stores the whole response JSON; the frozen copy keys on
  `request_digest(body)`. [existing G/core/request_cache/store.py:269-274];
  [existing E/capture_outcomes.py:93-96]
- **Policies.** A hit returns the stored body, so `reply_logprobs` gives the same numbers (LC-4). A
  reply over 1,000,000 bytes is not cached. [existing G/routes/chat_cache_stage.py:322-327]
- **Failure behavior.** A cache skip is a live call; the numbers can differ. [implied]
- **Contract tests.** LC#8.

## C8 Dependency rule

The combine core (`E/combine/`) stays pure and does no I/O; the reply logprobs reach it only through
the reader port, as the accounting numbers do. [existing E/world/combine.py:1-17] The layering gate
(`run_gates.py screamingface-engine`) enforces it. [existing .claude/sdlc.local.md]
