---
ticket: OME-791
stack: aigateway
status: implemented (awaiting owner approval to commit)
started: 2026-08-20
finished:
---

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

- **Commits:** none. Nothing staged or committed; owner approval not yet given.

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

- **Plan revised after adversarial review, before implementation.** Four independent reviews ran
  against the pre-review draft; one returned **reject**. Every finding was re-verified against
  this base before being accepted or rejected. Material corrections:
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

- **`plugin.py` is at 432 of 450 lines.** The next responsibility added to this file should go in
  a new module instead; extracting the shared ambient-state predicate into core (see the
  AIDEV-NOTE there) is the obvious candidate and would bring it back down.
