---
ticket: OME-791
stack: aigateway
status: in_progress
started: 2026-08-20
finished:
---

<!-- STATUS NOTE (OME-791 review remediation, 2026-08-21): the previous value,
"implemented (awaiting owner approval to commit)", was not one of the four permitted states
(planned | in_progress | done | blocked). `in_progress` is the honest replacement: the
implementation and the review-remediation pass are both COMPLETE, but the unit closes at merge
and rebase verification plus the gated-repository decision remain pending, so `finished` stays
empty. Set `finished` and `done` at merge. -->


# OME-791 — HuggingFace global-cache projection

## Intent

`huggingface_provider` inherits `CacheBypass` from `ProviderPluginBase`, so every
`huggingface/*` request bypasses AIGateway's global exact-response cache at the projection step
and all twelve of its parameter rules are pinned at `cache_behavior="bypass"` as a consequence.
This unit adds the provider's own pure projection and promotes those rules to `keyed`, so a
benchmark re-run over HF models replays instead of paying full price — the same capability
OpenRouter has had since OME-305 and OpenAI gains in OME-884.

Spec: `docs/spec/2026-08-20-OME-791-huggingface-global-cache-projection.md`.
Plan: `docs/plan/2026-08-20-OME-791-huggingface-global-cache-projection.md`.

## Planned changes

Production (`apps/aigateway/src/aigateway/plugins/huggingface_provider/`):

- `global_cache.py` — NEW. `GLOBAL_CACHE_ADAPTER_REVISION`, `router_dispatch_controls()`, and the
  pure `project_global_cache_request(body)`.
- `settings.py` — publish the router base as a module constant and add a pure
  `cacheable_upstream_model(slug)` derived from the existing slug predicates.
- `plugin.py` — wire `global_cache_projection`, `participates_in_global_cache` (official-base
  check), and `cache_reference_from_cached_response` returning `None`.
- `parameters.py` — promote all eleven rules to `cache_behavior="keyed"`, bump `_REVISION`,
  replace the bypass-rationale AIDEV-NOTE.

Tests (`apps/aigateway/tests/unit/huggingface/`):

- `test_huggingface_global_cache_projection.py` — NEW: purity/determinism, non-mutation,
  bypass classes, `prepared` completeness, adapter-revision isolation.
- `test_huggingface_global_cache_keys.py` — NEW: key-difference proofs per newly-keyed path
  through `build_global_cache_plan()`.
- `test_huggingface_route_global_cache.py` — NEW: route-level `miss -> hit`, one dispatch, one
  row, hit does no credential work, unsuccessful response not stored.
- Existing HF tests: expected to remain green and unmodified except for the cache-disposition
  assertions the promotion necessarily changes (append-only decision — enumerate before
  touching).

Durable artifacts: this ledger + the spec, plan and `docs/tasks/` mirror dated 2026-08-20.

## Test plan

RED first, per unit:

1. Projection purity and totality — settings object that raises; no body mutation; every input
   yields a projection or a `CacheBypass`, never an exception.
2. Bypass classes — malformed slug, non-`huggingface/` prefix, non-string model, and the
   unsuffixed `huggingface/<org>/<model>` case (router picks a backend per request).
3. `prepared` completeness — exactly the pinned official `api_base`; JSON-safe; a fresh dict per
   call so a caller cannot mutate later key material.
4. Key difference — repo, `:<backend>` suffix, messages, and each newly-keyed parameter
   (`temperature`, `max_tokens`, `stop`, `response_format`, `seed`, `n`, `frequency_penalty`,
   `presence_penalty`, `logprobs`, `top_logprobs`, `tools`, `tool_choice`) isolate; equal
   effective values collide.
5. Participation — an overridden `AIGW_HUGGINGFACE_ROUTER_API_BASE` declines participation while
   the official base participates.
6. Route — identical eligible requests produce `miss -> hit` with one dispatch and one row; a
   provider error stores nothing; a hit performs no HF credential read/decrypt and no dispatch.
7. Hit metadata — no `cache-reference mapper failed` warning; accounting reports unsupported.

Standing (green on arrival): the registry purity sweep and
`test_a_provider_that_declares_a_keyed_rule_backs_it_with_a_real_projection`.

