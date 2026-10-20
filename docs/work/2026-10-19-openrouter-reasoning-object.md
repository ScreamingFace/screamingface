---
ticket: OME-1656
stack: aigateway
status: done
started: 2026-10-19
finished: 2026-10-19
---

# openrouter-reasoning-object - support object-form reasoning effort

## Intent

Allow `sf.Model` calls to select OpenRouter's object-form reasoning effort through the existing
dotted scalar parameter `reasoning.effort`. This restores high-effort runs for models that reject
the legacy `reasoning_effort` spelling without widening the SDK/URL4 parameter value type to
arbitrary nested JSON.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/parameters.py`: add the validated,
  cache-keyed `reasoning.effort` rule with its own projection revision. Preserve the revision of
  existing rules because their projections do not change and this previously rejected path has no
  stored cache entries to abandon.
- `apps/aigateway/src/aigateway/core/request_cache/global_eligibility.py`: admit explicitly ruled
  direct dotted paths while preserving wrapper-only isolation for `provider_params.*`.
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/plugin.py`: reject requests that send
  both `reasoning_effort` and object-form reasoning effort.
- `apps/aigateway/tests/unit/openrouter/test_openrouter_parameter_projection.py`: prove dotted
  ingress projects to the nested OpenRouter body, validates the full documented effort enum, reaches
  the installed LiteLLM wire shape, appears in the contract, and conflicts with the legacy spelling.
- `apps/aigateway/tests/unit/openrouter/test_openrouter_global_cache_keys.py`: prove different object
  efforts cannot share a cache key; add the new path to the owner-approved exact keyed-path set.
- `apps/aigateway/tests/unit/test_global_cache_registry_conformance.py`: update the owner-approved
  addressing-form invariant for ruled direct dotted paths.
- `.claude/test-change-approvals/OME-1656.json`: pin both approved prior-test transitions.

## Test plan

- RED: a dotted `reasoning.effort=high` request reaches dispatch as
  `reasoning={"effort": "high"}` and is present in the model parameter contract.
- RED: all documented OpenRouter effort values are accepted; unknown values are refused before
  dispatch; legacy `reasoning_effort` remains unchanged.
- RED: installed LiteLLM sends the nested reasoning object verbatim for an affected model.
- RED: installed LiteLLM preserves every documented effort for all four affected ticket models.
- RED: object effort changes the global cache key and sending both effort spellings is refused.
- RED: an unknown direct dotted path still bypasses before cache lookup, matching the 400 miss path.
- GREEN: focused OpenRouter suites, then the complete AIGateway quality gate.

## Acceptance

- `sf.Model(..., params={"reasoning.effort": "high"})` compiles through the existing dotted-name
  path and dispatches the required OpenRouter JSON object.
- The gateway advertises and validates the parameter, keys cached responses by it, and never sends
  both effort spellings in one request.
- No SDK, Engine, database, migration, credential, or unrelated provider behavior changes.
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` is green.

## Outcome (fill at the end - required before COMMIT)

- **Actual files:** `core/request_cache/global_eligibility.py` now admits only explicitly ruled
  direct dotted paths while keeping `provider_params.*` wrapper-only; OpenRouter `parameters.py`
  owns the full object-effort enum and keyed direct rule; `plugin.py` publishes local evidence and
  refuses dual effort spellings. New projection, installed-LiteLLM wire, enum, conflict, summary,
  detailed-contract and cache-key coverage landed in three OpenRouter test modules; core cache and
  registry suites pin dotted-path addressing. Two approved prior-test transitions are pinned in
  `.claude/test-change-approvals/OME-1656.json`; an independent parameterized unknown-dotted
  regression closes the pre-classification cache boundary. The Linear mirror is
  `docs/tasks/2026-10-19-OME-1656-openrouter-reasoning-object.md`.
- **Commits:** `feat(aigateway): support OpenRouter reasoning objects`
- **Gates:** initial focused OpenRouter/cache/conformance run `76 passed`; reviewer follow-up
  (`reasoning.max_tokens` and two other unknown dotted paths plus the 4-model x 7-effort installed
  LiteLLM matrix) `32 passed`; `run_gates.py aigateway --base origin/main` green after rebasing to
  current main (approved append-only transitions, ruff, format, pyright, no-enterprise, full pytest
  with coverage). Repo script tests, loop parity, mirror status and `git diff --check` are green.
- **Deviations:** no SDK or Engine code was needed: their existing dotted scalar path already
  preserves `reasoning.effort`. The global-cache core guard was narrower than discovery suggested;
  owner approved changing its prior conformance contract from rejecting every dotted top-level key
  to rejecting only the wrapper-reserved `provider_params.*` namespace. The new rule received a
  dedicated revision instead of bumping the shared revision, avoiding a cold start for unchanged
  OpenRouter parameter cache entries. Per-model reasoning capability enforcement remains outside
  this unit; OME-652 already owns the architecture decision for dynamic capability enforcement.
