# OME-884 spec — direct OpenAI global exact-response cache

Status: approved (owner-approved MVP semantics, 2026-08-19).
Ticket: OME-884 (parent OME-787). Depends on OME-864, merged as `bab02e3e` via PR #630.

## 1. Problem

OME-864 shipped direct `openai/*` API-key dispatch for non-streaming Chat Completions. The
provider inherits `ProviderPluginCore.global_cache_projection`, which returns `CacheBypass`, so
no `openai/*` request has ever been eligible for the global exact-request cache (OME-305). Its
one enabled ordinary parameter, `max_tokens`, declares `cache_behavior="bypass"` for the same
reason. Benchmark suites re-running identical direct-OpenAI calls therefore pay full price every
time.

OME-864 also restricts dispatch to `default_models`. That list is the bootstrap catalog
published by `/v1/models`; using it as a dispatch allowlist prevents callers from addressing any
other model OpenAI actually serves.

## 2. Owner-approved MVP semantics

1. Every syntactically valid route-legal `openai/*` model is directly dispatchable and globally
   cacheable.
2. `OpenAIPluginSettings.default_models` is only the bootstrap `/v1/models` catalog. It is not a
   dispatch allowlist and not a cache allowlist.
3. A locally configured or directly addressed custom model follows the same miss/store/hit path
   as a default model.
4. Removing a model from `default_models` removes it from the published catalog only. Direct
   calls and successful cached replay remain available.
5. OpenAI validates model existence and caller access **only on a cache miss**.
6. A cache hit intentionally does not re-check current provider availability or caller access.
7. Exact replay may therefore return a previously successful row after a model disappears
   upstream or becomes unavailable to the current caller. This is accepted.
8. Runtime model discovery is out of scope and will later update only the published catalog.
9. Gateway-owned aliases are out of scope. Provider-published aliases are ordinary model IDs.
10. Ambient process-global `litellm.model_alias_map` redirects are unsupported and fail closed
    for the exact requested model only.

## 3. Model identity

A route-valid direct OpenAI model ID starts with `openai/` and carries exactly one bounded ASCII
model token: 1..128 characters drawn from `[A-Za-z0-9._-]`, first character alphanumeric. This is
the grammar `OpenAIPluginSettings` already enforces; OME-884 does not widen it.

One pure predicate expresses this and is shared by settings validation, `prepare_chat_body()`,
the projection, the parameter rules and API-key readiness validation. Fine-tuned or private IDs
whose syntax the current validator rejects (e.g. `ft:gpt-4o:acme::abc123`) stay out of scope;
admitting them would require a separate cross-account replay decision because such IDs are
account-specific.

## 4. Key material

`global_cache_projection(body)` returns the closed mapping the core requires:

- `resolved_model` — the UPSTREAM model id, i.e. the caller's model with LiteLLM's `openai/`
  provider prefix removed (`openai/gpt-5.6-sol` -> `gpt-5.6-sol`). LiteLLM strips that prefix
  exactly once on its way to the wire, so the stripped token is the identity OpenAI actually
  resolves — which is what this member is for. This matches the OpenRouter convention, and is
  pinned at the final HTTP payload by `tests/unit/openai/test_openai_dispatch`. The caller's
  gateway-prefixed string is not lost: the core keys it separately as `requested_model`, so both
  identities are in the key and a prefix change could never silently share a row.
- `provider_adapter_revision` — `GLOBAL_CACHE_ADAPTER_REVISION`.
- `prepared` — the JSON-safe output-affecting state this boundary adds before dispatch.

`prepared` describes: the pinned official API base, Chat-Completions-only routing (the Responses
API bridge suppressed), LiteLLM request-level cache disabling, and zero gateway-level retries.

Non-JSON transport guarantees cannot live in `prepared` and are folded into the adapter revision
instead: `Omit()` sentinels suppressing `OpenAI-Organization` / `OpenAI-Project`, the
request-local `AsyncOpenAI` client, `max_retries=0` on that client, and the httpx client's
`verify=True` / `trust_env=False` / `follow_redirects=False`. The revision is also coupled to the
exact installed LiteLLM behaviour (1.97.0), because stored rows survive deployments.

Suppressing the organization and project headers is the explicit condition that licenses
cross-account replay: two accounts sending the identical effective request produce byte-identical
upstream calls, so one stored row is correct for both.

The projection returns `CacheBypass` for a malformed or non-OpenAI model ID and for nothing else.

### Identity exclusion

Account, profile, auth mode, organization, project, credential and user identity never enter key
material. The port's signature is `(self, body)`, enforced registry-wide.

## 5. Participation and dispatch refusal

`ProviderPluginBase.participates_in_global_cache()` gains the raw requested model as its single
argument. `build_global_cache_plan()` passes `body.get("model")` without reordering any existing
gate. Default providers ignore it and still return `True`; OpenRouter ignores it and preserves
its `settings.enabled` gate.

OpenAI refuses participation **and** dispatch through one shared, total, fail-closed, model-free
core when any of the following holds:

- `litellm.OpenAIConfig.get_config()` is non-empty (LiteLLM merges those keys into
  `optional_params` for every OpenAI call);
- the `OPENAI_CUSTOM_HEADERS` environment variable is non-empty;
- an existing unsafe LiteLLM callback, fallback, header, proxy-auth, rule or routing global is
  active (the OME-864 set);