## Acceptance

- Identical eligible `huggingface/*` requests produce `miss -> hit`.
- Different repos, `:<backend>` suffixes, messages, or newly-keyed parameter values never collide.
- The projection is total, pure, non-mutating, JSON-safe, identity-free and credential-free.
- Malformed and unsuffixed ids neither read nor write cache.
- No core port change, no schema/migration/dependency change, no route-order change.
- OpenRouter, Anthropic and Codex behaviour unchanged.
- Focused tests plus the configured aigateway quality gates green.

## Baseline (before the first edit)

The configured aigateway quality gates, run 2026-08-20, were **ALL GREEN** — append-only check,
ruff check, ruff format --check, pyright,
`scripts/check_no_enterprise.py`, and `pytest --cov=aigateway --cov-fail-under=80 -q`. Venv
created fresh in the worktree (`uv sync`), Python 3.12, litellm 1.97.0.

## Outcome

- **Actual files** (all under `apps/aigateway/`, plus docs):
  - `src/aigateway/plugins/huggingface_provider/global_cache.py` — NEW, 153 lines.
    `GLOBAL_CACHE_ADAPTER_REVISION = "huggingface-global-cache-2026-08"` and the pure
    `project_global_cache_request(body)`. **Planned `router_dispatch_controls()` was NOT built** —
    review found it contradicted the plan's own "Deliberately not built" list.
  - `src/aigateway/plugins/huggingface_provider/settings.py` — `_ROUTER_API_BASE` renamed to public
    `OFFICIAL_ROUTER_API_BASE`. **Planned `cacheable_upstream_model(slug)` was NOT built** — the
    existing `pinned_router_target` already owns that predicate, and a second one is drift.
  - `src/aigateway/plugins/huggingface_provider/plugin.py` — 432 lines (limit 450). Three hooks
    plus the module-level `_unsafe_litellm_global_state()` and the once-per-condition decline log.
  - `src/aigateway/plugins/huggingface_provider/parameters.py` — TWELVE rules to `keyed`,
    `_REVISION` -> `"huggingface-2026-08"`, promotion-instruction block replaced with a record.
  - `tests/unit/huggingface/test_huggingface_global_cache_projection.py` — NEW, 41 tests
    (projection + participation + hit metadata).
  - `tests/unit/huggingface/test_huggingface_route_global_cache.py` — NEW, 37 tests (promotion,
    per-path key differences, published contract, route).
  - `docs/` — spec, plan, task mirror, this ledger, all dated 2026-08-20.
- **Two test files, not four** (planned). Collapsed to match the one-cache-file-per-provider
  precedent both existing projections follow.

- **Gates:** configured aigateway quality gates — **ALL GREEN**: append-only check (vs HEAD), ruff
  check, ruff format --check, pyright,
  `scripts/check_no_enterprise.py`, `pytest --cov=aigateway --cov-fail-under=80 -q`.
  Focused: `tests/unit/huggingface` 217 passed; the five global-cache core suites 327 passed.
  The plan's prediction of **zero prior tests modified** held — the append-only gate confirms it.

- **Commits (actual, present on `OME-791-huggingface-global-cache-projection`):**
  - `89116431` — `feat(aigateway): cache huggingface router responses`
  - `d6b1ec5d` — `docs(aigateway): record the OME-791 huggingface cache decisions`

  Together: 10 files, +2425/−31 vs `origin/main`. The earlier "Commits: none" line was written
  INSIDE the commit that contradicted it and is corrected here (review finding M4).

- **Review remediation implementation commit:**
  - `a549850b` — `fix(aigateway): harden huggingface cache eligibility`

- **Tripwires, both OBSERVED TO FIRE** (guard neutralised, symptom recorded in an AIDEV-NOTE at
  the guard, guard restored, suite re-run green):
  1. *Unsuffixed-id bypass* (`global_cache.py`). Neutralised, an unsuffixed
     `huggingface/deepseek-ai/DeepSeek-R1` projected `resolved_model="deepseek-ai/DeepSeek-R1:"`
     — a bogus EMPTY backend — and produced the real key hash
     `017a1b3f728f1ad79882d705856bbf4679bc7cb4d6292760bdc7ad7303ac9e21`. The failure mode is a
     permanent storable row, not a decline.
  2. *D3 participation gate* (`plugin.py`). Neutralised, the deployment configured for
     `https://proxy.internal/v1` was served `X-AIGW-Cache: hit` from a row filled against the
     official router — a 200 carrying an answer its own upstream never produced.

