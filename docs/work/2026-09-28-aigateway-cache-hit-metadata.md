---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway, screamingface-engine, screamingface
status: done
started: 2026-09-28
finished: 2026-09-28
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

- **Actual files:** as planned, plus the two workflow path filters.
  - aigateway src: `plugins/taxonomy/types.py` (`CacheReference.response_model` /
    `observed_at`, predicates `is_valid_cache_response_model` / `is_valid_cache_observed_at`),
    `plugins/taxonomy/entry_metadata.py`, `plugins/taxonomy/usage_accounting.schema.json`.
  - aigateway tests: `tests/unit/usage_accounting/test_cache_reference_hit_provenance.py`,
    `tests/unit/test_cache_entry_metadata_none_space.py`,
    `tests/unit/test_cache_hit_contract_fixture.py`,
    `tests/fixtures/cache_hit_contract/openrouter_hit.json`.
  - Engine tests: `tests/unit/test_cache_hit_contract.py`,
    `tests/unit/data/cache_hit_contract/run_events.json`.
  - SDK tests: `packages/screamingface/tests/test_cache_hit_contract.py`.
  - CI: `.github/workflows/screamingface-engine-tests.yml`, `screamingface-tests.yml`.
- **Commits:** `aeb16f0f` docs (spec + plan + ledger); `ca4d0fe3` feat(aigateway): return
  response_model and observed_at on a cache hit; `8c67f4fc` test: pin the cache-hit contract
  from gateway to Engine to SDK; plus this ledger commit.
- **Gates:**
  - aigateway: ALL GATES GREEN — pytest 4992 passed, 89 skipped; coverage >= 80.
  - screamingface: ALL GATES GREEN — pytest 1868 passed, 26 skipped; cov >= 95; build and
    distribution checks green (needs `uv sync --extra notebook` locally, as CI does).
  - screamingface-engine: ruff, format, pyright, layering green; pytest 4062 passed, 19
    skipped, **2 failed** — `tests/integration/test_worker_spine.py::
    test_submit_claim_spawn_frames_terminal` and `::test_a_warm_child_takes_the_run_and_is_replaced`.
    Both fail the same way on clean `origin/main` on macOS (`setrlimit(RLIMIT_AS)` →
    `ValueError: current limit exceeds maximum limit`, the OME-1151 root cause). Not caused by
    this unit (no Engine src change); Linux CI is the arbiter. Coverage 94.21%.
  - **Push blocked locally.** `.githooks/pre-push` reruns the Engine gate; on this machine it
    also fails `tests/integration/test_run_queue_roundtrip.py` (2 tests) because a shared local
    NATS at `localhost:4222` is reachable and carries other sessions' state. Not bypassed with
    `--no-verify` — that is the owner's call.
- **Deviations:**
  - `observed_at` accepts RFC 3339, not only `...:SSZ`: the out-of-band archive loader writes
    `+00:00` (seen in `test_cache_entry_archive_matched_row.py`). A strict format broke that
    certifying hit in the full suite.
  - A malformed stored `response_model` / `observed_at` is DROPPED by the mapper rather than
    sent to the S11 fallback, so an informational field never costs a certified price. The spec
    §3.1 is updated.
  - Runtime schema validation not built (spec Q3); PRD test 23 closed only for the `None` space
    (spec Q2). No new dependency.
- **Follow-ups / owner questions:** spec §4 Q1 (same format / Engine agnostic sign-off), Q2
  (`hypothesis`), Q3 (runtime schema validation — proposed `improvement-ideas`), Q4 (Engine span
  `gen_ai.response.model` could read `cache.reference.response_model` on a hit).
