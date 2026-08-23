# OME-933 — Live Evaluation progress (spec)

- **Linear:** https://linear.app/openmined/issue/OME-933/redesign-live-evaluation-progress
- **Landing:** `packages/screamingface`
- **Dependency:** `OME-950` supplies relative URL4 route names in ordinary terminal spans
- **Status:** approved 2026-08-23

## Outcome

`sf.evaluate(...)` shows one stable row per Candidate from launch through the authoritative final
Report. Each row advances independently as terminal benchmark Cases arrive, stays visibly alive
while work is in flight, and freezes with the final score and evidence when decoding completes.

The design uses only public Events the Client already receives. It adds no progress event, wire
schema, Benchmark hook, Engine adapter, URL4 expression, or Client-side scoring logic.

## Execution facts

- One Candidate is one independently submitted Engine Run.
- Candidate Runs can overlap and their Events can interleave.
- The Client knows the ordered Candidates before execution starts. Ordinary Benchmark evaluation
  also knows the selected Case count; opaque `sf.evaluate(url4)` replay learns it only from the
  final decoded Report.
- The transport accepts one Event observer for each Run.
- The transport's existing Run state validates sequence continuity and suppresses replayed Events
  before invoking that observer.
- The Engine publishes a `Span` only when its URL4 node finishes.
- The shared Benchmark protocol executes one local `/benchmarks/case-execution` node for each
  selected Case.
- The final decoded `CandidateResult` is the only authority for score, coverage, failures, usage,
  and final Candidate classification.

## Candidate identity

The Evaluation runner binds an internal observer to the `Candidate` at the same point that it
calls `transport.run(candidate, observer)`. The built-in panel therefore receives
`(Candidate, Event)` without guessing identity from a model name, URL4 text, span source, or
arrival order.

The public `on_event(event)` callback remains unchanged. It receives each accepted Event once and
does not receive synthetic progress or reconciliation Events.

## Exact Case progress

A row increments `completed` only for a typed `Span` satisfying both predicates:

```python
event.operation == "RelUrlNode"
event.name == "/benchmarks/case-execution"
```

Both `status="ok"` and `status="error"` count because both mean that Case-execution node reached a
terminal outcome. Failure is evidence about that completion, not a reason to hide the completion.

For ordinary Benchmark evaluation, each row's denominator is the selected
`evaluation.case_count`. `42 / 100` means 42 terminal Cases have been observed for that Candidate;
it is not Case ID 42 and does not claim which Case is currently executing. The display never
exceeds its known total.

Opaque `sf.evaluate(url4)` replay has no separate selected-count input. It shows the exact observed
numerator as `42 cases finished` while running, then learns the denominator from the authoritative
Report. The Client does not parse URL4 to invent execution context.

No other structural span counts. In particular, a `RemoteFetchNode` with the same unqualified
path does not count because its operation differs. Model spans cannot stand in for Cases because
one Case may make zero, one, or many model calls.

While a Run is live, the row preserves only the terminal Case spans actually observed. Once a
valid final CandidateResult decodes, its complete CaseResults reconcile the terminal display to
the authoritative selected count. This also clamps opaque URL4 replay if its previously unknown
denominator is smaller than the observed stream count.

## State model

Rows stay in input order and use these primary statuses:

| Status | Evidence |
|---|---|
| `Queued` | The Candidate exists but its bound observer has not received a root `Started`. |
| `Running` | Its root Run started and no authoritative CandidateResult has decoded. |
| `Finished` | Its CandidateResult decoded successfully. |
| `Run failed` | A terminal failure or Client result-contract failure left no CandidateResult. |
| `Stopped` | The Run reported `stopped`, or a user interruption stopped an already-started Run. |
| `Timed out` | The Run or Client explicitly reported a timeout. |
| `Not run` | Evaluation ended before the Candidate ever started. |

A successful root `Terminated` does not by itself show `Finished`; the row remains `Running` while
the returned body is decoded. On successful reconciliation, `Finished` may carry one secondary
result qualifier using the existing Report contract, in this precedence:

1. `Incomplete` when `score is None`.
2. Exact numeric grade coverage such as `1/2 graded` when `coverage < 1.0`.
3. `Warnings` when Candidate failures exist.
4. No qualifier for a clean result.

An actual terminal Event takes precedence over an inferred workflow outcome. Without one, only an
explicit user interruption maps to `Stopped` and only an explicit timeout maps to `Timed out`;
other failures map to `Run failed`. `Not run` requires runner-owned evidence that
`transport.run` was never entered; absence of a root `Started` Event is not treated as proof.

## Row evidence

The fixed column order is:

1. Candidate
2. Status
3. Cases
4. Score
5. Cost
6. Cache hit

