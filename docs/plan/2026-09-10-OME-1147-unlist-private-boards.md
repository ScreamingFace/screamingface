# OME-1147 — Plan

Spec: `docs/spec/2026-09-10-OME-1147-unlist-private-boards.md`

## Files

| File | Change |
|---|---|
| `portal/leaderboard-logic.js` | add `listedBenchmarks(benchmarks)`; widen the header comment |
| `portal/main.js` | `initIndex()` filters before `Promise.all(...fetchBoard)`; fix the empty-state copy |
| `src/scoreboard/routes/leaderboard.py` | correct the `list_benchmarks` docstring |
| `tests/portal/leaderboard-logic.test.js` | behaviour of the new helper |
| `tests/unit/test_portal_static.py` | the wiring assertion |

No new test file, so the gate list and `scoreboard-tests.yml` are untouched.

## RED — two layers

**Node, `tests/portal/leaderboard-logic.test.js`** — the rule:

- a `"private"` benchmark is dropped;
- a `"public"` one is kept;
- absent, `null`, and `"unrecognised"` are all kept (D3);
- a non-array input yields an empty array rather than throwing;
- the input array is not mutated.

**Python, `tests/unit/test_portal_static.py`** — the wiring:

- `main.js` calls `L.listedBenchmarks(` inside `initIndex`;
- `leaderboard-logic.js` exports it;
- `index.html` still loads `leaderboard-logic.js` before `main.js`.

The second layer is the one that matters. The node suite cannot see `main.js`, so a correct helper
that nothing calls would pass every behavioural test. The script-order assertion guards the other
half of the same failure: the helper is called, but the module that defines it has not loaded yet.

## GREEN

```js
function listedBenchmarks(benchmarks) {
  if (!Array.isArray(benchmarks)) return [];
  return benchmarks.filter(function (b) {
    return !b || b.visibility !== "private";
  });
}
```

In `initIndex`, immediately after `var benchmarks = (data && data.benchmarks) || [];`.

## Gates

`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`

Expected fully green including append-only: every test change is an addition. If append-only does
flag something, stop — that means an existing assertion was disturbed, which this plan does not
intend.

## Risks

- **The helper exists but nothing calls it.** Covered by the wiring assertion.
- **Script order regresses**, so `L` is undefined at call time. Covered by the load-order assertion;
  `test_portal_static.py` already uses the same technique for `benchmark.js`.
- **Over-filtering.** D3's fail-open keeps a board visible whenever the field is anything but the
  exact string `"private"`; three of the five node cases pin that.
