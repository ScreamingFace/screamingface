# Cache hit metadata and the cross-stack hit contract

- **Status:** approved for build (user: "spec + plan, then code"), 2026-09-28.
- **Parent work:** OME-1155 (PR #930 gateway block, PR #1055 Scoreboard, PR #1075 SDK).
- **Ledger:** `docs/work/2026-09-28-aigateway-cache-hit-metadata.md`.
- **Language:** ASD-STE100 Simplified Technical English.

## 1. Problem

1. On a cache miss, the gateway stores a metadata block (`aigw.cache-entry-metadata.v1`) with
   `usage`, `direct_cost`, `latency`, `response_model` and `observed_at`. On a hit, the gateway
   sends only `usage`, `direct_cost` and `latency` in `_aigw.usage_accounting.cache.reference`.
   The gateway stores `response_model` and `observed_at`, and then drops them.
2. Each stack tests only its own half of the hit contract. No test proves that the saved cost of a
   hit survives the hops gateway → Engine → SDK. A change to the gateway shape does not make an
   Engine test or an SDK test fail.
3. The author of PR #930 recorded two open items: PRD test 23 is example-based, not
   property-based; and there is no runtime validation of `usage_accounting.schema.json`.

## 2. Scope

### 2.1 In scope

- **S1. Two additive, optional fields on the hit reference.** `CacheReference` gets
  `response_model: str | None` and `observed_at: str | None`.
  `cache_reference_from_entry_metadata` copies them from the stored block.
- **S2. A deterministic cross-stack contract test.** It uses no live provider and spends no money.
- **S3. The "which optional fields are `None`" part of PRD test 23.** An exhaustive walk with the
  standard library only.

### 2.2 Out of scope

- The "same format as a live call, Engine agnostic" decision (see Q1). The `cache.reference`
  shape stays.
- Ranking on full cost (OME-1382, OME-1143). Live OpenRouter tests. Linear, Asana.
- Runtime validation of the schema (see Q3). It stays a follow-up.

## 3. Design

### 3.1 S1 — the hit reference

- `CacheReference.response_model`: `None`, or a `str` of 1 to 512 UTF-8 bytes. The collector
  already bounds the value to 512 bytes when it writes the block.
- `CacheReference.observed_at`: `None`, or an RFC 3339 timestamp (`YYYY-MM-DDTHH:MM:SS`, an
  optional fraction, then `Z` or `±HH:MM`). The gateway writes `...:SSZ`. The out-of-band archive
  loader writes `archive_paired` blocks with `+00:00`; both are real rows. The value is the time
  of the cache fill (the time that the gateway observed the original response). It is not the
  time of the hit. The check has two parts: a regex for the shape, then
  `datetime.fromisoformat` for the calendar (the regex alone admits `2026-99-99T99:99:99+99:99`).
- The constructor raises `ValueError` for a value that is not valid.
- **A bad stored value does not cost the price.** `cache_reference_from_entry_metadata` checks
  each of the two fields with the same predicate that the constructor uses
  (`is_valid_cache_response_model`, `is_valid_cache_observed_at`). It drops a bad value (the hit
  then looks like an older row) and does NOT go to the S11 fallback. The two fields are
  informational; the S11 fallback would replace a certified stored price with the value from
  the cached body. S11 does not change for `usage` and `direct_cost`. Each drop logs
  `cache-entry metadata field dropped field=<name>` at WARNING. The log never contains the value.
- `as_json` adds `response_model` and `observed_at` to the reference only when the value is not
  `None`. This is the rule that `latency` already uses.
  - **Compatibility.** The bytes stay the same only for a row whose metadata block is NULL or
    whose two fields are NULL, and for every provider fallback reference (built from the cached
    body). Rows written since PR #930 already store both fields, so on deploy their hits START to
    return the two new keys. This is additive; the Engine tolerates it
    (`test_the_engine_ignores_the_reference_fields_it_does_not_price`). The pinned
    release-fixture hashes in `test_release_fixtures.py` do not change.
  - **No value is inferred from the cached body** (PRD R2). The fallback mappers keep `None`.
- A `partial` block still returns both fields. The `partial` rule applies to price only.
- The JSON schema `$defs.cache_reference` gets two optional properties with the same bounds.
  `response_model` and `attempt.response_model` / `attempt.requested_model` share one
  `$defs.model_id` entry (`string`, `maxLength: 512`). The reference adds `minLength: 1`, because
  it OMITS an unknown model where an attempt renders `null`. Note: JSON Schema `maxLength` counts
  characters; the Python check (`MAX_RESPONSE_MODEL_BYTES`, also used by the collector) counts
  UTF-8 bytes, so the Python check is the stricter one.
- **Consumers.** The Engine reads only `cache.reference.direct_cost`
  (`world/accounting.py:_cache_reference_direct_cost`). The SDK does not read `_aigw`. The
  Engine kind stub sends `reference: null`. No consumer needs a change. The admin API surface
  does not change, so the `apps/aigateway-ui` schema types do not change.

### 3.2 S2 — the cross-stack contract test

Apps do not import each other. The contract therefore travels as **checked-in JSON fixtures**.
Each fixture has one **producer** test (it builds the fixture from real code and compares it to
the file) and one **consumer** test (it reads the file and asserts what must survive).

| Hop | Producer (owns the file) | File | Consumer |
|---|---|---|---|
| 1 | aigateway: the real chat route, miss then hit, with the real Tortoise store | `apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json` | Engine |
| 2 | Engine: `build_aigateway_world` + `Url4Executor` + `url4.streaming.lifecycle.run` fed with fixture 1, encoded with `url4.streaming.codec.encode` | `apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json` | SDK |
| 3 | — | — | SDK: `_RunState` decodes fixture 2; the result goes to `CandidateResult`, `Report` and the Scoreboard submission |

- **Fixture 1** holds the hit response: the `X-AIGW-Cache*` headers and the JSON body with
  `_aigw`. **Fixture 2** holds the ordered CloudEvents of one Engine run, as the wire sends them.
- **Normalization.** Values that change on each run are replaced with fixed, valid values before
  the compare: trace ids, span ids, event ids, times, `gateway_call_id`, `observed_at`, the
  measured `provider_latency_ms`, the cache key. The producer test first asserts the type of each
  value, then replaces it. All other bytes are compared exactly.
- **Regeneration.** `SF_REGENERATE_CONTRACT_FIXTURES=1` makes a producer test write the file
  instead of compare. Without the variable, a difference fails the test with the instruction.
- **Assertions that survive each hop.**
  - Hop 1: the reference carries the stored `direct_cost` (`reported`, `0.012345`,
    `openrouter_credits`), the stored `response_model` and `observed_at`; the current-request
    cost is `not_applicable` with no attempts. The fixture validates against
    `usage_accounting.schema.json`.
  - Hop 2: the run summary has `cache.hits == 1`, `cache.saved_cost_usd == "0.012345"` and
    `cost_usd == 0`. The model span carries `cache_status == "hit"` and
    `cache_saved_cost_usd == "0.012345"`.
  - Hop 3: `CandidateResult.cache_saved_cost_usd == Decimal("0.012345")`; the submission sends
    `cache_saved_cost_usd == "0.012345"` and does not add it to `run_cost_usd`.
- **Why these locations.** No cross-stack fixture directory exists today (the old
  `docs/spec/fixtures/` is gone). A file owned by its producer is the least-coupled choice: the
  producer regenerates it, and the consumer reads it by repository path. The Engine already reads
  aigateway files by repository path (`test_declared_models_match_aigateway.py`). A new top-level
  directory would be a repository-layout decision, which this unit does not make.
- **CI.** The path filters of `screamingface-engine-tests.yml` get the fixture-1 directory. The
  path filters of `screamingface-tests.yml` get the fixture-2 directory AND the fixture-1
  directory, because the SDK test also reads fixture 1 directly (to tie the last hop to the
  first). Thus a regenerated fixture runs its consumer suites.
- **Regeneration never looks green.** After it writes a fixture, a producer test fails on
  purpose (`pytest.fail(..., pytrace=False)`, the `test_public_surface.py` convention). Under `CI`
  the variable is refused.

### 3.3 S3 — PRD test 23, the `None` space

- `hypothesis` is not a dependency of any stack. This unit adds no dependency (see Q2).
- A new test walks **every** combination of `None` / value for the optional fields of the block
  (`observed_at`, `response_model`, `provider_latency_ms`, the six usage counts, and the cost
  presence), for each of the three `metadata_status` values. For each combination it asserts:
  - `serialize` → `parse` gives back an equal block (exact round trip);
  - `cache_reference_from_entry_metadata` gives back the stored `usage` exactly, the stored
    `direct_cost` only for a certifying status, and each optional field verbatim or absent.
- This closes the "walk the full `None` space" gap. It does not give shrinking. PRD test 23 at
  `level: property` stays open until Q2 is decided.

## 4. Open questions for the owner

- **Q1 — "same format, Engine agnostic".** OME-1155 asks that a hit return metadata in the same
  format as a live call. The code keeps the historical cost in `cache.reference` and a current cost
  of 0, and the Engine reads the hit on its own path. This unit keeps that shape. The owner must
  confirm the deviation on OME-1155, or ask for a format change.
- **Q2 — `hypothesis`.** Do we add `hypothesis` as a dev dependency of `apps/aigateway` to close
  PRD test 23 at `level: property`? This unit does not add it.
- **Q3 — runtime schema validation.** The item is not well defined: where the check runs (each
  render, or tests only), what happens on failure (fail open or fail closed), and whether
  `jsonschema` (today only a transitive dependency through `litellm`) becomes a direct dependency.
  This unit validates the contract fixture against the schema in tests only. Proposed follow-up:
  an `improvement-ideas` issue.
- **Q4 — Engine span `gen_ai.response.model` on a hit (follow-up).** The Engine sets it to its
  own route id (`openrouter/anthropic/claude-fable-5`), not to the model that produced the cached
  answer. It can now read `cache.reference.response_model`. This unit does not change the Engine.