While a row is Queued or Running, Score reads `Not scored yet`. A terminal row without a decoded
CandidateResult reads `Not scored`, because no score is still pending. After reconciliation it
shows the decoded benchmark-native score, or `Not scored` when the final score is `None`; the
Client never computes or estimates a score.

Cost sums accepted self-scoped Usage Events for that Candidate Run and reads `Not reported` until
evidence exists. Final CandidateResult usage reconciles it after decoding.

Cache hit shows only that Candidate Run's percentage from accepted Span provenance and the
authoritative cache-summary Log: `hits / (hits + misses)`, with bypasses excluded from the rate.
It reads `Bypassed` when cache outcomes were reported but every call bypassed, and `Not reported`
only when no cache outcome evidence exists. Detailed hit/miss/bypass evidence remains available
through Events and the final Report, not as a second aggregate band in the live widget.

The Status cell stays on one compact line: primary lifecycle state, optional final qualifier, and
elapsed time while Running. The live widget does not add a second Run activity section or duplicate
terminal wording such as `Stopped` plus `Run stopped`. It does not label activity `Answering` or
`Grading`, infer a current Case, invent typing dots, or animate fake work.
Elapsed time truncates fractional seconds: seconds are integral, minute durations retain integral
seconds, and hour durations drop seconds (`42s`, `1m 30s`, `1hr 30min`, `2hrs 45min`).
Running rows use the monotonic live clock; successfully reconciled rows retain the authoritative
duration from `CandidateResult.started_at` to `completed_at` instead of dropping elapsed time.

## Rendering lifecycle

Event folding is immediate and thread-safe. Rendering is coalesced behind a dirty signal so a
burst of Events produces at most roughly one notebook update per 100 ms. During a silent in-flight
model call, a one-second clock wake refreshes elapsed time so the panel still feels alive.

The benchmark name is the stable heading throughout the run. The panel does not replace it with a
large dynamic `Evaluating`, `Evaluation complete`, or `Evaluation ended` title, and it does not
repeat aggregate row-state counts beneath it. Candidate rows already own their exact lifecycle and
Running elapsed time. Their square status signal uses the static blue app accent for `Running`,
matching the canonical SFDS status recipe without adding a widget-specific motion pattern.

Final reconciliation or abort forces one synchronous terminal render, stops the clock, and leaves
the frozen panel visible. A compact right-aligned state on the benchmark-title row changes from
`evaluating… · 72%` to `complete · 1m 10s`, `stopped`, `timed out`, or `failed` using the same
truthful terminal evidence as the Candidate rows. Successful completion hides the now-redundant
100% progress track; interrupted or failed partial work retains the track when its denominator is
known. A renderer or notebook-comm failure remains decorative and cannot abort paid Engine work.

## Layout and SFDS v2

Content appears in this order:

1. Benchmark title with compact overall state right-aligned on the same row.
2. Paid-check disclosure, when applicable.
3. Overall Candidate-Case progress, only while the Evaluation is not successfully complete and
   every Candidate denominator is known.
4. Compact live receipt, with its height reserved before evidence exists.
5. Candidate table.
6. Global error, only when present.

Overall progress is `sum(completed Candidate Cases) / sum(planned Candidate Cases)`. It has no
fixed cap: ten Candidates over 100 Cases is 1,000 Case runs, while twenty Candidates over 2,450
Cases is 49,000. The UI reuses the canonical SFDS run-progress treatment: an 8px
gold-to-white-to-blue fusion-gradient fill whose leading edge remains blue, with the branded
`.11s linear` width transition. The title row's compact mono state reads
`evaluating… · 72%`. Exact per-Candidate Case counts remain in the table, while the progressbar's
accessible current and maximum values retain the aggregate count without duplicating it visually.
The fill may interpolate visually between exact endpoints, but the percentage changes only when
Case evidence changes. If any denominator is unknown, the bar is omitted rather than estimated,
while the truthful state remains visible without a percentage. On successful reconciliation, the
bar and redundant 100% disappear and the state reports `complete` with the authoritative total
duration from the earliest Candidate start to the latest Candidate completion.

The receipt is one muted mono line beneath the optional progress track, ordered by user value:
`cost $0.76 · 68 model calls · 202.9k in / 30.2k out`. It exposes only fields with evidence and is
visually empty before any exists, while reserving its one-line height so the Candidate table does
not jump when usage first arrives. It replaces the large three-cell aggregate strip without
changing the underlying live accounting.

After the authoritative Report reconciles, when exact evidence proves every observed model call
was a hit, with no miss, bypass, unaccounted call, non-zero cost, or non-zero token usage, the
receipt switches to the success narrative
`275 model calls · fully cached · no tokens billed`. It suppresses the misleading wall of
`cost $0.00 · ... · 0 in / 0 out`; the per-Candidate Cost cell still retains `$0.00`.

