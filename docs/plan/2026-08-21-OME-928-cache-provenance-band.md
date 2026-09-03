# OME-928 — cache provenance band (plan)

Spec: `docs/spec/2026-08-21-OME-928-cache-provenance-band.md`

## Carried forward from the OME-692 increment

`b5e5336f` is cherry-picked onto this branch. Its wire-decode half stays as-is and needs no further
work: `_engine/contract.py` (`_cache_status`, `cache_reason`), `events.py`
(`Span.cache_status` / `cache_reason` plus the strict contract), and the tests in
`test_engine_contract.py` and `test_event_values.py`. Its presentation half is replaced below.

## Batches

### 1 · state — the reason map
`_ui/evaluation_state.py`
- add `cache_bypass_reasons: dict[str, dict[str, int]]`, keyed by `run_id`
- `_observe_cache_log`: harvest attributes prefixed `cache.bypass.` and REPLACE that run's map,
  mirroring how the three totals already replace the span-derived counts
- `_observe_cache_status`: on a bypass span, tally `(cache_reason or "").strip() or "unstated"`
- `cache_bypass_breakdown` property: summed across runs, sorted by count desc then reason name
- `_cache_count` is left alone — the text activity summary still uses it

### 2 · view — three cells plus the band
`_ui/evaluation_view.py`
- `repeat(4,1fr)` → `repeat(3,1fr)`; drop `.sf-eval__stat-d`, `_cache_detail`, and the detail
  parameter threaded through `_stat_html`
- add `.sf-eval__cache*` — hairline, square, `flex-wrap:wrap`, no `nowrap`, `--sf-ink-2`
- `_cache_html`: label, rate or em dash, counts, and the bypass segment only when non-zero

### 3 · tests
`tests/test_evaluation_progress_panel.py` — RED first, per the acceptance list in the spec.
These are this branch's own unmerged tests, so revising them is not a rule 5 exception.

## Risks

- The band wraps to a second line on a bypass-heavy narrow panel, reflowing the feed below it.
  Accepted: the feed already grows as events arrive, so the panel was never a stable-layout surface.
- Rendering has not been checked inside JupyterLab's own cascade. Verified before the PR, not after.