- `litellm.secret_manager_client` is not `None` — an ambient secret manager can resolve the
  experimental-handler flag and other values outside the environment, so the flag check below
  stops being authoritative;
- `EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER` is set true, which swaps the dispatch handler and
  therefore the wire behaviour the adapter revision pins.

The flag is parsed by a total helper equivalent to
`isinstance(value, str) and value.strip().lower() == "true"`, which matches installed LiteLLM's
`get_secret_bool` -> `str_to_bool` semantics on the environment branch: only `"true"`
(case-insensitively, after stripping) is true; `"false"` and unrecognised values are not; unset
is `None`.

Ambient aliases are deliberately asymmetric: participation bypasses only when the exact requested
model is a key in `litellm.model_alias_map`, and dispatch preserves OME-864's existing per-request
alias refusal. An unrelated alias must not disable OpenAI.

Any exception inside participation is non-participation, never a request failure.

### The ambient request modifier — the one deliberate asymmetry (owner decision, cycle 2)

`litellm.modify_params` is NOT part of the shared core above, and that is a decision rather than an
omission. Installed LiteLLM 1.97.0 defines it as `bool(os.getenv("LITELLM_MODIFY_PARAMS", False))`,
so any non-empty value enables it — `"false"` and `"0"` included. When enabled it replaces
`kwargs["max_tokens"]` with a locally computed ceiling on the `acompletion` path, for every
provider, *after* this gateway has built the cache key. Since `max_tokens` is direct OpenAI's one
enabled and KEYED parameter, an enabled modifier means the number in the key is not the number that
reaches OpenAI.

Crucially, LiteLLM's modifier branch requires `kwargs.get("max_tokens") is not None`. A request
without a ceiling is therefore untouched, and refusing it would be an outage this gateway invented.
So the two decisions are scoped differently:

- **Cache participation — always declined while the flag is enabled.** The participation port
  receives only the raw model and cannot see whether this request carries a ceiling, so it declines
  for the whole provider. No row is read and no row is written.
- **Live dispatch — refused only when the effective `max_tokens` is not `None`.** That refusal is
  the existing sanitized, non-retryable `503 unsafe_openai_environment`, raised before API-key
  removal, before client construction and before `acompletion`. A profile-defaulted ceiling counts
  as present, because profile defaults are merged into the body before the cache stage (OME-305
  ruling 57). An explicit `max_tokens: null` counts as absent, matching LiteLLM's own test.
- **Live dispatch with no effective ceiling — still served**, merely uncached.

These two are *cache bypass* and *conditional dispatch refusal*: different decisions with different
triggers, not one predicate read twice. The asymmetry runs in the safe direction by construction —
participation ends up strictly stricter than dispatch, so no state exists in which a stored row
answers a request dispatch would have refused. Over-declining participation costs cache reuse;
over-permitting it would cost correctness.

Existing rows are preserved, not deleted or re-keyed: they remain exactly correct for any runtime
that is not modifying anything, and become reachable again as soon as the flag is cleared. An
unreadable or missing flag counts as ENABLED — the opposite of the sibling ambient reads, whose
missing values default to safe — because this flag's absence from the guard was the original defect.

Both decisions emit an operator `logger.warning` naming `litellm.modify_params` and the
`LITELLM_MODIFY_PARAMS` truthiness trap. The caller-facing 503 stays sanitized, so the log is the
only diagnostic an operator gets; it carries no model, message, profile, account or credential.

`GLOBAL_CACHE_ADAPTER_REVISION` does NOT change for this fix. The commit that introduced direct
OpenAI caching is unpushed and has never been deployed, so no poisoned rows can exist anywhere, and
the fix makes a modifying runtime non-participating rather than altering the wire semantics of a
safe one. That rationale is limited to the undeployed state and does not license skipping a bump
later.

## 6. Parameter contract

`max_tokens` becomes `cache_behavior="keyed"` for every route-valid `openai/*` model, in the same
increment as the real projection, with a bumped projection revision. The key therefore carries
both the model and the effective `max_tokens`, so requests cannot collide even though LiteLLM
maps the field to `max_tokens` for GPT-4/4o and to `max_completion_tokens` for GPT-5/o-series.
That mapping is pinned at the final HTTP wire for all fourteen default models, each with an
explicit committed expectation rather than a spelling-agnostic check, so a LiteLLM upgrade that
moves even one model between the two spellings fails by name.

`max_tokens` is also a stored `ProfileDefaults` field, and the body-wins defaults merge runs
before cache planning, so the key already sees the effective value. Explicit and defaulted equal
values share one entry; different profile defaults isolate.

Keying `max_tokens` is a precondition of `chat_cache_stage._is_a_whole_answer` storing
`finish_reason: "length"` rows; with `bypass` those rows would be a wrong-hit class.

## 7. Cache-hit metadata

`OpenAIProviderPlugin.cache_reference_from_cached_response()` returns `None`. Direct OpenAI
certifies no historical accounting evidence for a replayed row, so a hit renders cache status
without a false "cache-reference mapper failed" warning and accounting stays unsupported on both
hits and misses.

## 8. Non-goals and invariants preserved

No change to: the cache key schema, the caller-visible cache reason vocabulary, `routes/chat.py`,
`routes/chat_cache_stage.py`, request-cache persistence/store/models, migrations, dependency
manifests or lockfiles, or Codex/Anthropic/OpenRouter behaviour beyond the mechanical
participation-signature adaptation.
