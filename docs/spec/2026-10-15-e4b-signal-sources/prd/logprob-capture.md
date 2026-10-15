# PRD: Logprob capture (engine member call → reply logprobs)

**Source:** ans:Q2, ans:Q5, ans:Q6, ans:Q8 · **Priority:** P0 (logprob and entropy use it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §3, §4, §6](../erd.md) · used by: [logprob](logprob.md), [entropy](entropy.md)

## 1. Flows served

This is a component PRD. No user flow drives it directly. It owns: the member call params, the
parse of `choices[0].logprobs`, the `ReplyLogprobs` record, the reader that gives each member its
numbers in the combine step, the cache-hit rule and the `logprobs_unsupported` failure.

## 2. Background and constraints

- v1 supports OpenRouter only, with one named model pinned in a test. Other providers fail
  visibly. [stated ans:Q2]
- When the model cannot return logprobs, the member fails with a clear code,
  `logprobs_unsupported`. No retry. [stated ans:Q5]
- The numbers use all reply tokens: the content tokens of the final reply. [stated ans:Q6]
- `top_logprobs` is 5 by default and at most 20. [stated ans:Q8]

### 2.1 Current behavior

- Member calls are not streamed. The runner owns `stream`. [existing E/world/request_parameters.py:30-32];
  [existing G/plugins/openrouter_provider/plugin.py:253-256] (OpenRouter refuses streaming)
- The engine forwards any param it does not interpret, after `json.loads`.
  [existing E/world/request_parameters.py:172-189]
- `_observed_round_trip` decodes the body, keeps the accounting, then calls `parse_choice`. The
  raw body is a local. [existing E/world/connector.py:201-234]
- `parse_choice` keeps `content`, `tool_calls`, `finish_reason`, `refusal` and a reasoning flag. It
  drops `logprobs`. [existing E/world/model_response.py:10-45]
- The terminal round of a call (no `tool_calls`) is recorded once as an `OperationCall` with its
  `signal_accounting`. [existing E/world/connector.py:1310-1325]; [existing E/operation_calls.py:24-47,152-180]
- The combine adapter finds each member's calls by fingerprint `(path, params)` and folds their
  numbers. A call with zero or several matches makes the member's numbers unknown.
  [existing E/world/combine.py:73-124]
- OpenRouter returns `choices[i].logprobs` unchanged: the plugin does `model_dump()` and removes
  only `openrouter_metadata`. [existing G/plugins/openrouter_provider/plugin.py:563-585]
- The gateway forces `provider.require_parameters = true`, so a model that cannot honor a param
  makes OpenRouter refuse the call instead of dropping the param.
  [existing G/plugins/openrouter_provider/routing_policy.py:233-254]
- The gateway sanitizes upstream errors: a client sees a status and a gateway code, never the
  provider message. [existing G/plugins/openrouter_provider/dispatch_errors.py:1-11]
- The engine turns a non-2xx gateway answer into `ResolutionError(code=detail.code or
  aigateway_http_<status>)`, permanent except 429 and 5xx. [existing E/world/connector.py:1595-1637]
- The gateway cache stores the whole response JSON, and does not store a response over
  1,000,000 bytes. [existing G/core/request_cache/store.py:269-274];
  [existing G/routes/chat_cache_stage.py:322-327]; [existing G/config.py:154-155]

**Delta.** A new pure function `reply_logprobs(data, top_k)` reads `choices[0].logprobs.content`
and returns a `ReplyLogprobs` or None. The connector keeps it for the terminal round and records it
on the `OperationCall`. A new reader port in the combine step gives each member its
`ReplyLogprobs` by the same fingerprint match as the accounting reader. A gateway refusal of a
call that asked for logprobs maps to `logprobs_unsupported`.

## 3. Scenarios and acceptance criteria

**Definitions [proposed].** Let the content entries be `e_1..e_n` with `e_t.logprob = l_t`.
`tokens = n`, `logprob_sum = math.fsum(l_t)` (exact summing, as `combine_signal_accounting` does
[existing E/operation_accounting.py:134-150]). The entropy rule is in [entropy](entropy.md) §3.

### 3.1 Happy path

- **LC-1** Given a reply whose content logprobs are `-0.1, -0.2, -0.3`, then `tokens = 3` and
  `logprob_sum = -0.6` exactly (with `math.fsum`; a plain `sum` gives `-0.6000000000000001`).
  [stated ans:Q6]
- **LC-2** Given a Fusion that declares `logprob`, then each member call body has `logprobs: true`
  and no `top_logprobs`. With `entropy` k = 5, the body also has `top_logprobs: 5`. [stated ans:Q8]
- **LC-3** Given a tool loop of three rounds, then the numbers come from the terminal round only.
  [proposed]
- **LC-4** Given a gateway cache hit on the same request, then the numbers equal the numbers of the
  original call, bit for bit. [implied]; [existing G/core/request_cache/store.py:269-274]

### 3.2 Error paths

- **LC-E1** Given a member call that asked for logprobs and that the gateway refuses with the
  answer recorded in unit 1 (the "no endpoint supports the requested parameters" refusal), then the
  call fails with `ResolutionError(code="logprobs_unsupported", permanent=True)`. With
  `quorum="all"`, the Case fails with that code. [stated ans:Q5]
- **LC-E2** Given the same refusal under a quorum panel, then that member is left out of the panel,
  and its evidence row is `status="fail"`, `reason="missing"` (the panel carries no failure code),
  while the run failure log names `logprobs_unsupported`. [existing E/combine/spec.py:323-351];
  [proposed]