## Review remediation pass (2026-08-21)

The implementation review returned **3 blockers and 8 major findings**. The owner-scoped remediation
implemented B1, B2, B3, M1, M2, M3, M4, M5 and M8; M6/M7 and minor findings remain outside this
MVP remediation.

- **B1 — policy suffixes were cached as pinned backends.** `pinned_router_target()` treated *every*
  non-empty suffix as a deterministic backend, so `:fastest`, `:cheapest`, `:preferred`, `:auto` and
  even `:notarealprovider` produced real, permanent, globally shared keys. `:preferred` is the sharp
  case: it follows the **requesting account's** provider preference order, so one account's answer
  could be replayed to another whose identical request would have selected a different provider —
  identity-dependent dispatch under an architecturally identity-free key. Fixed with a fail-closed
  `KNOWN_ROUTER_BACKENDS` frozenset transcribed from the Hugging Face partner table (18 slugs, read
  2026-08-21), sourced from the partner table rather than the 8 seeded providers so the catalog
  cannot become an admission list. A denylist was rejected: it fails **open** on the next policy
  keyword HF ships. `_validate_model_slug` stays permissive — dispatch is unchanged.
- **B2 — LiteLLM Proxy could take over dispatch while participation returned `True`.** Guarding
  only `litellm.use_litellm_proxy` was insufficient: `_should_use_litellm_proxy_by_default` checks
  `get_secret_bool("USE_LITELLM_PROXY")` **first**
  (`llms/litellm_proxy/chat/transformation.py:73`) and returns on it alone, and is consulted at the
  top of `get_llm_provider` (`get_llm_provider_logic.py:151`). Verified live: both controls flip
  `get_llm_provider(...)` from `huggingface` to `litellm_proxy`, the environment one while the
  attribute stays `False`. Both are now guarded; litellm's private helper is deliberately not called.
- **B3 — the suite could not tell the fix from the bug.** The 217-test HF suite was green both
  before and after the correct behaviour was applied, because it tested the parser's raise sites
  rather than the semantic question "is this backend fixed for the next call?". Fixed with
  hazard-named semantic tests plus route-level no-read/no-write proofs.
- **M1/M2** — `disable_stop_sequence_limit` (truncates a `stop` list past four entries,
  `utils.py:7618`) and `enable_json_schema_validation` (gates post-dispatch schema refusal for a
  **keyed** `response_format`, `utils.py:1198`) both change behaviour behind a byte-identical
  request body. Both now decline participation, each with a behavioural proof.
- **M5 (PARTIAL, by owner scope)** — the complete HF ambient predicate, inventories, decline
  reasons and decline log moved to `huggingface_provider/runtime_guard.py`; `plugin.py` dropped
  **432 → 287 lines**. Cross-provider duplication is **NOT** eliminated: `openai_provider` and
  `openrouter_provider` still carry near-copies and were deliberately not touched. The former
  "mirror this into the siblings" instruction was **removed** as unsafe — HF declines cache
  participation where some sibling paths hard-fail dispatch, so copying a condition without its
  response would turn a lossless decline into a refused request. Repo-wide consolidation is a
  separate follow-up after this branch integrates current `main` and the provider-specific response
  policies can be designed together.
- **M8** — `additional_drop_params` removed from the guarded inventory (it is not a litellm module
  global on 1.97.0; the old test passed only because `raising=False` **created** it). Now:
  existence assertions for every guarded global, `raising=True` throughout, an independently
  authored expected inventory compared both ways, and every callback field — async included —
  parametrized with the `"cache"` exemption preserved.
- **M3** — `DEPLOYMENT.md` no longer claims HF always bypasses; it now carries a per-suffix
  cacheability table and the gated-repository cross-account licensing consequence. Added as
  consequence **6** on `config.requestCache` in `values.yaml`, plus `values-prod.yaml` and the
  chart README. Chart defaults unchanged.

