# OME-791 implementation plan: HuggingFace global-cache projection

## Status

Reviewed and revised. Four independent adversarial reviews ran against the pre-review draft
(kiss-scope, wrong-hit, completeness, feasibility); one returned **reject** on a verified
wrong-model-replay hazard. Every finding was checked against this base before being accepted or
rejected here. Awaiting owner approval. The checked-in specification is
`docs/spec/2026-08-20-OME-791-huggingface-global-cache-projection.md`.

## Base, and what follows from it

Branch `OME-791-huggingface-global-cache-projection` was cut from `origin/main` at `c157ed7a`.

Three consequences of that base, each verified rather than assumed:

1. **OME-884 is NOT merged.** `openai_provider/global_cache.py`, `runtime_guard.py` and the
   model-aware participation port live only on the unmerged `OME-884-…` branch. Its module shape
   is copied here as a pattern and never imported, so there is no dependency. The exemplars that
   exist on this base are `openrouter_provider/global_cache.py` and Anthropic's in-plugin
   projection.
2. **The participation port on this base is `participates_in_global_cache(self) -> bool`** —
   `core/plugin_base/_provider.py:278`, called at `core/request_cache/global_plan.py:73` with no
   argument. OME-884 changes it to accept the requested model. This plan writes the override
   against the base it is on. When the two branches meet, the second merger adapts one signature,
   exactly as OME-884's own plan already schedules for OpenRouter ("signature-only preservation").
   Noted in the ledger Deviations so it is not a surprise.
3. **HF's provider directory is byte-identical between `origin/main` and the OME-884 branch**
   (`git diff --stat origin/main...HEAD -- …/huggingface_provider …/tests/unit/huggingface` is
   empty), so no OME-884 work is silently depended upon.

Linear is read-only for this work by explicit owner direction: OME-791 stays in Backlog, no
status transition and no close comment. Reconcile manually.

## Owner-approved MVP semantics

- Cacheable unit: non-streaming Chat Completions through the unified HF router.
- **Only a backend-pinned id is cacheable.** `huggingface/<org>/<model>:<provider|policy>`
  projects; `huggingface/<org>/<model>` bypasses.
- `default_models` publishes `/v1/models`; it is not a cache allowlist. Any route-valid
  backend-pinned id projects, listed or not. This follows the OME-884 catalog ruling.
- A hit re-checks nothing — no backend availability check, no caller-access check. Inherited
  OME-305 exact-replay behaviour, restated because it now applies to HF.
- A deployment that overrides the router base does not participate in the cache at all.

## Existing contract (verified facts this plan builds on)

- HF inherits `CacheBypass` from `ProviderPluginBase`; every `huggingface/*` request bypasses at
  the projection step today.
- All TWELVE declared rule paths carry `cache_behavior="bypass"` (ten `direct_rule` calls plus the
  `tools` and `tool_choice` pair that `function_calling_rules` emits); the standing instruction block
  at `parameters.py:46-63` names the promotion order and the test that enforces it.
- `prepare_chat_body` (`plugin.py:208-230`) pops `api_key`, sanitises/drops `extra_headers`, and
  sets `out["api_base"] = self.settings.router_api_base`. It validates no model id.
- `available_auth_modes()` is exactly `("api_key",)`, and `_AUTH` in `parameters.py` matches, so
  a keyed rule already covers every available mode.
- `huggingface_chat_parameter_rules` ignores `model` and `auth_type` and returns one `_RULES`
  tuple, which is what satisfies the auth-mode-agreement conformance sweep. Do not introduce
  per-mode branching while promoting.
- All 24 seeds in `_default_model_slugs()` are backend-pinned; `pinned_router_target` returns
  non-`None` for every one. Measured, not assumed.
- HF owns no `usage_accounting.py` and no `chat_completion` override; it inherits
  `litellm.acompletion(**body)`.
- Core enforces the projection contract in `global_eligibility._projected` (`:342-372`): the hook
  receives a deep copy, the whole call is wrapped in `except Exception`, and
  `set(produced) != {"resolved_model", "provider_adapter_revision", "prepared"}` is a bypass. An
  extra member fails exactly as hard as a missing one.
- `prepared` is hashed whole as `prepared_request` and is **not** copied by the core.
- A non-JSON-safe value in `prepared` surfaces as `canonicalization_failure`, a different
  observable reason from `provider_projection`. Do not conflate them.
- `api_base` is **not** in `EXCLUDED_TRANSPORT_FIELDS` (`{"timeout", "extra_headers", "api_key"}`),
  so a projected `api_base` genuinely participates in the key.
- `extra_headers` is in `DISPATCH_CONTROL_FIELDS` (stripped at the route) **and** in
  `EXCLUDED_TRANSPORT_FIELDS` (never keyed). A caller cannot influence it; HF's sanitisation loop
  is defence in depth against an already-impossible input. It is therefore not projected.
