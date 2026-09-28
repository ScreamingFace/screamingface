# Plan — cache hit metadata and the cross-stack hit contract

- **Spec:** `docs/spec/2026-09-28-aigateway-cache-hit-metadata.md`.
- **Ledger:** `docs/work/2026-09-28-aigateway-cache-hit-metadata.md`.
- **Branch / worktree:** `aigateway-cache-hit-metadata` in
  `.claude/worktrees/aigateway-cache-hit-metadata`.
- **Loop:** `sdlc-python`. Write the failing tests first. Do not change prior tests.

## Task 1 — aigateway: two optional fields on the hit reference (S1)

1. RED — `apps/aigateway/tests/unit/usage_accounting/test_cache_reference_hit_provenance.py`:
   - a stored block with `response_model` and `observed_at` gives a reference that returns both;
   - a block with both `None` gives the same `as_json` keys as before (no new keys);
   - a `partial` block returns both fields and an `unavailable` cost;
   - the constructor refuses a non-`str`, an empty or a > 512-byte `response_model`, and an
     `observed_at` that is not `YYYY-MM-DDTHH:MM:SSZ`; the mapper turns a bad value into
     `CacheEntryMetadataReferenceError`;
   - the schema accepts the two fields and refuses a wrong type or an unknown extra key;
   - the chat route: miss then hit returns `response_model` and `observed_at` of the stored block.
2. GREEN — `plugins/taxonomy/types.py` (`CacheReference`), `plugins/taxonomy/entry_metadata.py`
   (copy the fields), `plugins/taxonomy/usage_accounting.schema.json`.
3. Check: `test_release_fixtures.py` hashes do not change.

## Task 2 — aigateway: PRD test 23 `None` space (S3)

1. `apps/aigateway/tests/unit/test_cache_entry_metadata_none_space.py`: the exhaustive walk from
   spec §3.3 with `itertools.product`. No production code change is expected. If the walk finds a
   defect, stop and record it.

## Task 3 — aigateway: fixture 1 producer (S2, hop 1)

1. `apps/aigateway/tests/unit/test_cache_hit_contract_fixture.py`: the real chat route, miss then
   hit, `_RecordingStore` (real Tortoise store). Normalize, then compare to
   `apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json`. Validate the body
   `_aigw` against the schema. `SF_REGENERATE_CONTRACT_FIXTURES=1` writes the file.
2. Generate the fixture once with the variable. Review it by eye.

## Task 4 — Engine: fixture 1 consumer and fixture 2 producer (S2, hop 2)

1. `apps/screamingface-engine/tests/unit/test_cache_hit_contract.py`:
   - read fixture 1 by repository path; serve it with `httpx.MockTransport`;
   - run `lifecycle.run(InMemoryEventStream(), Url4Executor(world.node), ...)`;
   - assert the run summary and the model span (spec §3.2, hop 2);
   - normalize the encoded events and compare to
     `apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json`.
2. Generate fixture 2 once with the variable.

## Task 5 — SDK: fixture 2 consumer (S2, hop 3)

1. `packages/screamingface/tests/test_cache_hit_contract.py`:
   - read fixture 2 by repository path; feed each event to `_RunState(url4)`; take the outcome;
   - assert `cache_saved_cost_usd == Decimal("0.012345")` on the outcome;
   - through `sf.Client.evaluate` with a replay transport that takes the cache and usage fields
     from the decoded outcome: assert `CandidateResult`, `Report.to_dict()` and `_submission`.

## Task 6 — CI path filters

1. `.github/workflows/screamingface-engine-tests.yml`: add
   `apps/aigateway/tests/fixtures/cache_hit_contract/**` to `push` and `pull_request`.
2. `.github/workflows/screamingface-tests.yml`: add
   `apps/screamingface-engine/tests/unit/data/cache_hit_contract/**` to both.

## Task 7 — gates, ledger, commit, push

1. `uv run .claude/scripts/run_gates.py aigateway --base origin/main`, then
   `screamingface-engine`, then `screamingface`. All green.
2. Fill the ledger outcome. Conventional commits, no `Co-Authored-By`. Push the branch. Do not open
   a PR. Do not change Linear.
