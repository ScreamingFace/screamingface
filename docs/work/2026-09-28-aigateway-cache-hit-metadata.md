---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway, screamingface-engine, screamingface
status: in_progress
started: 2026-09-28
finished:
---

# aigateway-cache-hit-metadata — return the full stored block on a hit, and pin the hit contract across the stack

Follow-up gaps of OME-1155 ("Cache gateway metadata end to end for OpenRouter"). Spec:
`docs/spec/2026-09-28-aigateway-cache-hit-metadata.md`. Plan:
`docs/plan/2026-09-28-aigateway-cache-hit-metadata.md`.

## Intent

A cache hit must return all of the metadata that the gateway stored for the entry. Today the
gateway stores `response_model` and `observed_at` but does not send them on the hit. Also, no
test proves that the saved cost of a hit survives the hops gateway → Engine → SDK. This unit adds
the two fields as optional, additive fields of `cache.reference`, and adds a deterministic
cross-stack contract test with shared JSON fixtures. It also closes the "which optional fields
are None" part of PRD test 23 with an exhaustive stdlib walk.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/taxonomy/types.py` — `CacheReference.response_model`,
  `CacheReference.observed_at` (optional, omitted from `as_json` when `None`).
- `apps/aigateway/src/aigateway/plugins/taxonomy/entry_metadata.py` — copy both fields from the
  stored block.
- `apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json` — two optional
  properties on `$defs.cache_reference`.
- `apps/aigateway/tests/fixtures/contract/openrouter_cache_hit.json` + producer test.
- `apps/screamingface-engine/tests/fixtures/contract/openrouter_cache_hit_run_events.json` +
  consumer/producer test.
- `packages/screamingface/tests/test_cache_hit_contract.py` (consumer test).
- CI path filters so a fixture change runs the consumer suites.

## Test plan

- RED: a hit returns `response_model` / `observed_at` from the stored block; old blocks
  (NULL fields) keep the old wire shape byte for byte; schema accepts/refuses the new fields.
- RED: fixture drift tests on both producer sides; consumer tests on Engine and SDK.
- RED: exhaustive round trip over the optional-field `None` space of `CacheEntryMetadata`.

## Acceptance

- All gates green for aigateway, screamingface-engine, screamingface.
- No change to the wire shape for entries with no `response_model` / `observed_at`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