- Every HF rule is `projection_kind="direct"`, so no `prepared` root obligation exists and the
  `unprojected_parameter` bypass cannot arise.
- **No existing test asserts HF cache behaviour.** `grep` over `tests/unit/huggingface/` for
  `cache_behavior`, `CacheBypass` and `global_cache` returns nothing, and no generic test names HF
  as a bypassing provider — the conformance relation is computed per provider, not listed. The
  append-only impact of this unit is therefore **zero prior tests changed**.

## Design decisions

### D1 — `resolved_model` is the upstream id, keeping the backend suffix

`resolved_model = model[len("huggingface/"):]`, i.e. `<org>/<model>:<backend>`.

Argued, not copied: Anthropic projects the FULL gateway string because for Anthropic the gateway
prefix IS LiteLLM's provider prefix and reaches the wire intact, while OpenRouter and OpenAI
strip. HF strips, and the evidence is the installed transform:
`tests/unit/huggingface/test_huggingface_dispatch.py:29-46` drives
`HuggingFaceChatConfig.transform_request` and asserts the post-strip model reaches the outbound
body verbatim as `deepseek-ai/DeepSeek-R1:novita`.

Because the suffix is part of the upstream id, two backends for one repo key differently as a
structural consequence. No separate mechanism, and nothing to keep in sync.

### D2 — `prepared` is exactly the pinned router base

```python
{"api_base": OFFICIAL_ROUTER_API_BASE}
```

A fresh dict per call, because the core hashes `prepared` by reference and does not copy it
(`global_eligibility._projected` returns it uncopied); a shared module-level table would let one
reader alter every later request's key material.

WHY it participates in the key at all: `prepared` is rendered *wholesale* into the canonical
mapping. It is not filtered against `EXCLUDED_TRANSPORT_FIELDS` — that set governs the caller's
body, not the projection's output — so anything a projection returns here is key material by
construction.

**Honest accounting of its entropy.** Given D3, every *participating* deployment sends the
official base, so `api_base` discriminates nothing today. It stays for two reasons, neither of
them key entropy: it is the truthful statement of what dispatch sends, which is the projection's
whole contract; and if D3's gate is ever loosened, the key is already correct rather than
retro-fitted. `api_key` and `extra_headers` are transport and stay out, per the verified
dispositions above.

### D3 — the env-overridable router base is gated in participation, not projected from settings

This is the one structural difference from every existing projection, and the plan's central
decision. `HuggingFacePluginSettings.router_api_base` is a real field
(`AIGW_HUGGINGFACE_ROUTER_API_BASE`); OpenRouter's base is an unconfigurable module constant
(`openrouter_provider/settings.py:28`), so that provider cannot diverge and never had to solve
this.

The projection may not read it: `test_no_projection_reads_operator_configuration` substitutes a
`_PoisonedSettings` whose `__getattr__` raises on any access, and the sibling sweep poisons
`os.environ`, so both doors are closed. Ruling 34 (`_provider.py:233-247`) states the hazard
precisely — at a fixed revision, dispatch varying on state the projection cannot observe means
two identical bodies produce one key and two different upstream calls.

Ruling 34 offers two answers, and the participation port offers a third:

- *Reject: fold the constant into the revision and accept the consequence.* The accepted
  consequence would be that a deployment pointed at a proxy shares rows with one pointed at the
  official router. That is cross-endpoint contamination of a globally shared cache — the one
  class of consequence not worth accepting.
- *Reject: bypass unconditionally.* Correct but useless: it would cache nothing anywhere,
  including every normal deployment.
- **Take: gate participation.** `participates_in_global_cache` may read deployment-local state by
  design (`_provider.py:299-317`), a `False` answer is fail-safe and lossless — it suppresses the
  lookup without invalidating, rewriting or re-keying any row — and it leaves the default
  deployment fully keyed.

So the projection emits the official constant, and the hook declines when the configured base is
not the official one.

**Comparison is normalised, not literal.** `https://router.huggingface.co/v1` and
`https://router.huggingface.co/v1/` dispatch identically — litellm's
`_build_chat_completion_url` does `model_url.rstrip("/")` at `transformation.py:26-28` before
appending `/chat/completions`. A literal `!=` would therefore disable all HF caching for a
deployment whose base is functionally identical and whose upstream calls are byte-identical. The
gate compares `rstrip("/")` on both sides. Anything beyond a trailing-slash difference declines:
this is a safety gate, so the normalisation stays minimal and provably wire-equivalent rather
than becoming a URL-canonicalisation routine.

