# PRD: N independent samples of one model

**Source:** prompt (OME-1289 §2), ans:Q11, ans:Q13 · **Priority:** P1 (added by ans:Q11)
**Lifecycle:** planned (the engine-side seed handling exists and is characterized)
**Owner:** unassigned
**Landing:** `packages/screamingface` only
**Uses:** [reducer-slot.md](reducer-slot.md) (the members feed any reducer)

## 1. Summary and user story

As a researcher, I want `samples(model, N)` to build N calls of one model that are N real answers,
not one cached answer counted N times, so that a vote over samples is honest. `[stated prompt]`

## 2. Background and constraints

- "`samples(model, N)` builds N calls that differ in seed. Optional: temperature, a list of
  prompts, a list of languages." `[stated prompt]`
- "The response cache must key on that difference. N copies of the same request are one request."
  `[stated prompt]`
- "The N calls are ordinary Fusion members after that. They do not define a new join."
  `[stated prompt]`
- samples() is in P1 `[stated ans:Q11]`.
- samples() works only for models whose provider accepts `seed`. Other models fail at compile time
  `[stated ans:Q13]`.

### 2.1 Current behavior

- A call that sets its own `seed` keeps it. The run's ambient seed applies only when the call has
  none `[existing apps/screamingface-engine/src/screamingface_engine/world/request_parameters.py:86]`.
- The aigateway cache key includes the keyed request parameters
  `[existing apps/aigateway/src/aigateway/core/request_cache/global_keys.py:128]`.
- The Anthropic provider rejects `seed` on purpose
  `[existing apps/aigateway/src/aigateway/plugins/anthropic_provider/discovery.py:23]`. The
  OpenRouter, Gemini, Hugging Face, and Ollama plugins list `seed`
  `[existing apps/aigateway/src/aigateway/plugins/openrouter_provider/parameters.py:211]`.
- The engine serves one model's parameter contract at `GET /v1/model-parameters?model=…`
  `[existing apps/screamingface-engine/src/screamingface_engine/rest/catalog.py:177]`.

**Delta (SDK only).**

```python
sf.samples(model, n, *, seeds=None, temperature=None, prompts=None, params=None) -> tuple[Model, ...]
```

- Member i gets `params["seed"] = str(seeds[i] if seeds else i)` `[proposed]`.
- `prompts`, when given, has length n, and member i uses `prompts[i]` `[stated prompt]`.
- `temperature`, when given, is set on every member `[stated prompt]`.
- A "list of languages" is a list of prompts. There is no separate argument `[proposed]`.
- Check before submit: the model's parameter contract must list `seed` as supported. If not,
  raise `ValueError("<model> does not support seed; samples() needs a seed-capable model")`
  `[stated ans:Q13]`.
- Duplicate guard: when any reducer Fusion has two members with the same model, prompt, and
  params, the SDK warns with `DuplicateMembersWarning` `[proposed — default for ans:Q11]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**SM-H1 Five seeded members.** `[stated prompt]`
Given `samples("openrouter/<model>", 5)`,
When it is called,
Then it returns five `Model`s with seeds "0" to "4" and the same model and prompt.

**SM-H2 Five cache keys.** `[stated prompt]`
Given a candidate `Fusion(samples(m, 5), synthesizer=Vote(...))` on a seed-capable model,
When one case runs against the gateway (recorded fixture),
Then the gateway receives five requests with five different cache keys.

**SM-H3 Prompt variants.** `[stated prompt]`
Given `samples(m, 3, prompts=[p_en, p_fr, p_de])`,
When it is called,
Then member i uses prompt i and seed i.

### 3.2 Error paths

**SM-E1 Model without seed.** `[stated ans:Q13]`
Given `samples("anthropic/claude-sonnet-5", 5)`,
When the candidate compiles,
Then the SDK raises `ValueError`, and no request is sent.

**SM-E2 Wrong lengths.** `[proposed]`
Given `samples(m, 3, prompts=[a, b])` or `seeds=[1, 1, 2]`,
When it is called,
Then it raises `ValueError` (length mismatch, or duplicate seeds).

**SM-E3 N out of range.** `[proposed]`
Given `n = 0` or `n > 256`,
When it is called,
Then it raises `ValueError`.

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| SM-D1 | Run seed does not override the sample seed | [existing apps/screamingface-engine/src/screamingface_engine/world/request_parameters.py:86] | H×M | Given a run with `X-Answer-Seed: 7` and `samples(m, 3)`, when the calls go out, then the seeds are 0, 1, 2. |
| SM-D2 | Duplicate members warn | [proposed — default for ans:Q11] | H×M | Given `Fusion([m, m, m], synthesizer=Vote())`, when it compiles, then `DuplicateMembersWarning` names the duplicates. |
| SM-D3 | Contract unavailable | [proposed — gap §per-connection/sync] | M×L | Given `GET /v1/model-parameters` fails, when samples() is compiled, then the SDK raises `EngineUnavailableError`. It does not assume seed support. |
| SM-D4 | Gateway rejects seed anyway | [implied] | M×L | Given the contract said yes but the gateway rejects `seed`, when the call runs, then the case fails with `model_parameter_invalid` (existing code). |
| SM-D5 | Replay | [stated prompt] | M×M | Given the same run twice with the cache on, when the second run executes, then all five answers come from the cache, and the vote is identical. |

## 4. Non-functional requirements

- samples() adds no new request type. It adds at most one contract lookup for each model and each
  client session (cached) `[proposed]`.

## 5. Out of scope

- A gateway-owned sample key for providers without seed `[stated ans:Q13]`.
- Variation by input transform (image augmentation) `[stated prompt]`.

## 6. Open questions

1. Duplicate guard form. ans:Q11 put samples() in P1 but did not pick warn or reject. Default:
   warn (`DuplicateMembersWarning`). Change it to an error if you prefer.

## 7. TDD plan (outside-in)

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| SM-1 | CHAR `call_seed_wins_over_run_seed` | unit (engine) | [existing apps/screamingface-engine/src/screamingface_engine/world/request_parameters.py:86] | H×M | passes today |
| SM-2 | `samples_builds_n_models_with_seeds_0_to_n_minus_1` | unit | [stated prompt] | H×M | list comprehension |
| SM-3 | `samples_rejects_model_without_seed_support` | unit | [stated ans:Q13] | H×M | contract lookup |
| SM-4 | `five_samples_produce_five_gateway_cache_keys` | integration (recorded gateway) | [stated prompt] | H×M | seed in keyed params |
| SM-5 | `duplicate_members_in_reducer_fusion_warn` | unit | [proposed] | H×M | compare (model, prompt, params) |
| SM-6 | `samples_prompts_and_seeds_length_and_uniqueness_checks` | unit | [proposed] | M×M | validation |
| SM-7 | `samples_n_bounds` | unit | [proposed] | M×L | 1 ≤ n ≤ 256 |
| SM-8 | `contract_lookup_failure_raises_engine_unavailable` | unit | [proposed] | M×L | no assumption |
| SM-9 | `samples_vote_replays_identically_from_cache` | integration | [stated prompt] | M×M | no new code; pin it |
| SM-10 | `gateway_seed_rejection_fails_with_model_parameter_invalid` | integration | [implied] | M×L | existing code path; pin it |
