---
ticket: OME-1686
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-20
finished: 2026-10-20
---

# OME-1686-succeeded-attempt-cost — report the cost of the successful attempt in request economics

## Intent

The leaderboard shows the cost of intelligence of a model, not the money that one run spent. A
retry must not change the price of a call. The gateway adds
`_aigw.request_economics.succeeded_attempt_direct_cost`: the `direct_cost` of the attempt that
succeeded, or `null` when no attempt succeeded. The Engine (`OME-1687`) prices each call from this
key. The fields for the actual spend do not change. Spec:
`docs/spec/2026-10-20-OME-1686-succeeded-attempt-cost.md`. Plan:
`docs/plan/2026-10-20-OME-1686-succeeded-attempt-cost.md`.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/taxonomy/render.py` — pure selector helper; new key from
  all `records`.
- `apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json` — key in
  `request_economics` properties and `required`; `$id` stays `v2` (owner, Q1).
- `apps/aigateway/docs/usage-accounting.md` — example, and "Cost of intelligence and actual spend".
- New tests: `tests/unit/usage_accounting/test_succeeded_attempt_cost.py`,
  `tests/unit/usage_accounting/test_succeeded_attempt_cost_route.py`.
- Prior tests (approved by the owner 2026-10-20, spec §5): `test_release_fixtures.py` hash values,
  `test_handoff_contract.py` exact dict, regenerated `fixtures/cache_hit_contract/openrouter_hit.json`.
  Recorded in `.claude/test-change-approvals/OME-1686.json`.
- Contract extension 2026-10-20: `usage_accounting.succeeded_attempt_usage` (same record, `usage | null`),
  in the same schema without an `$id` bump; documented beside the cost key.
- Owner decisions 2026-10-20: Q1 keep `$id` v2; Q2 approved; Q3 no forced `null` on error bodies.
- No schema/model (ORM) change, so no migration (rule S1 does not apply).

## Test plan

- Renderer: single success; 503→200 (key `reported 0.00042`, status stays `partial`); 429
  proven-zero→200 and 429 unknown→200; success with unknown cost; two successes (highest
  `sequence` wins); more than 64 attempts; 64 KiB degradation; only failures → `null`; hit,
  no collector, unsupported → `null`.
- Schema: every rendered case validates; a missing key and a wrong shape are rejected.
- Route: 503→200 through the real retry loop; miss then hit; non-retryable failure body; frozen-copy
  replay.
- Invariant protected: the key is computed from all records and is never cleared by truncation or
  degradation; the actual-spend fields do not change.
- Cross-check: Engine `tests/unit/test_cache_hit_contract.py` passes against the regenerated
  gateway hit fixture, with no Engine file change.

## Acceptance

- Spec §6 holds.
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `render.py`, `usage_accounting.schema.json`, `docs/usage-accounting.md`,
  two new test modules, the three approved prior-test files, and
  `.claude/test-change-approvals/OME-1686.json`. Also `entry_metadata.py` (deviation 1).
- **Commits:** `07bb328ea` — feat(aigateway): report the successful attempt's direct cost and usage.
  Docs: `f50f5eeea`, `356c81bd4`, `36b6338f7`, `fec26a103`.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` → ALL GATES GREEN on
  the first attempt (append-only with 3 approved OME-1686 transitions, ruff check, ruff format,
  pyright, no-enterprise, pytest with coverage). Separate full run: 6059 passed, 103 skipped,
  coverage 93.68%. One earlier full run had 1 intermittent failure that did not repeat (full
  rerun green; `test_chat_global_cache_route.py` 5/5 green). Engine cross-check:
  `apps/screamingface-engine/tests/unit/test_cache_hit_contract.py` 4 passed against the
  regenerated fixture, with no Engine change.
- **Deviations:**
  1. `entry_metadata.py` now calls the shared `last_succeeded_record` helper, so the selection rule
     is defined once. Its behaviour did not change.
  2. The usage-key tests were written after the implementation, because the contract extension
     arrived during GREEN. Proof that they test the right thing: with the key removed, 21 tests
     fail; with it restored, all pass.
  3. The approval manifest was written last, because its blob hashes depend on the final test
     edits. The owner also approved a 19th hash literal in
     `test_release_fixture_exercises_private_input_without_publishing_it`, outside the 18-value
     dict; it is in the manifest.