Note the sweeps cannot catch a regression here: `operator_gate_overrides` flips only `bool` fields
and `HuggingFacePluginSettings` declares none, so every sweep runs HF with the default base. The
override hazard must be pinned by an HF-local test.

### D4 — one origin for the router base, scoped to the dispatch path

Adding the projection makes the official base **key material**. A census of the HF package finds
the value spelled in **four** places, not two:

| Site | Role | In scope? |
|---|---|---|
| `settings.py:24` `_ROUTER_API_BASE` | the field default dispatch reads | **yes** — becomes key material |
| `api_key_validation.py:19` `_READINESS_URL` | credential probe target | no |
| `discovery.py:43` `MODELS_URL` | catalog listing | no |
| `discovery.py:44` `ALLOWED_ORIGINS` | catalog origin allowlist | no |

Only the first is on the dispatch path this projection describes. So the change is exactly one
rename:

- `_ROUTER_API_BASE` becomes a public `OFFICIAL_ROUTER_API_BASE`, homed in `settings.py` above the
  settings class so the pure projection can name it without importing anything impure;
- `router_api_base: str = OFFICIAL_ROUTER_API_BASE` stays as the field dispatch reads — no
  behaviour change.

**The other three are deliberately left alone.** `_READINESS_URL` is a *hardcoded literal that
must not track the settings field*: it exists so an overridden base cannot redirect a credential
probe, and `test_huggingface_validation_requires_identity_and_readiness` pins that by passing
`router_api_base="https://attacker.invalid/v1"` and asserting the probe still reaches the official
router. Deriving it from a shared constant is harmless today but couples a security-relevant
literal to a name whose whole purpose is to be configurable — so the earlier plan's edit here is
withdrawn. `discovery.py`'s two copies serve the catalog surface, carry no key material, and are
outside this unit.

Consequence recorded honestly: this unit does **not** achieve "one origin for the router base
across the package", and the DoD no longer claims it. It achieves one origin for the *dispatch
path*, which is the only origin the cache key depends on.

### D5 — no combination bypass for `logprobs` / `top_logprobs`

`validate_chat_parameter_combination` raises 400 for `top_logprobs` without `logprobs is True`,
and it runs on the miss path, after the cache read. That ordering suggests a wrong-hit — a request
the gateway must refuse being served 200 from a row. It is not one, and the reason is worth
recording because the shape recurs:

both fields are keyed, so an invalid combination keys uniquely; and a row can only exist for a
request that dispatched successfully — the fill path requires a whole answer with a
`finish_reason` (`chat_cache_stage.py:271-285`), and a 400 raised at `chat.py:418`, before
dispatch, never reaches it. An invalid combination therefore misses its own key every time and is
refused exactly as it is today. It pays one pointless cache probe; it cannot be answered.

**The invariant this rests on, stated so a future change cannot silently void it:** the conclusion
holds only while the combination predicate is a pure function of KEYED body fields. `auth_mode` is
structurally absent from the key, so a future combination rule that consulted the auth mode, the
resolved model, or any deployment state would reintroduce exactly the wrong-hit this argument
rules out — and would then need a real bypass. An `INVARIANT:` anchor beside the validator records
this.

No guard is added now. Adding one would imply a hazard that does not exist, which is its own kind
of wrong documentation.

### D6 — decline participation under unsafe ambient LiteLLM state

HF inherits base `chat_completion` = `litellm.acompletion(**body)` and adds no gateway-owned
control table, so ambient LiteLLM globals are unobservable-at-fixed-revision state of exactly the
kind ruling 34 governs.

**This decision was rewritten after review; the earlier justification was false and is withdrawn.**
The claim "both providers that already project guard this, so a projecting HF would be the only
one without" does not hold: Anthropic projects and dispatches through the same
`litellm.acompletion` with no such guard at all. The guard is justified below on the verified
mechanism instead of on precedent.

**The mechanism, verified on installed litellm 1.97.0 in this worktree's venv.**
`litellm.model_fallbacks` is read at `main.py:602` — *inside `async def acompletion`*, which spans
lines 388-698, the exact entry point HF dispatches through:

```python
fallbacks = fallbacks or litellm.model_fallbacks
if fallbacks is not None:
    response = await async_completion_with_fallbacks(...)
```

`fallback_utils.py:57,62` then re-enters `acompletion` with `model=fallback`. The gateway strips
caller `fallbacks` at ingress (`request_hardening.py:82`), so only the process global can set it,
and the fill path stores any answer carrying a `finish_reason` without comparing its model to the
key's. A single process-global setting therefore writes **another model's answer under an HF key**,
in a store whose rows have no expiry. That is not a stale answer, it is a wrong one, and it is the
reason this gate exists. Separately, `litellm.headers` reaches the HF wire specifically:
`main.py:2994`, inside `_complete_huggingface`, does `hf_headers = headers or litellm.headers`.

