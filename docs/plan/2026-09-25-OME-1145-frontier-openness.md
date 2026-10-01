# OME-1145 — plan

Spec: `docs/spec/2026-09-25-OME-1145-frontier-openness.md` (approved 2026-09-25).
Ledger: `docs/work/2026-09-25-OME-1145-frontier-openness.md`.
Branch `OME-1145-frontier-openness` from `origin/main` at `69971220`.

## Step 1 — RED, new tests first

- `tests/unit/scores/test_frontier_openness.py`: the pure computation, every §6 bullet except the
  route and portal ones. No DB.
- `tests/unit/scores/test_frontier_models_read.py`: the bounded `id, models, openness_override`
  read, including chunking across the parameter limit.
- `tests/unit/test_frontier_route.py`: the route end to end: frontier basis, revision, case count,
  `pinned` gate → `frontier_available: false`, private 404, unidentified and unrecognised counts.
- portal: a Node test for `renderFrontier` on the new shape (`open_share: null` hides the number).

Confirm each fails for the stated reason.

## Step 2 — GREEN

1. `scores/schemas.py`: new `FrontierResult`, `FrontierResponse` fields and a trend point shape
   per spec §4; `current` removed.
2. `scores/frontier.py`: replace `_current_split` / `_compute_trend` with
   `compute_frontier_openness(pareto_inputs, members, frontier_ids, *, pinned)` plus the trend
   replay. Pure, no I/O.
3. `scores/store.py`: `frontier_member_models(ids)`, chunked, `id, models, openness_override`
   only. The trend needs every row's `submitted_at` too: add it to the pareto projection as a
   **separate** narrow read rather than widening `ParetoEntry` (OME-1179 constraint 4).
4. `routes/leaderboard.py`: `get_frontier` reads the ranked route's inputs, applies the same
   `pinned` gate, keeps `turned_private` as the last await before the response.
5. `portal/benchmark.js`: `renderFrontier` on the new fields; tooltip names the unidentified count
   and the unrecognised routes.

## Step 3 — PRIOR TESTS (approved list, spec §7)

Rewrite exactly the listed tests onto the new basis, each with a stricter counterpart. The two
invariants in `test_frontier.py` (case count, no registered count) are re-expressed, not dropped.
Anything outside the list that breaks: STOP and ask.

## Step 4 — GATES

`uv run .claude/scripts/run_gates.py scoreboard --base origin/main --skip-append-only`. The
append-only check must flag **only** the approved files; run it once without the skip to prove it.

## Step 5 — MUTATION, COMMIT, PR

Mutations: count a dominated row; drop the revision filter; let `unknown` read open; ignore the
override. Each must fail a test. Then mirror, ledger outcome, PR, close-comment at merge.

## Risk

- **The trend replay is O(n · m log m)** over comparable submissions. Fine at dev scale (10
  rows); a board with thousands of submissions would need an incremental sweep. Stated in the
  code as an `AIDEV-NOTE`, not solved speculatively.
- **The frontier on dev is one entry until real costs land** (D-K). The fix is correct but cannot
  be demonstrated there yet.