**Falsification (both mutations executed, then reverted):**

1. `pinned_router_target` reverted to `return (repo, backend) if sep else None` →
   **21 tests failed** across `test_huggingface_provider_allowlist.py` and
   `test_huggingface_route_global_cache.py`. The pre-remediation suite passed this mutation.
2. `runtime_guard` stripped of the env-secret check and the three new globals →
   **11 tests failed** in `test_huggingface_runtime_guard.py`.

**Files changed in this remediation:**

| File | Lines | Note |
| --- | --- | --- |
| `src/…/huggingface_provider/settings.py` | 199 | `KNOWN_ROUTER_BACKENDS` + allowlisted `pinned_router_target` |
| `src/…/huggingface_provider/runtime_guard.py` | 263 | **NEW** — the whole guard, including fail-closed unreadable-state containment |
| `src/…/huggingface_provider/plugin.py` | 287 | was 432; guard removed |
| `src/…/huggingface_provider/global_cache.py` | 153 | stale symbol reference only |
| `tests/unit/huggingface/test_huggingface_provider_allowlist.py` | 183 | **NEW** — 23 tests |
| `tests/unit/huggingface/test_huggingface_runtime_guard.py` | 389 | **NEW** — 46 tests |
| `tests/unit/huggingface/test_huggingface_global_cache_keys.py` | 268 | **NEW** — split out, 30 tests |
| `tests/unit/huggingface/test_huggingface_route_global_cache.py` | 437 | was 550; 12 tests |
| `tests/unit/huggingface/test_huggingface_global_cache_projection.py` | 360 | M8 edits, 40 tests |
| `tests/live/test_huggingface_provider_allowlist_drift.py` | 77 | **NEW** — opt-in `AIGW_LIVE=1` |
| `DEPLOYMENT.md`, `charts/aigateway/{values,values-prod,README}` | — | M3 |
| `docs/work/2026-08-20-OME-791-…md` | — | this record (M4) |

**Checks actually run (2026-08-21):** ruff check ✅ · ruff format ✅ · pyright 0 errors ✅ ·
`tests/unit/huggingface` **290 passed** ✅ · focused global-cache conformance/purity/plan/key/reason
suite **131 passed** ✅ · full suite **3702 passed, 50 skipped, 1 unrelated failure** · coverage
**92.43%** (floor 80) ✅ · `git diff --check` clean ✅ · every changed/new Python file ≤ 450 lines ✅ ·
`check_no_enterprise.py` ✅.

**Owner-approved gate deviations:**

1. **Append-only check — RED.** It flags `test_huggingface_route_global_cache.py` (the 550→two-file
   split the brief *mandated*, naming `test_huggingface_global_cache_keys.py`) and two lines in
   `test_huggingface_global_cache_projection.py` (the `additional_drop_params` case and
   `raising=False`, both of which M8 *mandated* removing — the case only passed by creating the
   attribute it claimed to test). Verified **zero prior test functions lost**: all 37 that existed
   at HEAD still exist, now among 164. The gate cannot distinguish a move from a deletion. The
   owner approved this documented append-only deviation; the gate itself remains unchanged.
