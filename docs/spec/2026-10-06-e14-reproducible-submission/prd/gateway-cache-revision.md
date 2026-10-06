# PRD: Gateway cache revision, registry and replay controls (component)

**Source:** prompt / ans:Q1, ans:Q2, ans:Q3 · **Priority:** P0 (Stack B base; highest risk)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned · **Landing:** `apps/aigateway` · **PRs:** B1

## 1. Summary and the flows it serves

This component gives each cached response a **cache revision** label. It keeps every old label
computable, and it adds two request controls for replay. Two flows use it:

- `prd/cache-version-capture.md`: a run reads the label on each response.
- `prd/reproduce.md`: a replay sends `only-if-cached` and `cache-revision`.

No single flow owns the label rules or the registry, so they live here.

## 2. Background and constraints

- "A submission records the cache version that belongs to it." `[stated prompt]`
- "If more than one cache version exists, the run API can name the one you want." `[stated prompt]`
- "if the cache version or method changes, old submissions could still be replayed using the old
  caching approach" `[stated ans:Q1]`. The owner chose "Keep old key functions" over a data backfill
  and over "accept breakage". `[stated ans:Q1]`
- "Regarding the only-if-cached, keep it." `[stated ans:Q2]`
- Core never imports plugins. Wiring goes through a registry. (CLAUDE.md, Architecture.)

### 2.1 Current behavior

- The key is a sha256 over the request facts plus revision constants. It has no identity in it
  `[existing apps/aigateway/src/aigateway/core/request_cache/global_keys.py:257]`.
- `KEY_REVISION = "aigw-global-chat-cache-2026-08"` (`global_keys.py:104`) and
  `PARAMETER_CONTRACT_REVISION = "aigw-parameter-contract-2026-08b"` (`global_keys.py:117`) are
  inside the hash. `build_global_cache_key` already accepts `parameter_contract_revision` as a
  parameter (`global_keys.py:257`).
- Each provider plugin returns `provider_adapter_revision` from `global_cache_projection`
  `[existing apps/aigateway/src/aigateway/core/plugin_base/_provider.py:206]`. The current values:
  - openai `openai-global-cache-2026-08`
    `[existing apps/aigateway/src/aigateway/plugins/openai_provider/global_cache.py:61]`
  - openrouter `openrouter-global-cache-2026-08d` (`openrouter_provider/global_cache.py:66`)
  - huggingface `huggingface-global-cache-2026-08` (`huggingface_provider/global_cache.py:63`)
  - anthropic: computed from the Claude Code attribution constants
    `[existing apps/aigateway/src/aigateway/plugins/anthropic_provider/plugin.py:58]`
- Most adapter bumps record a **wire** change (headers, LiteLLM behaviour). The projection code
  stays the same `[existing apps/aigateway/src/aigateway/plugins/openai_provider/global_cache.py:29]`.
- A core registry of revision constants already exists. Snapshot export and upload use it
  `[existing apps/aigateway/src/aigateway/core/request_cache/revisions.py:34]`. Only openrouter
  registers its adapter revision today (`openrouter_provider/global_cache.py:75`). `KEY_REVISION` is
  not in `active_cache_revisions()`.
- The `cache` body object accepts only `use-cache`. An unknown or malformed field becomes a
  **bypass**, which calls the provider
  `[existing apps/aigateway/src/aigateway/core/request_cache/global_controls.py:61]`.
- The cache lookup runs before credential resolution
  (`[existing apps/aigateway/src/aigateway/routes/chat.py:366]` before `:405`). So a hit needs no
  provider credential.
- Response headers today: `X-AIGW-Cache`, `-Reason`, `-Write`, `-Key`
  `[existing apps/aigateway/src/aigateway/routes/chat_cache_stage.py:51]`.
- The Tavily lane has its own key and constant (`TAVILY_RETRIEVAL_CONTRACT_REVISION`,
  `[existing apps/aigateway/src/aigateway/core/request_cache/tavily_retrieval.py:64]`) and its own
  lookup and fill routes
  `[existing apps/aigateway/src/aigateway/routes/tavily_retrieval_cache.py:189]`.
- The earlier cache policy spec rejected `only-if-cached` because "one uncached leaf failing the
  whole run is a footgun with no present use case"
  `[existing docs/spec/2026-08-05-url4-cache-policy-spec.md:523]`. **Delta:** E14 is that use case,
  and it uses `only-if-cached` only for replay. The engine still drops a user's `only-if-cached`
  directive in `Cache-Control` (`cache_intent.py:114`). E14 does not change this.

### 2.2 Delta

1. **Cache revision label (B1).** `cr-` + 12 hex of the sha256 of the canonical JSON of
   `{key_revision, parameter_contract, tavily_retrieval, <adapter>: <revision>…}`. The gateway
   computes it at startup, from `active_cache_revisions()` plus `key_revision`. All four providers
   register their adapter revision. `[proposed]`
2. **Header (B1).** Every `/v1/chat/completions` response that ran the cache stage carries
   `X-AIGW-Cache-Revision: <label>`, and so does every Tavily lookup response. On a replay with an
   old label, the header carries that old label. `[proposed]`
