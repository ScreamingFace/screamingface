---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-11-11
finished:
---

# litellm-hold — hold litellm below 1.104.6 until OpenRouter rows are back in its bundled map

## Intent

Dependabot #1725 bumps litellm 1.104.2 → 1.108.2 in `packages/screamingface`, and its golden
replay fails `test_the_runtime_gateway_keeps_openrouter_reasoning_without_upstream_rows`. Since
1.104.6, litellm's bundled `model_prices_and_context_window_backup.json` has no `openrouter/*`
rows: 477 in 1.104.2, 0 in 1.104.6 through 1.109.0 (checked against the PyPI wheels). The gateway forces the
bundled map (`LITELLM_LOCAL_MODEL_COST_MAP=True`, `apps/aigateway/src/aigateway/__init__.py`),
so OpenRouter `reasoning_effort` would break in production. Hold litellm so the other bumps in
the group can land.

## Planned changes

- `.github/dependabot.yml`: add `litellm` `versions: [">=1.104.6"]` to the `ignore` lists of the
  `/packages/screamingface` and `/apps/aigateway` uv entries (aigateway is locked at 1.102.1 and
  would hit the same break on its next bump), each with a WHY comment.

## Test plan

- No code change. The guard is the existing `test_runtime_litellm_model_map.py`, which caught it.
  The YAML parses, and both entries list the hold.

## Acceptance

- Once merged, `@dependabot recreate` on #1725 drops litellm and the rest of the group goes green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:** Studio runtime (locks 1.104.2 transitively) has no Dependabot version entry, so there's nothing to hold there.