2. **`tests/unit/test_helm_prod_config.py::test_prod_sets_finite_openrouter_provider_concurrency_cap`
   — RED, pre-existing and unrelated.** It asserts `AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES` in
   prod `extraEnv`; that key is absent at `HEAD` **and** in the working copy, the test file is
   **untracked** (OME-921's uncommitted RED state), and this pass's only `values-prod.yaml` change
   is comment text. The owner approved committing OME-791 without absorbing that unrelated change.

## Deviations

- **Branch/base.** `OME-791-huggingface-global-cache-projection` branched from `origin/main` at
  `c157ed7a`. OME-884 is NOT merged, so `openai_provider`'s
  projection is absent on this base; its module shape was copied as a pattern, never imported.
  Forward-merge item: OME-884 changes the `participates_in_global_cache` signature to receive a
  model, which would let the `model_alias_map` check narrow from coarse-truthy to exact-model.

- **Linear untouched, by owner direction.** The owner directed mid-session that Linear must not be
  modified during this work. OME-791 was deliberately left in Backlog, no comment was posted, and
  the normal "move to In Progress at ledger creation" step was skipped. The `docs/tasks/` mirror
  records `status: Backlog` truthfully rather than claiming a transition that did not happen.

- **Plan corrected before implementation.** Material corrections:
  - **D6 rewritten.** The pre-review justification was FALSE (it claimed both projecting providers
    guard ambient LiteLLM state; Anthropic projects with no such guard). More seriously the guard
    was *under*-inclusive: `litellm.model_fallbacks` is read at `main.py:602` inside
    `async def acompletion` — the exact call HF inherits — and dispatches a DIFFERENT model whose
    answer is then stored under the HF key, permanently. The guard now mirrors
    `openai_provider/plugin.py:85-101`, whose condition set is verified reachable from HF's path.
  - **`HuggingFaceChatConfig().get_config()` condition withdrawn.** It cannot fire on the HF wire
    in litellm 1.97.0, and *evaluating* it mutates litellm class state (`_is_base_class = False`).
  - **DoD claim corrected.** "A hit does no credential work" was false: a hit performs one
    profile-index read, itself a `credential_blobs` row plus a master-key decryption, documented
    at `chat_profile_defaults.py:68-71`. The route test now asserts the narrow true claim AND
    asserts the profile-index read positively, so the claim cannot silently rot.
  - **Counts fixed.** TWELVE rule paths, not eleven (`function_calling_rules` emits both `tools`
    and `tool_choice`); 24 seeds, not the spec's 25. Both verified at runtime, not by eye.
  - **D4 census corrected** from two spellings of the router base to four. Only the dispatch-path
    one is renamed; `api_key_validation._READINESS_URL` is deliberately left as a hardcoded
    literal (it exists so an overridden base cannot redirect a credential probe) and
    `discovery.py`'s two copies are catalog-only. The DoD no longer claims "one origin" package-wide.
  - **D3 comparison normalised** with `rstrip("/")`, since litellm strips the trailing slash
    before appending `/chat/completions`; a literal `!=` would have disabled caching for a
    provably wire-identical deployment.
  - **Shared conformance file left untouched.** Raising `_OBSERVED_NON_BYPASS_INSTANCES` would
    make an append-only-protected shared test depend on catalog/environment state; an HF-local
    per-model twelve-instance floor is stronger and has zero blast radius.
  - **Observability added** (D11): with eight decline paths collapsing onto one wire reason, the
    hook now logs a condition TOKEN once per process — never the configured URL or header value.

- **One RED test rewritten mid-cycle** (not a prior-cycle test — written earlier this same unit
  and never green). `test_a_raising_guard_degrades_to_not_participating` asserted the *hook*
  returns `False`; the core already guarantees that at `global_plan.py:72-77`, so a `try` inside
  the hook would have been a second guard protecting nothing. Replaced with
  `test_a_raising_guard_costs_a_bypass_and_never_the_request`, which asserts the plan-level
  contract a caller actually depends on.

- **Owner decision still open, flagged not buried:** gated-repo licensing under cross-account
  replay (spec §9). Most seeds are gated repos requiring per-HF-account license acceptance, so a
  row filled by an accepting account can be served to one that never accepted. Recorded as an
  ACCEPTED CONSEQUENCE because it follows from the approved exact-replay semantics rather than
  from this unit's design; if the owner declines it, the remedy is a catalog-level seeding/gating
  decision, not a projection change.

- **~~`plugin.py` is at 432 of 450 lines.~~ RESOLVED 2026-08-21** by the review remediation pass:
  the ambient-state guard moved to `huggingface_provider/runtime_guard.py` and `plugin.py` is now
  **287 lines**. Note the correction to the original prediction — the extraction went to a
  provider-LOCAL module, **not** to core. Extracting into core was rejected for this branch because
  sibling providers respond to the same hazards differently (HF declines cache participation; some
  sibling paths hard-fail dispatch). A shared helper needs a union plus per-provider deltas and stays
  a separate follow-up after this branch integrates current `main`.
