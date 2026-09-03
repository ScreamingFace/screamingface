---
ticket: OME-928
stack: screamingface
status: in_progress
started: 2026-08-21
finished:
---

# OME-928 — Cache provenance as a diagnostic band

Spec: `docs/spec/2026-08-21-OME-928-cache-provenance-band.md`
Plan: `docs/plan/2026-08-21-OME-928-cache-provenance-band.md`

## Intent

Make it possible to tell, while an evaluation runs, whether the cache is working — and when it is
not, which of the two very different failures is happening: the cache was consulted and was cold,
or the cache was never consulted at all.

## How this unit came about

Irina asked for a cache-hit percentage after the cost box and added that she was not sure it was the
best shape. `OME-692-live-cache-progress` (`b5e5336f`) implemented the literal request as a fourth
stat cell. Review of that branch found the percentage cannot answer the underlying question, plus
two measurable defects in the cell itself. `OME-907` — why AIGateway cache prefill isn't hit on
first-time Draco runs — is the investigation this instruments.

## Findings that shaped the design

- **`--sf-ink-3` is not a text color** under SFDS, and the receipt used it at 10.5px. Measured
  against the panel ground: 3.20:1 light, 3.83:1 dark — below AA both ways. `--sf-ink-2` is
  6.61 / 7.48.
- **A fourth cell cannot hold the reasons.** `.sf-ui` caps at 920px and the grid collapses to one
  column only below 680px, so the cell is ~206px ≈ 32 characters at maximum width, before its label
  and value; `unsupported_control 91` is 22 on its own. Truncation fires at every real width.
- **A fixed top-N of reasons is wrong at some width** — one fits at 680px, two at 760px, three at
  920px. Hence wrap rather than cap.
- **The data was already there.** `RunCacheCounters.attributes()` publishes hits, misses, bypasses
  AND `cache.bypass.<reason>`; the Client read the three totals and dropped the breakdown.
- **Reasons belong to bypasses, not misses.** `PUBLISHED_CACHE_REASONS` is a closed, contract-tested
  set and only `CacheBypass` carries a `reason`; a cold miss needs none. An earlier draft of this
  design showed invented per-miss reasons and was corrected before any code was written.

## Planned changes

- `_ui/evaluation_state.py` — `cache_bypass_reasons` per run; harvest from summary attributes with
  replace semantics; tally live from bypass spans; `cache_bypass_breakdown` property
- `_ui/evaluation_view.py` — three-column row, drop `.sf-eval__stat-d` / `_cache_detail`, add the
  band in `--sf-ink-2`
- `tests/test_evaluation_progress_panel.py` — RED first against the spec's acceptance list
- carried forward untouched from `b5e5336f`: `_engine/contract.py`, `events.py` and their tests

## Test plan

RED then GREEN on the spec's nine acceptance points, with particular attention to: summary replaces
rather than doubles the reason map; zero bypasses renders no segment at all; `unstated` and `other`
stay distinct; two Candidate Runs aggregate without either overwriting the other.

Mutation check: force `cache_bypass_breakdown` to return empty and confirm the bypass tests fail.

## Prior-test changes — not a rule 5 exception

The panel tests being revised were added by `b5e5336f`, which is unmerged and carried onto this
branch by cherry-pick. Revising them is iterating on this unit's own work, not editing an inherited
contract. `run_gates.py` still needs `--skip-append-only` because the diff mechanically rewrites
assertions; the reason is this, recorded here.

## Outcome

- **Actual files:** `_ui/evaluation_state.py`, `_ui/evaluation_view.py`,
  `tests/test_evaluation_progress_panel.py`, plus the four renamed docs artifacts. The wire-decode
  half carried over from `b5e5336f` (`_engine/contract.py`, `events.py` and their tests) needed no
  further change, as planned.
- **Gates:** ruff check ✓ · ruff format ✓ · pyright ✓ · pytest --cov (95% floor) ✓ ·
  check_notebooks ✓ · uv build ✓ · check_distribution ✓ — **ALL GREEN**, with `--skip-append-only`
  for the reason recorded above.