- **LC-E3** Given a 200 reply with no `logprobs` (or `null`, or an empty `content` list) although
  the call asked for them, then `reply_logprobs` is None, and each declared logprob value is None
  (missing, not a failure). [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **LC-D1** (H×H) [implied] Given the logprobs, then no token string and no `bytes` array is kept,
  logged or written to evidence. Only the four numbers leave the function.
- **LC-D2** (H×M) [implied] Given a non-finite `logprob` (`-Infinity`, `NaN`) or a non-number,
  then the whole `ReplyLogprobs` is None (I-S2), never a partial sum.
- **LC-D3** (H×M) [existing E/world/combine.py:107-124] Given a member whose source call matches zero
  or several recorded calls, then its logprob values are None.
- **LC-D4** (H×M) [implied] Given a Fusion that declares nothing, then the call body, the request
  digest and the gateway cache key do not change.
- **LC-D5** (M×M) [proposed] Given a member with two or more source calls (should not pass the SDK
  check, DS-I4), then the engine gives None for its logprob values (defense in depth).
- **LC-D6** (M×M) [implied] Given a provider refusal (`provider_refusal`), then no
  `ReplyLogprobs` is recorded. [existing E/world/connector.py:1392-1414]
- **LC-D7** (M×L) [implied] Given a reply over 1,000,000 bytes, then the gateway does not cache it,
  and a rerun calls the model again. The numbers of the rerun can differ. Visible as a cache miss.
- **LC-D8** (M×L) [proposed] Given a `top_logprobs` list longer than the k that the call asked for,
  then only the first k entries count.

## 4. Non-functional requirements

- `reply_logprobs` is O(n × k) for n reply tokens, k ≤ 20. It runs once per terminal round.
  [proposed]
- Size estimate [proposed]: one content entry is about 120 bytes of JSON, and each top entry
  about 100 more. With k = 5, a reply of about 1,400 tokens stays under the 1,000,000-byte cache cap;
  with `logprob` only, about 8,000 tokens. GSM8K replies are a few hundred tokens.
- The new code is fail-open for the numbers (bad shape → None, a warning with the exception type
  only), like `_signal_accounting`. [existing E/world/connector.py:1380-1389]; [proposed]
- Observability: the existing "model call failed … code=" line names `logprobs_unsupported`.
  [existing E/world/connector.py:236-246]

## 5. Out of scope

- Providers other than OpenRouter. [stated ans:Q2]
- Retry without logprobs. [stated ans:Q5]
- Keeping per-token vectors (UniTE and the span ensemble are part 8). [stated ans:Q3]
- A gateway change, unless unit 1 shows that the refusal cannot be told apart (see §6).
  [proposed]

## 6. Open questions

1. The exact gateway answer to an OpenRouter refusal under `require_parameters` is not known. No
   recorded fixture exists. Unit 1 records it on the local stack (`~/sf-local`, engine, aigateway and
   OpenRouter). If the answer has a status and code that only this refusal uses, the engine maps
   that pair when the body has `logprobs: true`. If the code is generic (for example the same
   `provider_error` 404 as an unknown model), a small aigateway change gives the refusal its own
   gateway code. Default: map in the engine; escalate to the owner if a gateway change is needed,
   because it touches another stack.

## 7. TDD plan

Order: risk-first. Characterize the call body and the refusal, then build the parser core-out.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `call_body_without_declarations_is_unchanged` | unit | LC-D4 | H×M | passes today |
| 2 | CHAR `parse_choice_ignores_logprobs` | unit | [existing E/world/model_response.py:25-45] | M×M | passes today |
| 3 | `reply_logprobs_sums_the_content_tokens` | unit | LC-1 | H×M | pure function |
| 4 | `reply_logprobs_is_none_for_a_non_finite_or_bad_entry` | unit | LC-D2 | H×M | all or nothing |
| 5 | `reply_logprobs_keeps_no_token_text` | unit | LC-D1 | H×H | the dataclass has numbers only; log capture |
| 6 | `reply_logprobs_is_none_when_logprobs_are_absent` | unit | LC-E3 | H×M | — |
| 7 | `terminal_round_records_reply_logprobs_on_the_operation_call` | integration | LC-3 | H×M | connector, fake gateway |
| 8 | `cache_hit_gives_the_same_numbers` | integration | LC-4 | H×M | fake gateway replays the stored body |
| 9 | `gateway_refusal_with_logprobs_maps_to_logprobs_unsupported` | integration | LC-E1 | H×H | recorded answer from unit 1 |
| 10 | `logprobs_unsupported_is_a_declared_permanent_failure` (approved edit of `ET/test_e4b_catalog_pins.py:13-20`) | unit | LC-E1 | H×M | `DECLARED_FAILURE_CODES`, failure class, SDK mirror |
| 11 | `quorum_panel_member_refused_for_logprobs_is_missing` | integration | LC-E2 | M×M | — |
| 12 | `member_with_ambiguous_source_gets_none` | unit | LC-D3, LC-D5 | H×M | reuse the fingerprint index |
| 13 | `refusal_records_no_reply_logprobs` | unit | LC-D6 | M×M | — |
| 14 | `top_logprobs_longer_than_k_counts_only_k` | unit | LC-D8 | M×L | slice |

LC-2 is pinned by LP#6 and EN#8. LC-D7 is not tested offline (test-plan §5).