The semantic table fits all six columns within the available notebook width and does not introduce
its own horizontal scrollbar. Candidate cells show only the authored display name; the full model
route is redundant with the Recipe and Report surfaces and consumes the width needed by progress.
The header remains sticky, long truthful values may wrap, and there is no alternate stacked layout.
Candidate order never changes; there is no live rank, winner, or comparison treatment.
The fixed allocation prioritizes Candidate identity, then gives Cost and Cache hit enough room for
`Not reported`; Cases stays compact because its `x / N` values are short.
Cases, Score, Cost, and Cache hit use the canonical right-aligned SFDS numeric-column treatment.
The widget adds no horizontal shell padding because the notebook output cell already owns that
inset; title, progress, receipt, and table share one output-aligned left edge.

This is the SFDS v2 app register: IBM Plex Sans for prose and status, IBM Plex Mono for figures and
labels, square geometry, hairline rules, tabular numerals, blue informational activity, semantic
status colors, readable primary/secondary text roles, and equal light/dark behavior. There is no
gold or gradient outside the canonical fusion-progress treatment, and no shadow, rounded card,
fake avatar, or decorative low-contrast ink used as text.

The visual source of truth is the generated token sheet and table recipe from
`OpenMined/screamingface-brand` commit `7ea35a12608776ba3f811811578cec9fd5193b4f`
(2026-08-18). The shared notebook token bridge uses that revision's app-theme light/dark aliases;
the table uses its 13px mono body, 11px medium label, 0.1em label tracking, 12×16px wrapped-cell
spacing, stronger header separator, and 8px status rhythm.

There is no invented phase animation. The overall track uses the canonical SFDS fusion-gradient
and width transition; exact `completed / total` Case text avoids redundant per-row bars and keeps
ten-Candidate tables calm and compact.

## Accessibility

- Use a real `<table>` with a descriptive caption and scoped column headers.
- Keep the table and its cells native rather than adding fake controls.
- Do not place `aria-live` on the changing table or whole panel.
- Use one separate polite announcement region for Evaluation start, Candidate terminal states, and
  whole-Evaluation completion only.
- Status cannot rely on color alone: every square indicator has visible text.
- Case progress is exposed as ordinary readable `completed / total` text.
- Focus is never moved when a Candidate changes state.

## Compatibility and boundaries

- Existing Report and CandidateResult values are unchanged.
- Existing public Event values, order, replay behavior, and `on_event` callback are unchanged.
- Existing text progress remains the non-notebook fallback.
- Existing paid-check disclosure and cache-provenance collection remain present; only the
  redundant aggregate cache/activity rendering is removed from this widget.
- No Benchmark, screamingface-engine, AIGateway, Scoreboard, or additional URL4 change.
- No URL4 parsing in the Client.
- No provisional score, exact live failed/refused Case counter, current Case identity, phase
  inference, legacy progress schema, or compatibility fallback before V1.

## Acceptance

1. Ten Candidates over 100 Cases render ten stable rows with independent exact `x / 100` counts.
2. Interleaved and out-of-order Candidate Events update only their bound row.
3. Only the exact `(RelUrlNode, /benchmarks/case-execution)` pair advances progress; an error span
   advances it and a RemoteFetchNode/model/other structural span does not.
4. Transport replay does not double-count an accepted terminal span.
5. Early Run termination preserves the observed count and never fabricates 100%.
6. Score remains unavailable until CandidateResult decoding and then matches it verbatim.
7. Queued, Running, Finished, Run failed, Stopped, Timed out, and Not run are covered for sync and
   async Evaluations, including the existing eight-Run concurrency gate.
8. Cost, per-Candidate cache hit, aggregate totals, paid-check disclosure, and cache-provenance
   reconciliation retain their existing evidence rules; aggregate usage renders as one compact
   evidence-only receipt and aggregate cache/activity sections are absent.
9. Public `on_event` receives the same accepted Events once, with no synthetic additions.
10. Rendering is coalesced, the stable benchmark heading and compact progress state remain
    truthful, the silent clock advances, one terminal render is forced, and the frozen panel
    remains visible.
11. The six-column table fits without its own horizontal scroll, hides redundant model routes and
    progress bars, uses limited announcements, and renders correctly in light and dark.
12. One overall bar reports exact completed/planned Candidate-Case runs without a fixed cap or
    invented denominator, using the canonical SFDS gradient, transition, and compact
    `state · percent` line; accessible values retain the exact aggregate count.
13. Full `py-screamingface` gates, notebook checks, build, and distribution checks pass.
14. Shared notebook light/dark tokens and Evaluation table styling match the pinned current
    `screamingface-brand` revision rather than the older vendored palette snapshot.
15. A provably fully cached run is described as a success without zero-token telemetry, while any
    missing, bypassed, missed, or contradictory evidence keeps the ordinary receipt.
