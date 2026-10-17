# PRD: Logprob capture (engine member call → reply logprobs)

**Source:** ans:Q2, ans:Q5, ans:Q6, ans:Q8, ans:Q12, ans:Q13 · **Priority:** P0 (logprob and entropy use it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §3, §4, §6](../erd.md) · used by: [logprob](logprob.md), [entropy](entropy.md)

## 1. Flows served

This is a component PRD. No user flow drives it directly. It owns: the member call params and their
preflight, the parse of `choices[0].logprobs`, the `ReplyLogprobs` record, the member reader in the
combine step, the cache and frozen-copy rules, and the `logprobs_unsupported` failure.

## 2. Background and constraints

- v1 supports OpenRouter only, with one named model pinned in a test. Other providers fail
  visibly. [stated ans:Q2]
- When the model cannot return logprobs, the member fails with a clear code,
  `logprobs_unsupported`. No retry. [stated ans:Q5]
- Under a quorum panel the evidence shows `missing`, and the author sees the code elsewhere.
  [stated ans:Q12]
- If unit 1 shows that the gateway refusal cannot be told apart, part 3 may add a small aigateway
  change that gives the refusal its own error code. [stated ans:Q13]
- The numbers use all reply tokens: the content tokens of the final reply. [stated ans:Q6]
- `top_logprobs` is 5 by default and at most 20. [stated ans:Q8]

### 2.1 Current behavior

- Member calls are not streamed. The runner owns `stream`. [existing E/world/request_parameters.py:30-32];
  [existing G/plugins/openrouter_provider/plugin.py:253-256] (OpenRouter refuses streaming)
- The engine forwards any param it does not interpret, after `json.loads`.
  [existing E/world/request_parameters.py:172-189]
- The SDK checks each assigned model param against the gateway parameter catalog before any spend,
  and refuses a param that the catalog marks unsupported with `unsupported_model_parameter`.
  [existing S/_evaluation/model_parameters.py:153-225]; [existing S/_evaluation/candidate.py:66,760]
  (`parameter_assignments`)
- The gateway catalog does not model logprob support per model; a name that no live row lists is
  not treated as unsupported. [existing G/plugins/openrouter_provider/discovery.py:94-100]
- `_observed_round_trip` holds the request `body`, decodes the reply, keeps the accounting, then
  calls `parse_choice`. The raw reply is a local. [existing E/world/connector.py:201-234]
- `_raise_for_status` turns a non-2xx answer into `ResolutionError(code=detail.code or
  aigateway_http_<status>)`, permanent except 429 and 5xx. It sees the response only, not the request
  body. An upstream code in `ENGINE_RESERVED_CODES` is replaced by `aigateway_http_<status>`.
  [existing E/world/connector.py:1596-1637]; [existing E/error_text.py:63-96]
- On a failure, `_observed_round_trip` calls `observation.failed(exc.code)`, which reaches the
  activity observer, and writes a server log line. [existing E/world/connector.py:250-258];
  [existing E/activity/observer.py:134,160]
- `parse_choice` keeps `content`, `tool_calls`, `finish_reason`, `refusal` and a reasoning flag. It
  drops `logprobs`. [existing E/world/model_response.py:10-45]
- The terminal round of a call (no `tool_calls`) is recorded once as an `OperationCall` with its
  `signal_accounting`. [existing E/world/connector.py:1310-1325]; [existing E/operation_calls.py:24-47,152-180]
- The member reader `_read_member_accounting` finds each member's calls by fingerprint
  `(path, params)` and folds their numbers. A call with zero or several matches makes the member's
  numbers unknown. [existing E/world/combine.py:73-124]
- OpenRouter returns `choices[i].logprobs` unchanged. [existing G/plugins/openrouter_provider/plugin.py:563-585]
- The gateway forces `provider.require_parameters = true`, so OpenRouter refuses a call whose model
  cannot honor a param. [existing G/plugins/openrouter_provider/routing_policy.py:233-254]
- The gateway sanitizes upstream errors: a client sees a status and a gateway code, never the
  provider message. [existing G/plugins/openrouter_provider/dispatch_errors.py:1-11]
- The gateway cache stores the whole reply JSON, and does not store a reply over 1,000,000 bytes.
  [existing G/core/request_cache/store.py:269-274]; [existing G/routes/chat_cache_stage.py:322-327]
- A frozen-copy entry (request plus reply JSON) is at most 2,000,000 bytes. A larger entry is not
  stored, and the capture is reported as `failed`. [existing G/config.py:158-162];
  [existing G/core/frozen_copy/store.py:160-168]

**Delta.**

1. The SDK adds the injected `logprobs` and `top_logprobs` params to `parameter_assignments`, so
   the existing preflight refuses a model that the catalog marks unsupported, before any spend.
   [proposed] — WHY: the author sees the problem at once and earlier, which honors the intent of
   ans:Q5; the runtime code below covers every model the catalog does not know.
2. A new pure function `reply_logprobs(data, top_k)` reads `choices[0].logprobs.content` and returns
   a `ReplyLogprobs` or None. The connector keeps it for the terminal round and records it on the
   `OperationCall`.