- **Focused suite:** 32 passed.
- **Mutation-verified.** Forcing `cache_bypass_breakdown` to return empty fails **6** tests, all of
  them ones that exist to prove the breakdown reaches the band.

### Deviations from the plan

1. **`Span.cache_reason` already rejects a blank string**, so the planned "whitespace becomes
   `unstated`" case is unreachable through the public contract. The `.strip()` guard stays as
   defence, and the test now pins the contract rejection alongside the `None` path.
2. **Two of this branch's own tests asserted the superseded fourth-cell label** and were rewritten
   to the band. Anticipated in kind, but the plan named only one.
3. **My first no-provenance assertion was wrong**, not the code: `"0.0%" not in html` also matches
   the progress bar's `style='width:0.0%'`. Scoped to the band's own markup.
4. **A fresh worktree venv needs `uv sync --extra notebook`** before the panel tests can import
   `ipywidgets`; four unrelated tests fail without it. Environment, not code — verified they fail
   identically on the untouched cherry-pick.
5. `ruff format` reflowed one test file; caught by the gate, not the test run.

### Owner-verify

- **Live JupyterLab rendering of the band — light and dark, and the wrap at a narrowed width.**
  Risk is low rather than unknown: the feed row already ships `display:flex; gap;
  align-items:baseline` inside JupyterLab today, so the band adds only `flex-wrap:wrap` beyond
  existing precedent in the same widget.
- Whether the copy reads correctly to a researcher. Worth putting in front of Irina, who raised the
  request and said she was unsure of the shape.

## Review follow-up — strict decoding and label contrast

### Intent

Close the two merge-readiness findings the owner selected: keep malformed JSON cache-status values
inside the Client's established `ExecutionError` boundary, and make the visible cache label use the
canonical SFDS contracted secondary-text role.

### Planned changes

- `_engine/contract.py` — reject every non-string, non-null `cache_status` as `ExecutionError`
  before closed-vocabulary membership.
- `_ui/evaluation_view.py` — change the visible cache label from decorative `--sf-ink-3` to
  contracted `--sf-ink-2`, matching `OpenMined/screamingface-brand` commit `7ea35a1`.
- `tests/test_engine_contract.py` — append array/object malformed-wire cases.
- `tests/test_evaluation_progress_panel.py` — append a focused cache-label text-role assertion.

### Test plan

RED first: prove array/object status values currently leak `TypeError`, and prove the cache label
currently uses the decorative token. GREEN with the smallest decoder guard and token substitution,
then run both focused files and the full `screamingface` gate matrix.

### Acceptance

- Invalid string, array, and object cache-status values all raise `ExecutionError`.
- The cache label uses `--sf-ink-2`; no readable text in the new cache band uses `--sf-ink-3`.
- Existing cache provenance, progress-panel, package, notebook, build, and distribution tests remain
  green.

### Follow-up outcome

- **RED:** 3 expected failures — array and object `cache_status` values leaked raw `TypeError`;
  the cache-label CSS rule used `--sf-ink-3`.
- **GREEN:** the decoder now type-checks before closed-vocabulary membership, and the cache label
  uses `--sf-ink-2`. The two focused files pass: **79 passed**.
- **Brand verification:** cloned `https://github.com/OpenMined/screamingface-brand.git` at
  `7ea35a12608776ba3f811811578cec9fd5193b4f`; `SYSTEM.md` and `components/style.css` both define
  the single label role with `--ink-2` and reserve `--ink-3` from readable text.
- **Full gates:** ruff check ✓ · ruff format ✓ · pyright ✓ · pytest with the 95% coverage floor ✓ ·
  notebook determinism ✓ · wheel build ✓ · distribution check ✓ — **ALL GREEN**, retaining the
  branch's documented `--skip-append-only` exception for its earlier superseded assertions.
- **Actual files:** `_engine/contract.py`, `_ui/evaluation_view.py`, `test_engine_contract.py`,
  `test_evaluation_progress_panel.py`, and this ledger.
- **Deviations:** none.