**The form: adopt OpenAI's existing predicate rather than invent one.**
`openai_provider/plugin.py:85-101` already encodes this check on this base, and its condition set
is a strict superset of OpenRouter's (`openrouter_provider/litellm_controls.py:55-68`) with every
member verified reachable from HF's path. HF mirrors it:

| Condition | Why it can corrupt an HF row |
|---|---|
| `model_alias_map` contains **this** model | ambient redirect fills the row from a different model |
| `model_fallbacks` truthy | the blocker above — a different model's answer under this key |
| `headers` truthy | `main.py:2994` sends them; two processes key alike and send differently |
| `proxy_auth` not None | changes the transport the answer came through |
| `pre_call_rules` / `post_call_rules` non-empty | a hit returns at `chat.py:351`, before dispatch, so a deployment's configured refusal is silently skipped for a stored row |
| `drop_params` / `additional_drop_params` truthy | change which parameters reach the wire |
| non-`"cache"` entries in any global callback list | observers that make the call not a bare generation |

The alias check uses the **exact-model** form both exemplars use (`model in aliases`), not a coarse
truthy test, so a deployment aliasing unrelated models keeps its HF caching. The port's signature
on this base receives no model argument, so the hook reads it from the settings-independent path
available to it; if that is not reachable, the coarse truthy form is the fail-safe fallback and the
narrowing is deferred to the OME-884 forward-merge, which changes this signature anyway.

**Two conditions from the earlier draft are dropped.** `litellm.cache` is already covered — a
global callback list containing only `"cache"` is explicitly permitted by both exemplars, and
LiteLLM's own replay is what `caching`/`cache` per-request controls address on providers that pin
them; HF pins none, so this gate cannot pretend to. More importantly,
`litellm.HuggingFaceChatConfig().get_config()` is withdrawn outright: `_complete_huggingface`
(`main.py:2971-3011`) reads no `*Config.get_config()`, `BaseConfig.get_config` reads only
`cls.__dict__`, so the condition cannot fire on anything reaching the HF wire — and *evaluating*
it instantiates the class, whose `__init__` does `self.__class__._is_base_class = False`, mutating
litellm process state on every request. A guard that protects nothing and mutates shared state is
strictly worse than no guard.

**Known duplication, recorded not hidden.** This makes three near-copies of the predicate
(OpenRouter, OpenAI, HF) that must stay in sync. Extracting one core helper is the right cleanup,
but the three sets are not identical — each provider's reachable surface differs — so a union plus
per-provider deltas is more design than this MVP warrants. An `AIDEV-NOTE:` at the HF copy names
the other two and the extraction as the follow-up.

Any exception inside the hook is already swallowed into non-participation by `global_plan.py:72-77`,
so the guard cannot fail a request.

### D7 — `cache_reference_from_cached_response` returns `None`

Required, not decorative. `plugins/taxonomy/session.py:374` reaches the hook through `getattr`
inside a `try`, and there is no base-class default, so a provider that omits it logs
`cache-reference mapper failed provider=huggingface` on **every** hit — an operator-visible
failure that never happened. HF contributes no usage-accounting strategy, so `None` is the honest
answer; building one is out of scope.

### D8 — the adapter revision, and what it covers

`GLOBAL_CACHE_ADAPTER_REVISION = "huggingface-global-cache-2026-08"`, homed in the new
`global_cache.py`, kept separate from `parameters.py`'s `_REVISION` (that one versions what a
caller may say and where it lands; this one versions what the boundary adds on its own).

Enumerate in the constant's comment what the JSON-hashed `prepared` cannot carry, because rows
have no expiry and survive deployments:

- installed litellm 1.97.0's HF transform passing the post-strip model to the wire verbatim;
- the `{api_base}/chat/completions` URL shape, including the `rstrip("/")` normalisation;
- `api_base is not None` winning over litellm's ambient `HF_API_BASE` / `HUGGINGFACE_API_BASE`
  fallbacks in `get_base_url` / `get_complete_url`;
- the pinned base short-circuiting `_fetch_inference_provider_mapping`, whose lru-cached,
  env-keyed lookup would otherwise make the upstream model not a function of the request;
- the ambient-state conditions of D6: this revision is only meaningful for a process where none of
  them held, which is what participation enforces.

A litellm upgrade touching any of those is a mandatory bump.

All of these were verified against the venv on THIS base (litellm 1.97.0, confirmed by
`importlib.metadata.version`): `transformation.py:94-99` shows `if api_base is not None` winning
ahead of the `elif os.getenv("HF_API_BASE") or os.getenv("HUGGINGFACE_API_BASE")` fallback, `:78`
shows the same read in `get_base_url`, and `:26-38` shows the URL construction.