3. The existing member reader in `E/world/combine.py` returns the accounting numbers AND the
   `ReplyLogprobs` of each member, from one fingerprint index. No second port. [proposed]
4. The refusal mapping lives in `_observed_round_trip`, because only it holds the request body. It
   catches the `ResolutionError` that `_raise_for_status` raises. When `body.get("logprobs") is True`
   and the error matches the refusal recorded in unit 1, it raises
   `ResolutionError(LOGPROBS_UNSUPPORTED_TEXT, code="logprobs_unsupported", permanent=True)` before
   `observation.failed`. The message is fixed engine text: "the model may not return token
   log-probabilities (sf.Logprob, sf.Entropy), or no endpoint for the model supports another member
   parameter; choose another OpenRouter model or remove that parameter" (erratum E12). It never
   carries upstream text. [stated ans:Q5]; [proposed]
5. `logprobs_unsupported` joins `ENGINE_ERROR_CODES`, so an upstream that sends this code itself is
   kept as `aigateway_http_<status>` (OME-941). [proposed] — WHY: the code vouches for engine text.

## 3. Scenarios and acceptance criteria

**Definitions [proposed].** Let the content entries be `e_1..e_n` with `e_t.logprob = l_t`.
`tokens = n`, `logprob_sum = math.fsum(l_t)` (exact summing, as `combine_signal_accounting` does
[existing E/operation_accounting.py:134-150]). The entropy rule is in [entropy](entropy.md) §3.

**Validation [proposed].** The token values and the top lists are checked apart:

- If any `l_t` is not a finite number, or is greater than 0, then `logprob_sum` is None. A
  log-probability is never positive.
- If any top entry of any position is not a finite number ≤ 0, then `entropy_mean` is None. The
  token values stay.
- The token that the model chose can be absent from its position's top-k list. That is valid; the
  entropy uses the top list only.

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

- **LC-E1** Given a member call that asked for logprobs and that the gateway refuses with the answer
  recorded in unit 1, then the call fails with `logprobs_unsupported` and the fixed engine text. With
  `quorum="all"`, the Case fails with that code. [stated ans:Q5]
- **LC-E2** Given the same refusal under a quorum panel, then the member is left out of the panel,
  and its evidence row is `status="fail"`, `reason="missing"` (the panel carries no failure code). The
  author sees `logprobs_unsupported` through `observation.failed(code)` in the activity view of the
  run. [stated ans:Q12]; [existing E/combine/spec.py:323-351]; [existing E/activity/observer.py:134,160]
- **LC-E3** Given a 200 reply with no `logprobs` (or `null`, or an empty `content` list) although the
  call asked for them, then `reply_logprobs` is None, each declared logprob value is None (missing,
  not a failure), and the engine logs one warning per combine step with the count of such members
  only. [proposed]
- **LC-E4** Given a model that the gateway parameter catalog marks as not supporting `logprobs`
  (or `top_logprobs`), then the SDK preflight refuses the candidate with
  `unsupported_model_parameter` before any call. [proposed] (orchestrator decision);
  [existing S/_evaluation/model_parameters.py:153-225]
- **LC-E5** (conditional on unit 1) Given that the gateway refusal is NOT distinct (its status and
  code also mean another failure), then the aigateway OpenRouter plugin gives the refusal under
  `require_parameters` its own gateway code `unsupported_parameters` (gateway-authored text, no
  provider text), and the engine maps that code (with `logprobs: true` in the body) to
  `logprobs_unsupported`. [stated ans:Q13]

### 3.3 Derived scenarios (risk-ordered)

- **LC-D1** (H×H) [implied] Given the logprobs, then no token string and no `bytes` array is kept,
  logged or written to evidence. Only the four numbers leave the function.
- **LC-D2** (H×M) [proposed] Given one bad token value (`-Infinity`, `NaN`, a string, or `0.3`), then
  `logprob_sum` is None. Given one bad top entry, then only `entropy_mean` is None.
- **LC-D3** (H×M) [existing E/world/combine.py:107-124] Given a member whose source call matches zero
  or several recorded calls, then its logprob values are None.
- **LC-D4** (H×M) [implied] Given a Fusion that declares nothing, then the call body, the request
  digest and the gateway cache key do not change.
- **LC-D5** (M×M) [proposed] Given a member with two or more source calls (the SDK refuses this,
  DS-I4), then the engine gives None for its logprob values (defense in depth).
- **LC-D6** (M×M) [implied] Given a provider refusal (`provider_refusal`), then no `ReplyLogprobs`
  is recorded. [existing E/world/connector.py:1392-1414]
- **LC-D7** (M×L) [implied] Given a reply over 1,000,000 bytes, then the gateway does not cache it,
  and a rerun calls the model again. The numbers of the rerun can differ.
- **LC-D8** (M×L) [proposed] Given a `top_logprobs` list longer than the k that the call asked for,
  then only the first k entries count.