3. **Registry (B1).** `core/request_cache/revision_registry.py` holds the entries
   (`erd.md` §4). The registry has one entry today: the current label. `[proposed]`
4. **Key function for a label (B1).** `cache_key_for(label, provider, body, …)` runs the projection
   (the entry's frozen projection if it has one, else the current one). It then replaces
   `provider_adapter_revision`, `parameter_contract` and `key_revision` with the entry's constants
   and hashes. For the current label the result is byte-equal to `build_global_cache_key`.
   `[proposed]`
5. **Controls (B1).** The `cache` object accepts two new fields:
   - `only-if-cached: true` — serve a hit or return an error. Never call the provider. Never bypass.
   - `cache-revision: "<label>"` — compute the key with that label's key function.
   `[stated ans:Q2]` `[stated ans:Q1]`
6. **Read-only old revisions (B1).** A label that is not the current one is allowed only with
   `only-if-cached: true`. So a request with an old label never writes. `[proposed]`
7. **Tavily lookup (B1).** The lookup body accepts an optional `cache_revision`. The key then uses
   that entry's `tavily_retrieval` constant. A fill always uses the current constant. `[proposed]`
8. **Revisions read (B1).** `GET /v1/cache/revisions` returns `{current, known}`. A replay engine
   calls it once before the first chat call, so it never sends replay controls to a gateway that
   would bypass them (`contracts.md` K10). `[proposed]`

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **G1.** Given a gateway with the current constants, when it starts, then its computed label is in
  the registry. `[proposed]`
- **G2.** Given any eligible chat request, when the gateway answers it (hit, miss or bypass), then
  the response has `X-AIGW-Cache-Revision` equal to the current label. `[proposed]`
- **G3.** Given a cached request, when it is sent again with
  `cache: {"only-if-cached": true}`, then the gateway serves the stored response with
  `X-AIGW-Cache: hit`. It resolves no credential and calls no provider. `[stated ans:Q2]`
- **G4.** Given a row stored under label L1, and a gateway whose current label is L2, when the same
  request is sent with `cache: {"only-if-cached": true, "cache-revision": "L1"}`, then the gateway
  serves the L1 row, and the header says `L1`. `[stated ans:Q1]`
- **G5.** Given a Tavily result stored under label L1, when a lookup sends `cache_revision: "L1"`,
  then the lookup returns `hit` with that result. `[stated ans:Q1]`

### 3.2 Error paths

- **G6.** Given `only-if-cached: true` and no stored row, then the response is `504` with
  `detail.code = "cache_miss"`. No credential is read and no provider is called. `[stated ans:Q2]`
  (RFC 9111 §5.2.1.7 names `504` for this case.)
- **G7.** Given `only-if-cached: true` and a request that the cache would **bypass** (the provider
  does not take part, the shape is unsupported, a parameter is unknown, the cache is disabled, or
  the store is down), then the response is `504` with `detail.code = "cache_bypass"` and
  `detail.reason = <the published bypass reason>`. The provider is never called. `[implied]`
- **G8.** Given `cache-revision` with a label that is not in the registry, then the response is
  `400` with `detail.code = "unknown_cache_revision"`. `[proposed]`
- **G9.** Given an old label without `only-if-cached: true`, then the response is `400` with
  `detail.code = "cache_revision_requires_only_if_cached"`. `[proposed]`
- **G10.** Given `only-if-cached: true` with `use-cache: false`, then the response is `400` with
  `detail.code = "conflicting_cache_controls"`. `[proposed]`
- **G11.** Given `only-if-cached` or `cache-revision` with a value of the wrong type, then the
  response is `400` with `detail.code = "malformed_cache_controls"`. It is **not** a bypass. A
  bypass would call the provider, and a replay must never do that. `[implied]`
- **G12.** Given a Tavily fill that sends `cache_revision` with an old label, then the response is
  `422` with code `cache_revision_read_only`. `[proposed]`

### 3.3 Derived scenarios (risk-ordered)

- **G13. A constant changes, but no registry entry is added** `[proposed]` — Impact H × Likelihood M.
  Given a PR that changes any revision constant, when CI runs, then the "current label is
  registered" test fails and names the missing label.
- **G14. Projection code changes under a label that already exists** `[stated ans:Q1]` — H×M.
  Given a change to a provider's `global_cache_projection` or to the parameter rules, when CI runs,
  then the golden vectors of an older entry fail. The fix is to freeze the old projection in that
  entry. Deleting or editing the vectors is not a fix (I8).
- **G15. The anthropic revision is computed** `[existing anthropic_provider/plugin.py:58]` — M×M.
  Given a change to a Claude Code attribution constant, then the computed adapter revision changes,
  so the label changes, and G13 fires.
- **G16. A label that differs from the current one for only one provider** `[implied]` — M×H.
  Given a label L1 whose constants differ from L2 only in the openrouter revision, when an openai
  request replays under L1, then its key equals its L2 key, and the shared row is served.
- **G17. Old `use-cache`-only callers are unchanged** `[implied]` — H×L. Given a request with no
  new field, then the parse result, the key, the headers (except the new revision header) and the
  bypass reasons are the same as today.
- **G18. Two gateways with different code at the same time** (rolling deploy) `[implied]` — M×M.
  Given pods on L1 and L2, when a run's calls go to both, then the responses carry different labels.
  The engine marks the run `partial` (`prd/cache-version-capture.md` C7). The gateway does nothing
  special.
- **G21. Revisions read** `[proposed]` — H×M. Given any gateway with B1, when a caller reads
  `GET /v1/cache/revisions`, then `current` equals the computed label and `known` lists every
  registry label, oldest first.
- **G19. Concurrency.** N/A for the registry: it is read-only at runtime. The controls do not
  change the write path (a write happens only on a current-label miss, as today).
- **G20. Empty state.** N/A: the registry always holds the current label (I7).

## 4. Non-functional requirements

- **Latency** `[proposed]`: label computation runs once at startup. Per request, the new work is a
  dictionary lookup and, for an old label, one extra projection. The budget is under 1 ms at p99.
- **Security** `[proposed]`: the label is a hash of public constants. It holds no secret. The
  controls do not widen who can read a row: any hosted caller can read any row today
  (`apps/aigateway/DEPLOYMENT.md`, "The Global Response Cache").
- **Observability** `[proposed]`: the `504` and `400` responses log the label, the provider, the
  model and the 12-character key prefix. They never log the prompt.
- **Size** `[proposed]`: about 20 golden vectors for each provider for each entry, at most about
  50 KB of JSON for each entry.

## 5. Out of scope

- A data backfill or re-key of old rows `[stated ans:Q1]`.
- A key list or digest on the submission `[stated ans:Q3]`.
- A per-request TTL, or a write-only lane (still bypassed, `global_controls.py:32`).
- Honouring `only-if-cached` in a user's url4 `Cache-Control` directive
  (`docs/spec/2026-08-05-url4-cache-policy-spec.md:523` still holds for that case).

## 6. Open questions

None.

## 7. TDD plan

Build order: core-out. The label and registry are pure, so they come first. Then the controls
parse, then the route wiring.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `parse_global_cache_controls` returns today's result for absent, `{}`, `use-cache` true/false, an unknown field and a wrong type | unit | `[existing global_controls.py:61]` | H×L | passes today, by design |
| 2 | CHAR the key of each golden request today is unchanged | unit | `[existing global_keys.py:257]` | H×L | record today's keys as the first entry's vectors |
| 3 | `current_label_is_registered` | unit | G1, G13 | H×M | compute the label from `active_cache_revisions()` + `KEY_REVISION` |
| 4 | `all_four_providers_register_an_adapter_revision` | unit | §2.2.1 | H×M | call `register_adapter_revision` in openai, anthropic and huggingface |
| 5 | `label_changes_when_any_constant_changes` (property: one changed constant → a new label) | unit | G13, G15 | H×M | canonical JSON, sorted keys |
| 6 | `every_registry_entry_reproduces_its_golden_keys` | unit | G14, I8 | H×M | `cache_key_for(label, …)` |
| 7 | `cache_key_for_current_label_equals_build_global_cache_key` | unit | §2.2.4 | H×M | one code path, constants passed in |
| 8 | `old_label_differing_in_one_adapter_keeps_other_providers_keys` | unit | G16 | M×H | replace only the constants the entry names |
| 9 | `only_if_cached_hit_serves_without_credential` | integration | G3 | H×M | parse `only-if-cached`; check before `_resolve_credential_target` |
| 10 | `only_if_cached_miss_is_504_cache_miss_and_no_dispatch` | integration | G6 | H×H | raise after `look_up_global_cache` returns `miss` |
| 11 | `only_if_cached_bypass_is_504_with_reason` (table: each bypass reason) | integration | G7 | H×H | raise on any `bypass` status |
| 12 | `malformed_new_controls_are_400_not_bypass` | unit | G11 | H×M | new fields fail closed |
| 13 | `unknown_label_is_400` | unit | G8 | M×M | registry lookup |
| 14 | `old_label_without_only_if_cached_is_400` | unit | G9 | H×M | read-only rule |
| 15 | `only_if_cached_with_use_cache_false_is_400` | unit | G10 | M×L | conflict check |
| 16 | `old_label_hit_serves_old_row_and_echoes_label` | integration | G4 | H×M | key with the old constants |
| 17 | `revision_header_on_hit_miss_and_bypass` | integration | G2 | M×M | `set_global_cache_headers` adds the header |
| 18 | `tavily_lookup_with_old_label_hits_old_row` | integration | G5 | M×M | key with the entry's `tavily_retrieval` |
| 19 | `tavily_fill_with_old_label_is_422` | integration | G12 | M×L | fills use the current constant only |
| 20 | `legacy_use_cache_callers_unchanged` | integration | G17 | H×L | regression over test 1's table |
| 21 | `revisions_read_lists_current_and_known_labels` | integration | G21 | H×M | new route on the registry |

Refactor on green: keep `GlobalCacheControls` frozen. Add `only_if_cached: bool` and
`revision: str | None`, and do not add a second dataclass.