### D9 — promotion

**Twelve** paths move to `cache_behavior="keyed"` in one change with the projection. Enumerated at
runtime from the live rule table on this base, not counted by eye:

`temperature`, `max_tokens`, `stop`, `response_format`, `seed`, `n`, `frequency_penalty`,
`presence_penalty`, `logprobs`, `top_logprobs`, `tools`, `tool_choice`.

The last two are why the count is twelve and not the ten `direct_rule` calls: `function_calling_rules`
emits both a `tools` and a `tool_choice` rule (`standard_parameters.py:232-252`, with
`tool_choice=True` defaulted at `:204`). It also defaults `cache_behavior="bypass"`
(`standard_parameters.py:205`) and HF's call at `parameters.py:167` omits the argument, so flipping
the ten `direct_rule` calls is not enough — the helper must be passed `cache_behavior="keyed"`
explicitly.

`_REVISION` bumps to `"huggingface-2026-08"`. `top_p` stays observed-but-unruled: a
bypass-to-keyed promotion cannot enable a parameter no rule enables.

**Caller-visible contract change, verified.** The published model-parameter contract digests a
per-rule string including `cache_behavior` and `projection_revision`
(`core/model_parameter_contract.py:78`), so promoting the rules and bumping `_REVISION` changes the
`contract_id` / `context.revision` digests for every HF model, and every HF model's detail document
starts reporting `gateway.cache_behavior: keyed` on twelve rows. That is correct — the contract
genuinely changed — and it breaks no test, because no test pins a literal digest and none asserts
`"huggingface-2026-07"` (searched `src` and `tests`). But "breaks no test" is also the problem: the
caller-visible surface flips with nothing asserting it. This unit adds one assertion that an HF
model's served contract detail reports `keyed` for a promoted path, so the flip is proven rather
than merely unobjected-to. Consumers that cache the contract by digest see one change, once.

The standing instruction block at `parameters.py:46-63` is replaced by a note recording what was
done. Its closing sentence names Anthropic and OpenRouter as the only projecting providers, which
is accurate on this base (OME-884 is unmerged) and becomes stale by *this* change — so updating it
is this unit's job, not housekeeping. Identical blocks in the ollama, antigravity, codex and gemini
plugins are **out of scope** and deliberately left alone.

### D10 — streaming needs no HF work

Verified, so the plan does not have to defend it: streaming is refused by the core, ahead of and
independently of any provider. `TRUTHY_BYPASS_REASONS = {"stream": BYPASS_STREAM}`
(`global_eligibility.py:88-92`) is applied at `:180`, while `_projected` runs at `:406`, and the
constant carries the invariant "streaming stays structurally ineligible here even if a provider
rule ever declared otherwise". HF's streaming path therefore cannot read or write a row, before or
after this change.

Because HF's streaming path is live, the route test asserts this once for HF specifically —
`stream: true` yields reason `stream` and stores no row — rather than resting on a core guarantee
no HF test exercises.

### D11 — what an operator will see, and its known limit

A refusal publishes `X-AIGW-Cache-Reason: provider_projection` in **all** of these cases: HF has no
projection, HF is pointed at a non-official router (D3), and any ambient-LiteLLM condition fired
(D6). They are indistinguishable on the wire.

That is deliberate and not this unit's decision to change. `global_plan.py:89-105` records why a
plan-level `disabled` may not be returned instead — it is re-mapped downstream to
`cache_unavailable`, which would tell an operator their cache store is broken when it is healthy —
and its AIDEV-NOTE records that a dedicated `provider_disabled` reason is the right long-term
answer but is an owner decision, because the vocabulary is a caller-visible contract that URL4
reads and `test_global_cache_reason_vocabulary._WIRE_CONTRACT` owns.

**Mitigation inside this unit's scope, and it is not optional.** With eight decline paths
collapsing onto one wire reason and nothing logged, an operator whose HF caching silently stopped
has no way to learn why. The participation hook logs, at most once per condition per process, a
reason TOKEN naming which check declined — never the configured URL value, never a header value,
never any credential. An operator then has a diagnosable signal in logs with no change to the wire
vocabulary. A test asserts the token appears once and that the configured base value does not.

### D12 — profile defaults are already inside the key

Not a change, but load-bearing and previously unstated. Two of the twelve newly-keyed paths —
`max_tokens` and `temperature` — are exactly the fields stored as `ProfileDefaults`, and the
ruling-57 merge happens *before* the cache lookup: `build_global_cache_plan` receives the body
"after the body-wins profile-default merge" (`global_plan.py:60-64`). So the key describes the
**effective** request, and two callers whose stored defaults differ key differently even when their
wire bodies are identical. That is the correct behaviour and it is what makes promoting these two
paths safe; it is recorded here because a reader could otherwise assume the key sees only the raw
body.

