# B1 — gateway: cache revision label, registry and replay controls

- **Worktree:** `.claude/worktrees/e14-b1-gateway-cache-revision` · **Branch:** `e14-b1-gateway-cache-revision`
- **Base:** `e14-reproducible-submission-spec` · **Stack:** `aigateway`
- **PRD:** `prd/gateway-cache-revision.md` (G1–G21, TDD #1–#21). Contracts K1, K2, K10. Rules: `00-common.md`.
- **Commit order:** commits 1..n for the label + registry (TDD #1–#8, #17) with no behaviour change,
  then the controls (TDD #9–#16, #18–#21).

## Files

| File | Change |
|---|---|
| `src/aigateway/core/request_cache/revision_registry.py` | new (core): key-revision registration, label, registry entries, `cache_key_for` support |
| `src/aigateway/core/request_cache/global_keys.py` | `key_revision` parameter threaded like `parameter_contract_revision` (default `KEY_REVISION`); used in `_canonical_mapping` |
| `src/aigateway/core/request_cache/global_plan.py` | optional `revision` (a registry entry) → keys with the entry's constants |
| `src/aigateway/core/request_cache/global_controls.py` | `only_if_cached: bool = False`, `revision: str \| None = None` on `GlobalCacheControls`; parse rules below |
| `src/aigateway/core/request_cache/tavily_retrieval.py` | `tavily_retrieval_key(key, *, contract_revision=TAVILY_RETRIEVAL_CONTRACT_REVISION)` |
| `src/aigateway/routes/chat_cache_stage.py` | `REVISION_HEADER = "X-AIGW-Cache-Revision"`; set it in `set_global_cache_headers` |
| `src/aigateway/routes/chat.py` | only-if-cached enforcement after `look_up_global_cache`, before `_resolve_credential_target`; control errors |
| `src/aigateway/routes/tavily_retrieval_cache.py` | `cache_revision` on lookup (optional) and fill (422 if not current); revision header in `_publish` |
| `src/aigateway/routes/cache_revisions.py` | new: `GET /v1/cache/revisions` (`CurrentAccount`) ; include in `main.py` next to the tavily router |
| `src/aigateway/plugins/{openai,anthropic,openrouter,huggingface}_provider/…` | one `register_key_revision(<provider>, GLOBAL_CACHE_ADAPTER_REVISION)` line each, next to the constant |
| `tests/fixtures/cache_revisions/<label>.json` | golden vectors for the current label |
| `scripts/generate_cache_revision_vectors.py` | writes the vectors file for the current label from a fixed request list |
| `tests/unit/…` | new test files only (append-only) |

Exemplars: `core/request_cache/revisions.py` (registry style, plugin registers into core),
`tests/unit/test_chat_cache_contract_composition.py` (`cache_client`, `credential_blobs`,
`_DispatchCounter`), `tests/unit/test_global_cache_key.py` (golden-style key tests).

## Decisions (pinned)

- **Do not register into `revisions.register_adapter_revision` / `active_cache_revisions()`.** That
  map is the snapshot manifest. New names there make every existing production snapshot refuse to
  load (`upload_job.py` revision_mismatch). Use a separate registration in `revision_registry.py`:
  `register_key_revision(provider: str, revision: str) -> None`, keyed by the provider string that
  `build_global_cache_key` receives (`plugin.custom_llm_provider`; check the four values).
- Constants map (`current_constants()`):
  `{"key_revision": KEY_REVISION, "parameter_contract": PARAMETER_CONTRACT_REVISION,
  "tavily_retrieval": TAVILY_RETRIEVAL_CONTRACT_REVISION, "adapters": {<provider>: <rev>, …}}`.
- Label: `"cr-" + sha256(canonical JSON of the constants map).hexdigest()[:12]`. Canonical JSON:
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Reuse
  `canonical.py`'s helper if it gives exactly this; otherwise use the line above.
- `@dataclass(frozen=True) class RevisionEntry: label: str; constants: Mapping[str, Any];
  frozen_projections: Mapping[str, Callable[[dict[str, Any]], dict[str, Any] | CacheBypass]] = {}`
  (use `field(default_factory=dict)` / `MappingProxyType`).
- `REGISTRY: Mapping[str, RevisionEntry]` is a literal in `revision_registry.py` with ONE entry today:
  the current label, its constants written out as literals (so a later constant change does not
  change the old entry). `current_label()` computes the label from the live constants;
  `entry_for(label) -> RevisionEntry | None`.
- Keying under an entry: projection = `entry.frozen_projections.get(provider, plugin.global_cache_projection)`;
  wrap it so a dict result has `provider_adapter_revision` replaced by
  `entry.constants["adapters"][provider]`; call `build_global_cache_key(…,
  parameter_contract_revision=entry.constants["parameter_contract"],
  key_revision=entry.constants["key_revision"])`. For the current label this must equal today's key
  byte for byte (TDD #7). A provider missing from an entry's adapters → 400 `unknown_cache_revision`
  (the label does not cover that provider).
- Controls parse (`parse_global_cache_controls`): allowed keys become `{"use-cache",
  "only-if-cached", "cache-revision"}`. Today's rules stay for `use-cache` and unknown keys
  (bypass) **only when neither new key is present**. When `only-if-cached` or `cache-revision` is
  present: wrong type → raise a new `CacheControlError(code)` (`malformed_cache_controls`); unknown
  extra key → `malformed_cache_controls`; `only-if-cached: true` with `use-cache: false` →
  `conflicting_cache_controls`. `only-if-cached: false` is allowed and means "not set".
  `chat.py` turns `CacheControlError` into `HTTPException(400, detail={"code": …, "message": …})`.
- Revision rules in `chat.py` (before `look_up_global_cache`): label not in `REGISTRY` → 400
  `unknown_cache_revision`; label ≠ `current_label()` and not `only_if_cached` → 400
  `cache_revision_requires_only_if_cached`.
- only-if-cached in `chat.py` (after `look_up_global_cache`, before `_resolve_credential_target`):
  `miss` → `HTTPException(504, detail={"code": "cache_miss", "message": …})`; `bypass` →
  `HTTPException(504, detail={"code": "cache_bypass", "reason": outcome.reason, "message": …})`.
  Set the cache headers on the error response too if the route can (nice to have; not required).
  With an old label, a miss never reaches the write path (it raised).
- Header: `X-AIGW-Cache-Revision` = the label used to key (the requested one, else current) on
  every response that ran the cache stage; on Tavily lookup responses too.
- Tavily: `_Description` gains `cache_revision: str | None = None` (excluded from the key material
  itself). Lookup with a label → key with `entry.constants["tavily_retrieval"]`; unknown label →
  422 `unknown_cache_revision` (the lane's 422 vocabulary). Fill with a label ≠ current → 422
  `cache_revision_read_only`.
- `GET /v1/cache/revisions` → `{"current": current_label(), "known": [labels in REGISTRY order]}`.
- CI guard (TDD #3): a unit test asserts `current_label() in REGISTRY` and, on failure, prints the
  computed label and constants so the developer can add the entry + run the vectors script.
- Golden vectors: about 5 fixed requests per provider (reuse bodies from the existing key tests),
  stored as `{"label": …, "vectors": [{"provider": …, "body": {…}, "key_hash": …}]}`. TDD #6 loads
  every file in `tests/fixtures/cache_revisions/` and checks each key with `cache_key_for`.
- Update the docstring of `GlobalCacheControls` ("There is no read-only or write-only lane") to say
  that old revisions are read-only replay (OME-1307).

## Do not

- Do not change `active_cache_revisions()`, snapshot export or upload.
- Do not change `KEY_REVISION`, `PARAMETER_CONTRACT_REVISION` or any adapter revision value.
- Do not log prompts or full key hashes (12-character prefix only).

## Verify

`python3 .claude/scripts/run_gates.py aigateway --base e14-reproducible-submission-spec`
