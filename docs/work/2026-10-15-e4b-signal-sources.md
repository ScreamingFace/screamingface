---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo, aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-15
finished:
---

# e4b-signal-sources — E4b part 3, signal sources v1

One ledger for the whole part. The plan is
[docs/plan/2026-10-15-e4b-signal-sources.md](../plan/2026-10-15-e4b-signal-sources.md). The spec is
[docs/spec/2026-10-15-e4b-signal-sources/](../spec/2026-10-15-e4b-signal-sources/00-overview.md).
Each unit has its own section below.

## Unit 1 — characterize the gateway

### Intent

Record the two gateway answers that the logprob parser (C3) and the refusal mapping (C4) use, before
any product code. Make a small number of live calls to the local aigateway (cost cap: 10 calls,
`max_tokens` ≤ 64, `top_logprobs` ≤ 5, one synthetic prompt, total < 0.05 USD). Pick the pinned
model for RC#8 and a refusing model for RC#9. Decide the D1 branch. If the refusal is not distinct
(LC-E5), give it the aigateway code `unsupported_parameters` (C4b, LC#20).

### Planned changes

- `apps/screamingface-engine/tests/unit/data/logprobs/*.json`: the trimmed reply with `logprobs` and
  `top_logprobs`, and the refusal answer with its status.
- LC-E5 branch only: `apps/aigateway/src/aigateway/plugins/openrouter_provider/` (a detector for the
  OpenRouter parameter refusal and a gateway-authored error), and a new aigateway unit test.
- This ledger.

### Test plan

- LC-E5 branch only (LC#20, aigateway half): a new test file. A transport 404 from OpenRouter with
  the parameter-refusal text gives `404` with `detail.code == "unsupported_parameters"`, gateway
  text only, no provider text. Other 404 refusals (`max_price`, data policy, unknown model) keep
  `provider_error`. The embedded HTTP-200 shape keeps today's mapping. RED first.

### Acceptance

- The fixtures exist, have no id, `_aigw`, provider, model or header, and the token text is
  synthetic.
- The ledger names the pinned model, the refusing model, the refusal status and code, the D1
  branch, the number of live calls and the total cost.
- The repo gate is green (and the aigateway gate on the LC-E5 branch).

### Unit 1 note — the recorded gateway answers (2026-10-15)

Local stack: aigateway at `127.0.0.1:9105` (`~/sf-local`), OpenRouter. All calls used `curl` to
`POST /v1/chat/completions`, the prompt "What is 2+3? Reply with the number only.",
`max_tokens: 16`.

| # | Model | Body extras | Gateway | Cost (`_aigw` direct_cost) |
|---|---|---|---|---|
| 1 | `openrouter/openai/gpt-4o-mini` | `logprobs: true`, `top_logprobs: 5` | 200, one token, five top entries | 0.0000036 |
| 2 | `openrouter/anthropic/claude-haiku-4.5` | `logprobs: true`, `top_logprobs: 5` | 404 `provider_error` "The upstream provider returned an error." | none (refused) |
| 3 | `openrouter/anthropic/claude-haiku-4.5` | none (control) | 200 | 0.000045 |
| 4 | `openrouter/anthropic/claude-haiku-4.5` | `logprobs: true`, `top_logprobs: 5` | 404 `unsupported_parameters` (temporary gateway from this worktree, port 9115, on a copy of the local database; stopped and deleted after the call) | none (refused) |

- **Live calls:** 4 (cap 10). **Total cost:** 0.0000486 USD (cap 0.05).
- **Pinned model (RC#8):** `openrouter/openai/gpt-4o-mini`. It returns `logprobs.content[]` with
  `token`, `bytes`, `logprob` and `top_logprobs[]` (5 entries), plus `logprobs.refusal: null`. The
  one token had `logprob: 0.0`, so the parser must accept 0 (the C3 rule "finite and ≤ 0").
- **Refusing model (RC#9):** `openrouter/anthropic/claude-haiku-4.5`. The gateway catalog
  (`GET /v1/model-parameters`) marks `logprobs` and `top_logprobs` as `supported`
  (source `openrouter:static`), so the SDK preflight (LC-E4) does not stop it and the runtime path
  runs. Call 3 shows that the refusal comes from `logprobs`.
- **Refusal before LC-E5:** HTTP 404, `detail.code = "provider_error"`, text "The upstream provider
  returned an error.". The accounting attempt shows a transport failure
  (`failure_code: provider_status_error`), so the plugin re-raised a litellm `NotFoundError`.
- **D1 branch: LC-E5 (NOT distinct).** The route maps every upstream 404 to `provider_error`
  (`G/routes/chat_dispatch.py`, `_provider_error_code`). The same status and code also mean a
  `max_price` refusal, a zero-data-retention or data-policy refusal and a missing upstream model
  (pinned in `test_openrouter_routing_policy_routes.py` and
  `test_openrouter_no_eligible_endpoint.py`). Thus the engine cannot read it as a logprobs refusal.
- **LC-E5 change:** the OpenRouter plugin gives the transport 404 parameter refusal the code
  `unsupported_parameters` (status 404, gateway text "No upstream endpoint for this model supports
  every requested parameter.", not retried). Call 4 shows that the detector matches the live
  refusal. Unit 3 maps `unsupported_parameters` (with `logprobs: true` in the body) to
  `logprobs_unsupported` (the engine half of LC#20).
- **Fixtures** (`apps/screamingface-engine/tests/unit/data/logprobs/`), each `{"status", "body"}`:
  - `openrouter_reply_with_logprobs.json`: call 1. Content is `SYNTHETIC-ANSWER`; tokens are
    `tok0`, `tok0_alt1`..`tok0_alt4` (the `bytes` match the new text); the numbers, `finish_reason`
    and the token counts in `usage` are as recorded.
  - `openrouter_refusal_provider_error.json`: call 2, the answer before LC-E5.
  - `openrouter_refusal_unsupported_parameters.json`: call 4, the answer after LC-E5.
  - Removed: `id`, `_aigw`, `provider`, `system_fingerprint`, `created`, `model`, `object`,
    `service_tier`, `choices[].index`, `choices[].provider_specific_fields`, `message.role`,
    `message.tool_calls`, `message.function_call`, `message.provider_specific_fields`,
    `usage.is_byok`, `usage.cost`, `usage.cost_details` (removed by the review fixes), and every
    header. No provider text is in the refusal bodies.

### Unit 1 outcome

- **Actual files:** as planned. aigateway: `G/plugins/openrouter_provider/response_errors.py`
  (`is_parameter_refusal`, the detector), `G/plugins/openrouter_provider/dispatch_errors.py`
  (`_unsupported_parameters_error`, gateway text only), `G/plugins/openrouter_provider/plugin.py`
  (the transport branch of `chat_completion`), new test
  `apps/aigateway/tests/unit/openrouter/test_openrouter_parameter_refusal_code.py` (9 cases: two
  phrasings get the new code and one upstream call; five other 404 texts, a 400 with the same
  words and the embedded HTTP-200 shape keep their mapping). Engine: the three fixtures. This
  ledger.
- **RED:** the two new-code cases failed (`provider_error` != `unsupported_parameters`); the seven
  "keep the mapping" cases passed before and after (they pin what must not change).
- **Commits:** `feat(aigateway): give the OpenRouter parameter refusal its own code (E4b part 3
  unit 1)`, then `test(screamingface-engine): record the gateway logprobs reply and refusal (E4b
  part 3 unit 1)`.
- **Gates:** `run_gates.py aigateway --base 0f4b9e292` ALL GATES GREEN (append-only, ruff, format,
  pyright, no-enterprise, pytest with coverage ≥ 80). `run_gates.py repo --base 0f4b9e292` ALL
  GATES GREEN.
- **Pinned edits:** none. No existing test changed.
- **Deviations:** (1) Call 4 used a temporary gateway from this worktree (port 9115, on a copy of the
  local database) to prove the detector on the live refusal; the copy was deleted after the call.
  (2) The gateway health path is `/healthz`, not `/health` (`/health` gives 404). (3) The
  embedded HTTP-200 shape of the refusal keeps `provider_error`: an existing test pins it, and the
  live refusal is the transport shape. (4) The exact OpenRouter text is not visible through the
  gateway; the detector matches two fixed phrasings, and call 4 shows that one of them matches.
  The paid test RC#9 (unit 5) checks it again.

### Unit 1 review fixes (2026-10-15)

No live call. The fixes use only the recorded answers.

- **Intent.** Close the review findings for unit 1.
- **Planned changes.**
  - `G/plugins/openrouter_provider/provenance.py`: move `is_parameter_refusal` here from
    `response_errors.py`. It now also requires `classify_provenance(exc) is
    ErrorProvenance.TRANSPORT`, so it is correct without help from its caller.
  - `G/plugins/openrouter_provider/plugin.py`: import from `provenance`; raise the new error
    `from exc` (as the embedded branch above it does), so a server-side traceback keeps the
    litellm exception. The response is gateway text either way.
  - `G/plugins/openrouter_provider/dispatch_errors.py`: the docstring says what a client can do
    with the code, not what the engine does with it.
  - `apps/aigateway/tests/unit/openrouter/test_openrouter_parameter_refusal_code.py`: one local
    `_as_transport(exc, *, wire_status)` helper (the shape of the sibling
    `test_openrouter_no_eligible_endpoint.py`) for the 404 and the 400 cases; a new direct test
    of the detector on a 404 with the refusal text but no transport chain.
  - `ET/data/logprobs/openrouter_reply_with_logprobs.json`: remove `usage.is_byok` (an account
    fact), `usage.cost` and `usage.cost_details` (no later unit reads them).
- **Test plan.** RED first: the new direct test fails before the detector checks provenance.
  The nine existing cases stay green.

### Unit 1 review fixes — outcome

- **RED:** `test_the_detector_needs_a_proven_transport_failure` failed before the move:
  `AssertionError: assert True is False` (`is_parameter_refusal` of a `NotFoundError` with no
  transport chain). It passed after the detector checked provenance.
- **Code name `unsupported_parameters` (MAJOR finding): decision (a), keep the name.** Spec C4b
  sets the name, and a rename needs a spec erratum. The gateway already uses this code for a
  different answer: the parameter classifier (`G/routes/chat.py:621`,
  `G/routes/chat_profile_defaults.py:89`) sends HTTP **400** with a `rejected` map when the catalog
  does not enable a parameter. The new refusal is HTTP **404** with no `rejected` key. Thus the code
  alone is NOT distinct; the status and the code together are.
  - **Rule for unit 3 (replaces the rule "`unsupported_parameters` + `logprobs: true` ->
    `logprobs_unsupported`" above):** the engine maps to `logprobs_unsupported` only when the
    status is **404** AND `detail.code == "unsupported_parameters"` AND the body asked for
    `logprobs: true`. A 400 `unsupported_parameters` keeps its current mapping.
  - **Unit 3 adds an engine test** (with LC#20): a 400 `unsupported_parameters` with a `rejected`
    map on a call with `logprobs: true` (for example a disabled `temperature` or
    `provider_params.top_k`) keeps its current mapping and is NOT `logprobs_unsupported`.
  - **Owner decision pending:** approve (a) as a note on C4 and C4b, or choose (b), a distinct
    code (for example `no_endpoint_for_parameters`) with a spec erratum.
- **Other fixes:** the detector moved to `G/plugins/openrouter_provider/provenance.py` and
  requires a proven transport failure; `plugin.py` raises the new error `from exc`;
  `dispatch_errors.py` says what a client can do with the code; the test file has one
  `_as_transport` helper and one new direct test (10 cases now); the logprobs fixture has no
  account or cost data.
- **Commit:** `fix(screamingface-engine): review fixes for E4b part 3 unit 1`. One commit, as the
  run asked; the RED line above is the record of RED first. Later units commit RED separately, as
  part 1 did.
- **Gates:** `run_gates.py aigateway --base 0f4b9e292` ALL GATES GREEN (append-only, ruff, format,
  pyright, no-enterprise, pytest with coverage >= 80). `run_gates.py repo --base 0f4b9e292` ALL
  GATES GREEN.
- **Pinned edits:** none. No test from before this part changed.

### Open items (owner)

1. The `unsupported_parameters` name decision above ((a) kept; approve or choose (b)).
2. The embedded HTTP-200 shape of the parameter refusal still gives `provider_error` (deviation
   (3) of unit 1). C4b does not limit the shape, and the test plan rates this risk H×H. To close
   it: approve it as a C4b erratum, OR allow a pinned edit of
   `test_no_eligible_endpoint_embedded_in_a_200_body_surfaces_sanitized` in a later unit, and
   change `test_the_embedded_http_200_parameter_refusal_keeps_its_mapping` with it.
3. At PR-open, replace "E4b part 3" in the gateway comments (`provenance.py`,
   `dispatch_errors.py`, `plugin.py`) with the OME id.
