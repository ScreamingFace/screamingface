# Plan: OME-1686 — succeeded-attempt cost in request economics

Spec: `docs/spec/2026-10-20-OME-1686-succeeded-attempt-cost.md`. Ledger:
`docs/work/2026-10-20-OME-1686-succeeded-attempt-cost.md`. Stack: `aigateway` (`sdlc-python`).
Branch: `OME-1686-succeeded-attempt-cost`. Consumer: `OME-1687` (Engine), blocked by this issue.

## Preconditions

- Done 2026-10-20: the owner approved the spec and this plan. Q1: keep `$id` `v2`. Q2: the three
  prior-test changes are approved (manifest `.claude/test-change-approvals/OME-1686.json`). Q3: do
  not force `null` on error bodies.
- No Engine file changes in this branch. The Engine is `OME-1687`.
- Contract extension (owner, 2026-10-20): also `usage_accounting.succeeded_attempt_usage`, the
  `usage` of the same record (spec §3). One selector helper feeds both keys. Each test below that
  names the cost key has a matching usage-key test.

## Steps

### RED — new tests first (new test modules only; prior tests unchanged at this stage)

1. **Renderer unit tests** — new module
   `apps/aigateway/tests/unit/usage_accounting/test_succeeded_attempt_cost.py`. Build records with
   the existing record helpers (copy the builder idiom from `test_render.py`) and call
   `render_aigw_metadata` directly:
   - single success, `reported 0.001` → key equals that attempt's `direct_cost` JSON;
   - 503 (`unavailable`) → 200 (`reported 0.00042`) → key is `reported 0.00042`;
     `direct_cost_status == "partial"`; `known_direct_cost_subtotals` unchanged;
   - 429 `provider_guaranteed_zero` → 200 `reported` → key is the 200's cost;
     `direct_cost_status == "complete"` (OME-1446 behaviour stays);
   - 429 `unavailable` → 200 `reported` → key is the 200's cost; status `partial`;
   - successful attempt with `unavailable` cost → key is `{"status": "unavailable", amount/unit/source null}`;
   - two `succeeded` records → key is the one with the highest `sequence` (D1);
   - more than `MAX_RENDERED_ATTEMPTS` records, success last → key present and correct while
     `rendered_attempts == 64`;
   - metadata above 64 KiB (`bounds_overflow` shape) → after `_degrade_to_bound` the key is still
     present and correct;
   - only failed records → `null`;
   - `cache_status="hit"` → `null`; `collector=None` → `null`; `supported=False` → `null`.
2. **Schema tests** — in the same new module: every rendered case above validates against the
   packaged schema; a document without the key is rejected (it is `required`); a key with a wrong
   shape (for example an extra property, or a number amount) is rejected.
3. **Route tests** — new module
   `apps/aigateway/tests/unit/usage_accounting/test_succeeded_attempt_cost_route.py`, reusing the
   route harness of `test_chat_route_accounting.py` (gateway overload retry, about line 543) and
   `test_openrouter_proven_zero_route.py`:
   - 503 → 200 through the real retry loop → response `_aigw.request_economics` carries the key
     with the 200's cost;
   - cache miss then the same request as a hit → the hit carries `null`;
   - a failed request (non-retryable 502) → the error body's `_aigw` carries `null`;
   - frozen-copy replay → `null` (reuse the harness of `tests/unit/test_frozen_copy_replay.py`).
4. Run the new tests. Confirm that each one fails because the key is missing, not because of a
   harness error.

### GREEN — minimal production change

5. `apps/aigateway/src/aigateway/plugins/taxonomy/render.py`:
   - add a pure helper `_succeeded_attempt_direct_cost(records, *, cache_status)` that returns
     `None` for a hit, else the `direct_cost.as_json()` of the `succeeded` record with the highest
     `sequence`, else `None`;
   - call it with `records` (not `rendered_records`) and put the result in `request_economics`;
   - do not touch `_degrade_to_bound`. Add an `# INVARIANT:` comment that degradation must not
     clear the key, and a `# FEATURE:` comment that names the cost-of-intelligence rule and
     `OME-1686`.
6. `apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json`: add the key to
   `$defs.request_economics.properties` and `required`. Keep `$id` `v2` (Q1).
7. Run the new tests (green) and the full aigateway suite. Expect red only in the prior tests
   that spec §5 lists.

### Prior tests — only after owner approval (spec Q2)

8. `test_release_fixtures.py`: replace only the 18 values in `_EXPECTED_FIXTURE_SHA256`. Print
   the new hashes from the test failure, and check the diff of one fixture by hand to prove the
   only difference is the new key.
9. `test_handoff_contract.py:89-100`: add the new key to the exact dict.
10. Regenerate `tests/fixtures/cache_hit_contract/openrouter_hit.json` with
    `SF_REGENERATE_CONTRACT_FIXTURES=1 uv run pytest tests/unit/test_cache_hit_contract_fixture.py`.
    The only diff must be `"succeeded_attempt_direct_cost": null`.
11. Cross-check the Engine consumer without changing Engine files: from
    `apps/screamingface-engine`, run `uv run pytest tests/unit/test_cache_hit_contract.py`. It
    reads the regenerated gateway fixture by repository path. The Engine run-events fixture must
    not change. If it changes, STOP and report (it is `OME-1687` scope).
12. Record the three approved files byte-exact in `.claude/test-change-approvals/OME-1686.json`
    (`base_blob` from `origin/main`, `approved_blob` from `git hash-object`), in the format of the
    existing manifests.

### Docs, refactor, gates

13. `apps/aigateway/docs/usage-accounting.md`: add the key to the example; add the section
    "Cost of intelligence and actual spend" (spec D8).
14. Refactor while green. Keep `render.py` under 450 lines.
15. Gates, from the repository root:
    `uv run .claude/scripts/run_gates.py aigateway --base origin/main`.
16. Ledger outcome, then a conventional commit, for example
    `feat(aigateway): report the successful attempt's direct cost in request economics`.
    No push and no PR without the user's confirmation.

## Expected production files

- `apps/aigateway/src/aigateway/plugins/taxonomy/render.py`
- `apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json`
- `apps/aigateway/docs/usage-accounting.md`

## Expected test files

- new: `tests/unit/usage_accounting/test_succeeded_attempt_cost.py`
- new: `tests/unit/usage_accounting/test_succeeded_attempt_cost_route.py`
- changed (approved 2026-10-20): `test_release_fixtures.py` (hash values only),
  `test_handoff_contract.py` (one dict), `fixtures/cache_hit_contract/openrouter_hit.json`
  (regenerated)
- new: `.claude/test-change-approvals/OME-1686.json`

## Stop conditions

- A prior test outside spec §5 turns red.
- The Engine cache-hit contract test (step 11) changes its output.
- The key cannot be computed from `records` without a collector change.
- Any need to change retry policy, the proven-zero rules, or `direct_cost_status`.
