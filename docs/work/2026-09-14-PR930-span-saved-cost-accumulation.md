---
ticket: unfiled — PR #930 review fixes (Linear MCP offline this session; filing skipped by owner)
stack: url4 + screamingface-engine (+ aigateway docs)
status: done
started: 2026-09-14
finished: 2026-09-14
---

# PR #930 review fixes — span-level saved cost, and the metadata-erasing restore

## Intent

Three findings from the full review of PR #930. (1) A span published its cache saved cost
last-wins, so a tool-calling turn with several hits dropped every amount but the final one,
while the run total counted them all — a money attribute that cannot be summed. (2) The span
write was guarded on the PRICE while the run counter beside it was guarded on the STATUS; the
two encode the same invariant and would drift. (3) `DEPLOYMENT.md` told an operator that NULL
means unknown, but never that merging a pre-0011 archive turns already-known rows back into
unknown ones.

Fix (1) by mirroring the run model on the span: one accumulator per provenance, never summed
into a single figure (PRD S5), which is also the accumulation semantics PRD §4.1 already
states ("O(1) per gateway round trip, not per turn"). Fix (2) falls out of it — with nothing
to blank, the span guard becomes `cache_status == "hit"`, the run's own guard.

## Planned changes

- `packages/url4/src/url4/streaming/protocol/signals.py` — `SpanData`: keep
  `cache_saved_cost_usd` (provider-authored, now a span total), replace
  `cache_saved_cost_provenance` with `cache_saved_cost_archive_usd`.
- `apps/screamingface-engine/src/screamingface_engine/runner/cache_counters.py` — extract
  `SavedCostTotals` (the route-by-provenance, never-mix rule in ONE place); `RunCacheCounters`
  delegates to it.
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` — `_SpanState` holds
  a `SavedCostTotals`; `_fold_response` records run and span under one `cache_status == "hit"`
  guard; `_finish` publishes both totals.
- `apps/aigateway/DEPLOYMENT.md` — restore section states the metadata-erasing merge.
- Tests: `apps/screamingface-engine/tests/unit/test_cache_saved_cost.py`,
  `tests/unit/test_span_tree.py`, `packages/url4/tests/unit/test_saved_cost_reporting.py`.

## Test plan

- A span with three `reported` hits publishes their SUM, not the last one.
- A span with both provenances publishes two separate totals and no third combined one.
- A hit whose cost is unpriceable leaves an earlier hit's total standing.
- A non-hit carrying a price adds nothing to the span (guard parity with the run).
- The OTel attribute bag carries both money attributes as exact decimal strings.
- The url4 protocol admits the new field and no longer admits the provenance one.

## Acceptance

- `url4.cache_saved_cost_usd` on a span equals the sum of that span's provider-authored hits,
  so summing the attribute across spans reproduces `cache.saved_cost_usd` for the run.
- No code path adds the two span totals together.
- Gates green on all three stacks.

## Outcome

- **Actual files:** as planned, plus two spec rows that described the superseded span shape
  (`docs/spec/2026-09-13-cache-entry-metadata-erd.md` §"the saved-cost total from ans:Q2",
  `…-prd.md` row E2) and one new test file,
  `apps/screamingface-engine/tests/unit/test_cache_saved_cost_spans.py` (7 tests).
  `packages/url4/src/url4/dag/node.py` did NOT change: `report_response` emits the per-round-trip
  `ModelResponse` event, which rightly keeps `cache_saved_cost_provenance` — only the AGGREGATED
  span record needed reshaping.
- **Gates:** `run_gates.py` green on all three stacks — screamingface-engine (2 823 passed,
  9 skipped), url4 (1 248 passed), aigateway (4 357 passed). Engine + url4 re-run after the
  pyright-escape cleanup.
- **Deviations:**
  - **Three prior tests edited, owner-confirmed.** `test_span_data_carries_both_saved_cost_fields`
    and `test_both_saved_cost_fields_are_absent_by_default_on_a_span` (url4), and
    `test_a_saved_cost_becomes_an_exact_decimal_string_attribute` (engine) assert the
    `cache_saved_cost_provenance` field the approved design removes. Each swaps it for
    `cache_saved_cost_archive_usd` and keeps its original intent; no assertion was weakened or
    dropped. Gates therefore ran with `--skip-append-only` (sdlc rule 5 Confidence Gate: asked,
    answered, recorded here).
  - **`SavedCostTotals` is EXTENDED by `RunCacheCounters`, not composed into it.** Composition
    would have moved the two money fields off `dataclasses.fields(RunCacheCounters)` and broken
    `test_the_counter_carries_exactly_two_saved_cost_accumulators` — a prior test that had no
    business changing for a DRY refactor of mine. Inheritance keeps it green and still checking
    the same invariant.
  - **No Linear issue.** Linear MCP was not connected this session and the owner chose to skip
    filing. PR #930 itself carries no `OME-N` either; both remain open process debt, together
    with the missing `docs/tasks/` mirror (review finding 4, out of scope here).
  - Review finding 4 (untracked PRD/ERD cited by ~30 docstrings) was NOT addressed — the owner
    scoped this unit to findings 1–3.
