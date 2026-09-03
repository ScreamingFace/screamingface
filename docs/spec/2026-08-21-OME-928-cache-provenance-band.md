# OME-928 — Cache provenance as a diagnostic band (spec)

Status: approved 2026-08-21. Supersedes the presentation half of the `OME-692` increment spec
(same date, filed under that id) — that spec's contract for `Span.cache_status` / `cache_reason`
still holds and is carried forward unchanged.

Related: `OME-692` (Blocked; owns cache write/key/age and saved-cost totals) and `OME-907`
(investigate why AIGateway cache prefill isn't hit on first-time Draco runs — this instruments it).

## Outcome

While `sf.evaluate(...)` runs, its notebook panel shows cache provenance as one full-width band
beneath a three-column stat row: the hit rate, the observed hit/miss counts, and — only when
bypasses occurred — the bypass total with the Engine's per-reason breakdown. Public
`sf.events.Span` values retain `cache_status` and `cache_reason` so callbacks see the same evidence.

## Why a band rather than a fourth stat cell

Measured, not preferred. `.sf-ui` caps at `max-width:920px` and the stat grid collapses to one
column only below `680px`, so a fourth cell is ~206px — about 32 characters — at maximum width,
before its label and value. `unsupported_control 91` is 22 characters on its own. A fourth cell
therefore admits either no reasons at all, which cannot distinguish a cold cache from a silently
broken one, or truncated reasons, which read as fact while hiding the number that mattered.

## Contract

- `Span.cache_status` is `"hit"`, `"miss"`, `"bypass"`, or `None`.
- `Span.cache_reason` is a non-blank string or `None`; the Client preserves the Engine vocabulary
  without interpreting it.
- Unknown or absent provenance remains `None`. The Client never infers cache behavior from latency,
  tokens, cost, or model identity.
- Each cache-bearing model Span increments that Run's live count exactly once. A bypass Span also
  tallies its reason, or `unstated` when it names none.
- An Engine cache-summary Log **replaces** that Run's live counts and its reason map. It is the
  authoritative final reconciliation and is never added to the Span-derived values.
- Reason counts are read from summary attributes prefixed `cache.bypass.`. The total
  `cache.bypasses` does not match that prefix and is never mistaken for a reason bucket.
- Evaluation totals sum the latest authoritative values for every Candidate Run.
- Hit rate is `hits / (hits + misses)`. Bypasses are displayed but excluded from the denominator.
  With no hit or miss evidence, the rate is unavailable rather than zero.

## Presentation

The stat row is three cells — model calls, tokens, cost. One full-width hairline band follows it.

```
cache   62.0%   62 hit · 38 miss
cache   66.7%   6 hit · 3 miss · 91 bypassed — unsupported_control 91
cache   —       no cache activity reported
```

- The bypass segment is **absent** from the rendered HTML when bypasses are zero. A healthy run is
  one number; the band only grows when it has something to report.
- Reasons render descending by count, then by name for a stable order, verbatim. They **wrap**
  rather than truncate: at 680px one reason fits, at 760px two, at 920px three, so any fixed cap
  would be wrong at some width and CSS cannot vary it without container queries.
- Body text uses `--sf-ink-2`. `--sf-ink-3` is not a text color under SFDS and measures 3.20:1
  (light) and 3.83:1 (dark) against the panel ground — below AA. `--sf-ink-2` measures 6.61 / 7.48.
- Existing app-register system otherwise: IBM Plex Mono for labels and figures, tabular numerals,
  square geometry, hairline rules, semantic existing tokens only, no new colour or decoration.

## Deliberately not classified

The Client does not sort reasons into expected-versus-defect. `opted_out` (caching off by request)
and `unsupported_control` (a control key the gateway's closed grammar rejects, silently costing
every hit) are both shown verbatim, and the count against the run's total does the signalling. A
Client-side severity list would be a second copy of the gateway vocabulary and would drift from
`PUBLISHED_CACHE_REASONS`, which is published in exactly one place for that reason.

## Non-goals

- Persisting provenance onto `CandidateResult`; no run-to-run comparison here.
- Computing or displaying saved money.
- Cache keys, writes, or age.
- Any Engine, gateway, or wire change — including gateway-published reason severity, which would
  remove the duplication risk above but is cross-cutting and out of scope.
- Client-owned cache lookup, mutation, or fingerprinting.
- Closing `OME-692` while its saved-accounting dependencies remain unfinished.

## Known limitations

- Live Span-derived reasons are uncapped; the authoritative summary caps at 16 buckets plus
  `other`. A run with more than 16 distinct reasons would see the displayed set shrink when the
  summary lands. Accepted: the gateway's real vocabulary is a handful of tokens.
- `other` summed across Candidate Runs collapses different reason sets — honest per run, imprecise
  in aggregate. Not surfaced, because explaining it would cost more clarity than it buys.

## Acceptance

1. Decoding a cache-bearing Engine Span preserves status and reason in `sf.events.Span`.
2. Invalid status or blank reason fails the existing strict Event contract.
3. Live Spans update hits, misses, bypasses, reasons, and the rate immediately.
4. A summary Log replaces, rather than doubles, both the counts and the reason map for its Run.
5. Multiple Candidate Runs aggregate without one Run overwriting another.
6. Zero bypasses renders no bypass segment at all.
7. No provenance renders an unavailable metric, not a fabricated zero.
8. `unstated` and `other` remain distinct buckets.
9. Existing progress, cost, tokens, completion, and text-summary behavior remains intact.
