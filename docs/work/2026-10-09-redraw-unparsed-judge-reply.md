---
ticket: OME-1527   # rides the parent ticket (Work order #3, PR 3 of 20); no leaf of its own
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-09
finished: 2026-10-09
---

# redraw-unparsed-judge-reply — a Task scorer asks the judge again when its reply doesn't parse

## Intent

A judge reply with no verdict word or broken JSON is still a successful model call, so nothing
retries it. Hand-built boards get a redraw by nesting the judge call inside the parser
(url4 `;retry=`); a Task scorer on the plugin lane gets one reply and must either fail the whole
Case (`scorer_error`, wasting its other judge calls) or score the item "not met" (silently
wrong). This unit adds one shared helper Task scorers call per judged item: ask, parse, redraw up
to twice, then fail the Case by name. Built ahead for FRAMES (`OME-1457`) and the rubric-board
migrations (R3 on `OME-1527`).

## Cache finding (settled before code)

- inspect's own cache is off unless a call or the eval's `GenerateConfig.cache` turns it on
  (`inspect_ai/model/_model.py:975-980`, inspect 0.3.263); the helper passes `cache=False` so the
  argument wins over any eval-level setting.
- The AI Gateway's global exact-request cache is on by default and stores any successful reply
  (`apps/aigateway/src/aigateway/core/request_cache/global_controls.py`); nothing in its key or
  eligibility depends on temperature, so an identical re-ask is answered with the cached text.
- The hand-built `;retry=` has NO cache opt-out: url4's `GuardNode._attempt` re-executes the same
  subtree (`packages/url4/src/url4/dag/nodes/guard.py:66-75`), and the connector sends the run's
  own cache policy on every call (`screamingface_engine/world/connector.py:889`, `:955`). Its
  "fresh sample" comments (`healthbench/revision_inputs.py:30-35`, `gdpval/runtime.py:271-273`)
  hold only on a cache miss. Reported, not fixed here (out of scope).
- Existing mechanism reused: the connector already turns a request scope whose cache policy says
  `participate=False` into body field `{"cache": {"use-cache": false}}`
  (`screamingface_engine/world/cache.py:30-56`), read per call from `current_scope()`
  (`connector.py:354`). A redraw rebinds the scope with that policy around its one fetch. The
  in-process node fetch is plain awaits (`url4/peer/_dispatch.py:80-85`), so the binding reaches
  the connector. Accounting: the request key is path + params + context + intent
  (`grading_accounting.py:79-84`), with no cache field, so the redraw registers the same key and
  both calls' cost sums onto the same Case (`_accounting_for_keys`, `:170-177`).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_redraw.py` (new): the helper
  `judge_until_parsed`, `JudgeReplyUnparseable`, `MAX_JUDGE_REDRAWS = 2`, `JudgedItem`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py`: a
  `fresh_judge_draw()` context manager (a ContextVar) the helper sets; the provider then sends
  that one fetch under a request scope that opts out of the gateway cache.
- `apps/screamingface-engine/tests/unit/inspect/test_judge_redraw.py` (new).

## Test plan

- garbage then valid → parsed verdict, redraw count 1.
- garbage ×3 → `JudgeReplyUnparseable` naming the item; never a "not met" value.
- valid first → redraw count 0, and the first ask keeps the run's cache policy (only redraws
  leave the cache).
- through the real gateway provider: the redraw's fetch sees `participate=False`, the first ask
  sees the run's policy, and both register the same accounting request key.
- a redraw with no request scope bound refuses loudly instead of re-asking the cache.

## Acceptance

- The tests above pass with the `inspect` extra; existing judge_provider tests unchanged
  and green; extra-less pyright clean on touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `judge_redraw.py` (new), `judge_provider.py` (`fresh_judge_draw`
  + `_gateway_cache_opt_out`, +45/-4), `tests/unit/inspect/test_judge_redraw.py` (new, 6 tests:
  the five planned plus "an eval-level inspect cache never serves the redraw").
- **Commits:** `03071eb5d` feat(screamingface-engine): redraw a judge reply that doesn't parse;
  this ledger in the follow-up docs commit.
- **Gates:** ruff check + ruff format clean; pyright on the touched files with NO extras: 0
  errors; `check_layering.py` OK; `tests/unit/inspect` with the `inspect` extra: 1310 passed;
  judge activity + request-scope + provider tests: 105 passed. Mutation check: removing the
  cache opt-out fails 2 tests, removing `cache=False` fails 1. Full `run_gates.py` not run
  (dispatch scoped this unit to relevant free tests; the pre-commit hook ran ruff).
- **Deviations:** about 360 lines against a ~120 target, almost all docstrings (Feynman doc on
  the helper) and the 6 tests. The redraw opt-out reuses the request scope's existing
  `CachePolicy` instead of a new transport flag the connector would have to learn. A blank judge
  reply is NOT redrawn: the provider already raises on it before the parser sees it (unchanged).
- **Finding, not fixed (out of scope):** the hand-built boards' `;retry=` has the same cache
  problem — it re-sends identical bytes with the run's own cache policy, so on a gateway cache
  hit every retry returns the same broken reply (see "Cache finding" above). Their "fresh sample"
  comments hold only on a cache miss. Worth its own ticket if those boards are not migrated soon.
- **Owner-verify:** nothing to press; no Task uses the helper yet. The first consumer (FRAMES
  under `OME-1457`, or a rubric-board migration) proves it on a paid run: a redrawn item shows
  `cache: {"use-cache": false}` on its gateway request and its cost on the same Case.
