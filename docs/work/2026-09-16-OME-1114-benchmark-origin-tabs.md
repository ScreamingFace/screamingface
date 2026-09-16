---
ticket: OME-1114
stack: screamingface
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1114 — Benchmark listing shows one tab per origin, each linking to its source

## Intent

The Engine catalogue now stamps every benchmark with `origin` (OME-1112). The SDK still
flattens the listing, so imported inspect_evals boards would be indistinguishable from ours.
This unit makes `sf.benchmarks.list()` render one tab per origin — "ScreamingFace" and
"inspect_evals" — each tab carrying a link to its source collection
(https://leaderboard.dev.screamingface.ai/ and
https://ukgovernmentbeis.github.io/inspect_evals/). Pure client-side presentation of one
server field; zero new endpoints. Owner-locked design (2026-09-16 session): tabs (not
stacked groups), link map lives SDK-side in the UI layer, decode accepts ANY non-empty
origin string so an older SDK never bricks against a newer Engine, and an unmapped origin
auto-gets its own tab with no link.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/catalog_contract.py` — `_BenchmarkEntry.origin`; decode `origin` (absent → `"screamingface"` for pre-OME-1112 Engines; present → any non-blank string).
- `packages/screamingface/src/screamingface/_engine/catalog.py` — `_benchmark()` forwards origin.
- `packages/screamingface/src/screamingface/discovery.py` — `Benchmark.origin: str = "screamingface"` + non-blank validation.
- `packages/screamingface/src/screamingface/_ui/cards.py` — origin → (tab label, source URL) map; grouped/tabbed benchmark rows HTML; origin (+ link) on `benchmark_card_html`.
- `packages/screamingface/src/screamingface/_ui/catalog.py` — `_BenchmarkCatalog` renders one tab per origin (ipywidgets `Tab`) and grouped sections in the static `_repr_html_` fallback.
- `packages/screamingface/tests/test_benchmark_origin_tabs.py` — new test file (append-only rule: prior tests untouched).

## Test plan

- Decode: `origin` present flows to `Benchmark.origin`; absent defaults to `"screamingface"` (old-Engine compat); blank/non-string → `invalid_catalogue`.
- `Benchmark` refuses a blank origin.
- Mixed catalogue static HTML: both tab labels + both source hrefs; an undeclared origin (e.g. `"helm"`) renders its own group with no link.
- Mixed catalogue widget: `ipywidgets.Tab` with one tab per origin, titled from the map; search still filters rows.
- ScreamingFace-only catalogue: single tab with the leaderboard link; `repr` unchanged (`Benchmarks(N)` — pinned by a prior cycle's test).
- `benchmark_card_html` shows the origin and its source link.

## Acceptance

- Mixed catalogue → one tab per origin with its source link (widget + static HTML).
- Our-boards-only catalogue → single tab; all prior tests green unmodified.
- Unknown origin decodes and renders; SDK never validates against the Engine's closed set.
- `run_gates.py screamingface` all green (95% coverage, notebooks deterministic, build + distribution checks).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `packages/screamingface/CHANGELOG.md` (interface-change entry, demanded by the public-surface tripwire) and `packages/screamingface/tests/public_surface_snapshot.json` (regenerated via `UPDATE_SURFACE_SNAPSHOT=1` for the new `Benchmark.origin` field). `_ui/catalog.py` also gained a `_body` hook on the base `_Catalog` so the tabbed benchmark body plugs in without duplicating the widget scaffold.
- **Commits:** 6b03f24c — feat(screamingface): show the benchmark catalogue as one tab per origin
- **Gates:** `run_gates.py screamingface --skip-append-only` ALL GREEN (ruff check/format, pyright, pytest cov ≥95%, notebooks deterministic, uv build, distribution check). 10 new tests + 2 widget tests (widget pair verified green under `--extra notebook`; they importorskip in the plain lane).
- **Deviations:** append-only check flagged the regenerated `public_surface_snapshot.json` (a data snapshot, not a test edit); owner approved `--skip-append-only` in-session. No prior test files modified.