- **LC-D9** (M×L) [existing G/config.py:158-162] Given a frozen-copy capture whose request plus reply
  is over 2,000,000 bytes, then the entry is not stored and the capture reports `failed`. The README
  says to keep k small when a frozen copy is needed.
- **LC-D10** (M×M) [proposed] Given an upstream answer whose `detail.code` is
  `logprobs_unsupported`, then the engine keeps `aigateway_http_<status>`, because the code is in
  `ENGINE_ERROR_CODES`. [existing E/world/connector.py:1596-1637]

## 4. Non-functional requirements

- `reply_logprobs` is O(n × k) for n reply tokens, k ≤ 20. It runs once per terminal round.
  [proposed]
- Size estimate [proposed]: one content entry is about 120 bytes of JSON, and each top entry about
  100 more. With k = 5, a reply of about 1,400 tokens stays under the 1,000,000-byte cache cap; with
  `logprob` only, about 8,000 tokens. A frozen-copy entry also holds the request, so its limit is
  near 2,800 tokens with k = 5. GSM8K replies are a few hundred tokens.
- The numbers are fail-open (a bad shape gives None and a warning with the exception type only), like
  `_signal_accounting`. [existing E/world/connector.py:1380-1389]; [proposed]
- Observability: the author sees `logprobs_unsupported` through `observation.failed(code)` and the
  activity view. The server log line (connector.py:252-258) is for operators only.
  [existing E/world/connector.py:250-258]

## 5. Out of scope

- Providers other than OpenRouter. [stated ans:Q2]
- Retry without logprobs. [stated ans:Q5]
- Keeping per-token vectors (UniTE and the span ensemble are part 8). [stated ans:Q3]
- An aigateway change other than the refusal code of LC-E5. [stated ans:Q13]

## 6. Open questions

None. The refusal branch is decided (ans:Q13): unit 1 records the answer; LC-E5 applies only if it
is not distinct.

## 7. TDD plan

Order: risk-first. Characterize the call body and the refusal, then build the parser core-out.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `call_body_without_declarations_is_unchanged` | unit | LC-D4 | H×M | passes today |
| 2 | CHAR `parse_choice_ignores_logprobs` | unit | [existing E/world/model_response.py:25-45] | M×M | passes today |
| 3 | `reply_logprobs_sums_the_content_tokens` | unit | LC-1 | H×M | pure function, `math.fsum` |
| 4 | `reply_logprobs_token_sum_is_none_for_a_bad_or_positive_value` | unit | LC-D2 | H×M | all or nothing for the sum |
| 5 | `reply_logprobs_keeps_no_token_text` | unit | LC-D1 | H×H | the dataclass has numbers only; log capture |
| 6 | `absent_logprobs_give_none_and_one_count_warning` | unit | LC-E3 | H×M | warning text holds a count only |
| 7 | `terminal_round_records_reply_logprobs_on_the_operation_call` | integration | LC-3 | H×M | connector, fake gateway |
| 8 | `cache_hit_gives_the_same_numbers` | integration | LC-4 | H×M | fake gateway replays the stored body |
| 9 | `gateway_refusal_with_logprobs_maps_to_logprobs_unsupported_with_fixed_text` | integration | LC-E1 | H×H | in `_observed_round_trip`; recorded answer from unit 1 |
| 10 | `logprobs_unsupported_is_a_declared_permanent_engine_code` (approved edits, overview §8) | unit | LC-E1, LC-D10 | H×M | `DECLARED_FAILURE_CODES`, failure class, `ENGINE_ERROR_CODES`, SDK mirror |
| 11 | `quorum_panel_member_refused_for_logprobs_is_missing_and_observed` | integration | LC-E2 | M×M | assert the `failed` observation code |
| 12 | `member_with_ambiguous_source_gets_none` | unit | LC-D3, LC-D5 | H×M | the one fingerprint index |
| 13 | `refusal_records_no_reply_logprobs` | unit | LC-D6 | M×M | — |
| 14 | `top_logprobs_longer_than_k_counts_only_k` | unit | LC-D8 | M×L | slice |
| 15 | `preflight_refuses_a_model_the_catalog_marks_without_logprobs` | unit | LC-E4 | H×M | params in `parameter_assignments` |
| 16 | `upstream_cannot_send_logprobs_unsupported_itself` | unit | LC-D10 | M×M | `ENGINE_RESERVED_CODES` |
| 17 | `bad_top_entry_erases_entropy_only` | unit | LC-D2 | H×M | two validations |
| 18 | `frozen_copy_entry_over_the_cap_reports_failed` | integration | LC-D9 | M×L | existing capture path, large fake reply |
| 19 | `member_reader_returns_accounting_and_reply_logprobs` | unit | Delta 3 | H×M | extend `_read_member_accounting` |
| 20 | (conditional, LC-E5) aigateway `openrouter_parameter_refusal_has_its_own_code` and engine `unsupported_parameters_maps_to_logprobs_unsupported` | unit + integration | LC-E5 | H×M | gateway-authored text only |

LC-2 is pinned by LP#6 and EN#8. LC-D7 is not tested offline (test-plan §5).
