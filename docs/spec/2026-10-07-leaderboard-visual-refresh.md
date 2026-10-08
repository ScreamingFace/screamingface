# portal-featured-benchmarks — a curated benchmark shortlist, surfaced first

## Problem

`benchmark.html`'s tab strip and `index.html`'s catalogue render every registered benchmark
(~65) at equal weight — a flat, eight-row wrap. The boards readers should land on are buried,
and the page sprawls. There is no notion of a featured subset anywhere in the portal.

## Rule

A small, ordered editorial shortlist surfaces first across the portal:

```
FEATURED = [draco-3pass, contracteval, frontierscience, healthbench-professional, ifeval]
```

- **Tab strip (`benchmark.html`):** the featured boards present in the catalog render as
  prominent `<a>` tabs, in FEATURED order; every other board moves into one native
  `<select>` "More benchmarks" control that navigates to the chosen board. A non-featured
  board that is the current page is shown as the selected option (no featured tab is active).
- **Catalogue (`index.html`):** rows are ordered featured-first (FEATURED order), then the
  rest in catalog order. All rows stay visible — it is a catalogue.

INVARIANT: the shortlist is editorial curation, so it lives beside `listedBenchmarks` in
`leaderboard-logic.js` (pure, DOM-free, unit-tested) — not hardcoded in the render code. Order
is significant. A featured id the catalog does not return is skipped, never fabricated — the
same fail-open, defensive posture as `listedBenchmarks`.

## Not changed

- The `/v1/benchmarks` API and the backend — this is portal-only.
- Private-board handling: the tab strip has never run `listedBenchmarks`; it still doesn't, so
  a private board (if any) simply lands in the dropdown. OME-1147 (unlisting worst-30%) is a
  separate unit and is not entangled here.
- `healthbench-worst30` is deliberately NOT featured (the requester meant "HealthBench" =
  Professional; worst-30% is separately slated to be hidden per OME-1147).

## Tests

- `partitionFeatured(benchmarks) → {featured, rest}`: featured in FEATURED order regardless of
  input order; a missing featured id skipped; `rest` excludes featured and preserves input
  order; no board in both lists; non-array → `{featured:[], rest:[]}`; input not mutated.
- `FEATURED_BENCHMARK_IDS` pins `healthbench-professional` and `draco-3pass`.
- DOM rendering (the `<select>`, index ordering) is not unit-tested — `main.js` has no DOM
  harness, consistent with the rest of the portal; covered by manual verification.