### D13 — the licensing dimension of cross-account replay (owner decision, flagged)

HF has one property no other projecting provider has: most seeds in `_default_model_slugs()` are
**gated repositories** whose access requires per-HF-account license acceptance. Exact replay is
cross-account by design (`global_plan.py:5-9`), and a hit re-checks nothing — so a row filled by an
account that accepted a model's license can be served to an account that never did.

This is the same accepted-consequence class OME-884 recorded for OpenAI ("a hit performs no
availability and no access check"), but the consequence is qualitatively different: OpenAI's is an
access-control question inside one vendor relationship, whereas this one touches a third party's
licensing terms. It is therefore written down as an explicit **owner decision**, not silently
accepted by an implementer:

- the spec records it as an ACCEPTED CONSEQUENCE with this reasoning visible;
- implementation proceeds, because it is inherent to the approved exact-replay semantics rather
  than introduced by this unit's design;
- if the owner declines it, the remedy is a seed-list or gating decision at the catalog level, not
  a projection change — so it does not block or reshape the work below.

Raised explicitly in the completion report rather than buried in a doc.

## Deliberately not built

Named so the reviewer can see the KISS boundary was chosen, not missed: no HF `usage_accounting.py`;
no `chat_completion` override, no gateway dispatch-control table and no per-request pinning of
`num_retries` / `caching` (both exemplars do this; HF's MVP declines participation instead of
pinning the wire, which is fail-safe and smaller); no extraction of the shared ambient-state
predicate into core (D6 records why); no new bypass reason (the vocabulary is a wire contract and
minting one is an owner decision); no core port change; no dispatch-side model validation added to
`prepare_chat_body`; no edit to `discovery.py` or `api_key_validation.py` (D4); no change to the
sibling providers' stale comment blocks; no edit to the shared conformance census (see below).

## Test-first implementation sequence

Two new test files, not four — matching the one-cache-file-per-provider precedent the OpenRouter
and OpenAI projections both follow.

### Unit 1 — the pure projection

RED in `tests/unit/huggingface/test_huggingface_global_cache_projection.py`:

- a backend-pinned id projects; the return set is exactly the three members;
- `resolved_model` is the prefix-stripped id and **retains** `:<backend>` — asserted directly on
  the projection's output, since the key-difference test cannot prove this (see the test matrix);
- `prepared == {"api_base": OFFICIAL_ROUTER_API_BASE}`, a fresh container per call;
- determinism, and no mutation of the passed body;
- bypass for: missing `model`, non-string `model`, a non-`huggingface/` prefix, a slug
  `_validate_model_slug` rejects (including the forbidden provider-as-path-segment form), and an
  **unsuffixed** id;
- every bypass carries `PROJECTION_BYPASS_REASON`;
- totality — no input raises;
- the projection reads no settings (HF-local, in addition to the registry sweep, because the
  sweeps run HF with default settings only);
- bumping `GLOBAL_CACHE_ADAPTER_REVISION` changes the key hash;
- participation: default settings participate; a trailing-slash base still participates; a
  genuinely different base does not; each D6 condition declines; a clean process participates; a
  raising guard degrades to non-participation; the decline token is logged once and carries no
  configured value;
- `cache_reference_from_cached_response` returns `None`.

GREEN: `global_cache.py` (revision constant + `project_global_cache_request` only — no dispatch
helper), the `OFFICIAL_ROUTER_API_BASE` rename in `settings.py`, and the three plugin hooks. Do not
touch `parameters.py` yet — the promotion is refused by the conformance sweep until the projection
exists, and that ordering is the guard rail.

**`resolved_model` is derived, not re-implemented.** `pinned_router_target(slug)` already answers
exactly the projection's question, returning `(repo, backend)` or `None`, and its own docstring
claims single-definition ownership of the predicate. So the projection is
`repo, backend = target; f"{repo}:{backend}"` — no new `cacheable_upstream_model` helper, because a
second predicate is the drift the OpenRouter projection deliberately avoids. One guard is required
first: `pinned_router_target` raises `AttributeError` on a non-string (probed on this base with
`None`, `123`, `{}`, `[...]` — all raise on `.startswith`), so the projection tests
`isinstance(model, str)` before calling it. The core's `_projected` would swallow the raise, but the
projection's own contract is TOTAL and the totality test asserts no raise.

**Tripwire, observed to fire.** Neutralise the unsuffixed-id bypass, run the unsuffixed test, and
record the observed symptom (a real key hash) in the AIDEV-NOTE beside the guard, then restore it.
This is the repo's existing discipline, used at exactly two sites today.

**Tripwire, observed to fire.** Fill a row with the default base, then override the base and prove
the row is not replayed — a gate that only stops new writes would pass a test that never stored
anything. Record the observed symptom.

### Unit 2 — promotion, key differences, and the route

RED in `tests/unit/huggingface/test_huggingface_route_global_cache.py`:

- every one of the twelve newly-keyed paths: equal effective values collide, different values do
  not, driven through `build_global_cache_plan()` so rules, auth modes, participation and
  projection are exercised together;
- different repos, and different `:<backend>` suffixes for one repo, do not collide;
- a meta-test deriving the keyed set from the live rules and asserting equality against a literal
  **twelve**-member set, so no future keyed path can land without a key-difference proof. Mirrors
  `test_every_openrouter_keyed_path_has_an_explicit_key_difference_proof`; without it the promotion
  is unguarded;
- an HF-local floor: every registered HF model contributes exactly twelve keyed instances, derived
  from the plugin rather than from a literal count, so it is environment-independent;
- one assertion that a served contract detail document reports `gateway.cache_behavior: keyed` for
  a promoted path (D9);
- route: identical eligible requests produce `miss -> hit`, one dispatch, one row;
- route: a hit performs **no `aigateway:huggingface:*` credential read or decrypt, no auth-mode
  resolution, no key injection and no provider dispatch**. The one profile-index read — itself a
  `credential_blobs` row plus a master-key decryption — is explicitly ALLOWED, per the AIDEV-NOTE
  at `chat_profile_defaults.py:68-71` that documents it as the accepted pre-cache cost;
- route: `stream: true` yields reason `stream` and stores no row (D10);
- route: an unsuccessful provider response stores nothing;
- route: an unsuffixed id dispatches normally and never reads or writes cache;
- route: caller opt-out bypasses.

This module is **not** in `tests/unit/conftest.py`'s `_LEGACY_API_KEY_ROUTE_MODULES` frozen
allowlist, so it exercises the real API-key validation service and must install its own explicit
double. Enable the cache with the established pattern — an env fixture setting
`AIGW_REQUEST_CACHE_ENABLED=true` installed before app construction, a `cache_client` fixture that
logs in, and the contract-shaped in-memory store — copied from the closest working exemplar,
`tests/unit/test_chat_global_cache_route.py:112-124`.

GREEN: promote the twelve rules and bump `_REVISION`.

Standing, green on arrival: the registry purity sweeps,
`test_a_provider_that_declares_a_keyed_rule_backs_it_with_a_real_projection`, and
`test_a_bare_request_is_cacheable_exactly_when_the_provider_has_a_projection` — the last is an
iff, so HF must not merely avoid bypassing but actually key end-to-end for all 24 seeds.

### No housekeeping edit to the shared conformance file

The earlier plan proposed refreshing `test_global_cache_registry_conformance.py`'s census prose and
leaving its `_OBSERVED_NON_BYPASS_INSTANCES = 72` floor. Both halves were wrong, and the item is
withdrawn:

- *comment-only* would leave a `>=` floor at 72 while HF alone adds 24 x 12 = 288 instances, so the
  guard could no longer notice HF regressing;
- *raising the floor* makes a shared, append-only-protected test file depend on catalog and
  environment state — the count is not stable across deployments, and this unit predicts zero prior
  test changes.

The guard HF needs is HF-local and stronger: the per-model twelve-instance assertion in Unit 2,
derived from the plugin. The shared file is left untouched.

## Planned files

Production, all under `apps/aigateway/src/aigateway/plugins/huggingface_provider/`:

- `global_cache.py` — NEW. `GLOBAL_CACHE_ADAPTER_REVISION` and
  `project_global_cache_request(body)`. Nothing else. Target well under the 450-line limit.
- `settings.py` — rename `_ROUTER_API_BASE` to public `OFFICIAL_ROUTER_API_BASE` (D4).
- `plugin.py` — three hooks: projection, participation (D3 + D6 + the D11 log), cache reference.
- `parameters.py` — twelve paths to `keyed`, `_REVISION` bump, replaced instruction block.

Tests, both under `apps/aigateway/tests/unit/huggingface/`:

- `test_huggingface_global_cache_projection.py` — NEW (projection, participation, hit metadata)
- `test_huggingface_route_global_cache.py` — NEW (promotion, key differences, route, contract)

No shared test file is edited.

Durable artifacts: the `docs/tasks/`, `docs/spec/`, `docs/plan/` and `docs/work/` files dated
2026-08-20.

Must not change without returning to owner review: the cache key schema; the caller-visible reason
vocabulary; `routes/chat.py` and `routes/chat_cache_stage.py`; request-cache persistence, models
or migrations; dependency manifests or lockfiles; `core/plugin_base/_provider.py` and
`core/request_cache/global_plan.py`; `api_key_validation.py` and `discovery.py`; and Anthropic,
OpenRouter, Codex or Gemini behaviour.

## Verification

From `apps/aigateway`:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python scripts/check_no_enterprise.py
uv run pytest --cov=aigateway --cov-fail-under=80 -q
```

Focused, from `apps/aigateway`:

```sh
uv run pytest tests/unit/huggingface -q
uv run pytest tests/unit/test_global_cache_projection_purity.py \
  tests/unit/test_global_cache_registry_conformance.py \
  tests/unit/test_global_cache_key.py \
  tests/unit/test_global_cache_plan.py \
  tests/unit/test_chat_global_cache_route.py -q
```

No append-only exception is expected. If the append-only check reports one, STOP: this plan predicts
zero prior-test changes, so a failure means the prediction was wrong and the diff needs review
before an exception is even considered.

Diff review before reporting completion:

```sh
git diff --stat origin/main -- apps/aigateway docs
git diff --check origin/main
wc -l apps/aigateway/src/aigateway/plugins/huggingface_provider/global_cache.py
git status --short
```

`git diff` omits untracked files: read every intended new file directly and reconcile against
`git status --short`.

## Test matrix

| Acceptance claim | Proof |
|---|---|
| Backend-pinned exact replay | Route `miss -> hit`, one dispatch, one row |
| Backend suffix survives into `resolved_model` | Direct assertion on the projection's `resolved_model` |
| Two backends for one repo do not collide | Key-difference test on the two ids |
| Unsuffixed never caches | Projection bypass + route probe/write assertions + observed tripwire |
| Malformed never caches | Bypass per rejected-slug class, same predicate as the slug grammar |
| Projection is pure | Registry sweeps + HF-local poisoned-settings test |
| Projection is total | No input raises, including non-string `model` |
| `prepared` is complete | Exactly the pinned base; fresh container; JSON-safe |
| Revision abandons a generation | Monkeypatched revision changes the key hash |
| Overridden base cannot share rows | Fill-then-override tripwire, row preserved, not replayed |
| Trailing-slash base still participates | Normalised-comparison test |
| Ambient LiteLLM state cannot poison | One participation test per D6 condition |
| Every keyed path is proven | Twelve per-path key-difference tests + derived-set meta-test |
| HF cannot silently stop contributing | Per-model twelve-keyed-instance assertion |
| Contract flip is visible | Served detail document reports `keyed` for a promoted path |
| Streaming stays ineligible for HF | Route asserts reason `stream`, no row |
| Hit does no provider-credential work | No `aigateway:huggingface:*` read/decrypt, no auth-mode resolution, no injection, no dispatch; the profile-index read is allowed |
| Profile defaults are inside the key | Two callers with different stored defaults key differently |
| Failures never stored | Provider error yields zero rows |
| Hit metadata is quiet and truthful | No mapper warning; `None` reference |
| A decline is diagnosable | Decline token logged once, carries no configured value |
| Other providers unaffected | Full gate; no core or sibling-plugin change in the diff |

## Stop conditions

Return to owner review rather than broadening scope if:

- the projection would need settings, environment, credential, identity or I/O to be correct;
- an existing test must change (the plan predicts none);
- correctness appears to require a core port change, a route-order change, a new bypass reason, or
  a dispatch-side refusal HF does not have today;
- the ambient-state guard cannot be expressed on the participation hook alone — in particular, if
  declining participation turns out not to prevent a `model_fallbacks` process from writing rows,
  the guard must move to dispatch and that is a scope change;
- promotion turns out to need per-mode rule branching;
- OME-884 merges mid-flight and the participation signature change is more than mechanical.

## Definition of done

- Linear, task mirror, spec, plan and ledger agree; Linear itself untouched by direction.
- HF projects for all 24 seeds and for any route-valid backend-pinned id; unsuffixed and malformed
  ids bypass.
- All **twelve** rule paths keyed, each with a key-difference proof, guarded by the derived-set
  meta-test and the per-model instance floor.
- The projection is pure, total, non-mutating, JSON-safe, identity-free and credential-free.
- An overridden router base and each ambient LiteLLM hazard decline participation losslessly, and
  each decline logs a diagnosable token.
- A hit performs no HF provider-credential read or decrypt, no auth-mode resolution, no key
  injection and no dispatch; the single profile-index read remains the accepted pre-cache cost.
- One origin for the router base **on the dispatch path**; the validation and discovery copies are
  documented as deliberately separate.
- The caller-visible contract flip is asserted, not merely unobjected-to.
- Zero prior tests modified; no core, schema, migration, dependency, route or shared-test change.
- Focused tests and the full AIGateway gate green; ledger Outcome filled with actual files, gates
  and deviations before handoff.
