# OME-933 — Live Evaluation progress (spec)

- **Linear:** https://linear.app/openmined/issue/OME-933/redesign-live-evaluation-progress
- **Landing:** `packages/screamingface`
- **Dependency:** `OME-950` supplies relative URL4 route names in ordinary terminal spans
- **Status:** awaiting implementation approval

## Outcome

`sf.evaluate(...)` shows one stable row per Candidate from launch through the authoritative final
Report. Each row advances independently as terminal benchmark Cases arrive, stays visibly alive
while work is in flight, and freezes with the final score and evidence when decoding completes.

The design uses only public Events the Client already receives. It adds no progress event, wire
schema, Benchmark hook, Engine adapter, URL4 expression, or Client-side scoring logic.

## Execution facts

- One Candidate is one independently submitted Engine Run.
- Candidate Runs can overlap and their Events can interleave.
- The Client knows the ordered Candidates and selected Case count before execution starts.
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

Each row's denominator is the selected `evaluation.case_count`. `42 / 100` means 42 terminal
Cases have been observed for that Candidate; it is not Case ID 42 and does not claim which Case is
currently executing. The display never exceeds its known total.

No other structural span counts. In particular, a `RemoteFetchNode` with the same unqualified
path does not count because its operation differs. Model spans cannot stand in for Cases because
one Case may make zero, one, or many model calls.

If a Run terminates before every terminal Case span is observed, its row preserves the honest
observed count. The Client does not fabricate the missing completions from the final result.

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
2. `Partial` when `coverage < 1.0`.
3. `Warnings` when Candidate failures exist.
4. No qualifier for a clean result.

An actual terminal Event takes precedence over an inferred workflow outcome. Without one, only an
explicit user interruption maps to `Stopped` and only an explicit timeout maps to `Timed out`;
other failures map to `Run failed`. A Candidate with no root start maps to `Not run`.

## Row evidence

The fixed column order is:

1. Candidate
2. Status
3. Progress
4. Score
5. Cost
6. Cache

Before reconciliation, Score reads `Not scored yet`. After reconciliation it shows the decoded
benchmark-native score, or `Not scored` when the final score is `None`; the Client never computes
or estimates a score.

Cost sums accepted self-scoped Usage Events for that Candidate Run and reads `Not reported` until
evidence exists. Final CandidateResult usage reconciles it after decoding.

Cache uses that Candidate Run's accepted Span provenance and authoritative cache-summary Log:
`hits / (hits + misses)`, with bypasses excluded from the rate. It reads `Not reported` until
evidence exists. The existing aggregate cache-provenance band remains below the Evaluation totals.

The Status cell may show concise secondary activity from real Events, such as a completed, failed,
or refused model call and elapsed time. It does not label activity `Answering` or `Grading`, infer a
current Case, invent typing dots, or animate fake work.

## Rendering lifecycle

Event folding is immediate and thread-safe. Rendering is coalesced behind a dirty signal so a
burst of Events produces at most roughly one notebook update per 100 ms. During a silent in-flight
model call, a one-second clock wake refreshes elapsed time so the panel still feels alive.

Final reconciliation or abort forces one synchronous terminal render, stops the clock, and leaves
the frozen panel visible. A renderer or notebook-comm failure remains decorative and cannot abort
paid Engine work.

## Layout and SFDS v2

Below the heading, content appears in this order:

1. Paid-check disclosure, when applicable.
2. Candidate table.
3. Aggregate model calls, tokens, and cost.
4. Existing aggregate cache-provenance band.
5. Collapsed Run activity.
6. Global error, only when present.

The table is semantic HTML inside its own horizontal-scroll container. It keeps a sticky header and
sticky Candidate column, a minimum width sufficient for all six columns, and no alternate stacked
layout. Candidate order never changes; there is no live rank, winner, or comparison treatment.

This is the SFDS v2 app register: IBM Plex Sans for prose and status, IBM Plex Mono for figures and
labels, square geometry, hairline rules, tabular numerals, blue informational activity, semantic
status colors, readable primary/secondary text roles, and equal light/dark behavior. There is no
gold, gradient, shadow, rounded card, fake avatar, or decorative low-contrast ink used as text.

Motion is functional and restrained. Progress fills may transition when motion is allowed; under
`prefers-reduced-motion: reduce` they update without transition. There is no looping animation.

## Accessibility

- Use a real `<table>` with a descriptive caption and scoped column headers.
- Keep the table keyboard-scrollable without turning cells into fake controls.
- Do not place `aria-live` on the changing table or whole panel.
- Use one separate polite announcement region for Evaluation start, Candidate terminal states, and
  whole-Evaluation completion only.
- Status cannot rely on color alone: every square indicator has visible text.
- Progress exposes an accessible name and numeric current/max values.
- Focus is never moved when a Candidate changes state.

## Compatibility and boundaries

- Existing Report and CandidateResult values are unchanged.
- Existing public Event values, order, replay behavior, and `on_event` callback are unchanged.
- Existing text progress remains the non-notebook fallback.
- Existing paid-check disclosure and aggregate cache-provenance behavior remain present.
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
8. Cost, cache, aggregate totals, paid-check disclosure, and cache-provenance reconciliation retain
   their existing evidence rules.
9. Public `on_event` receives the same accepted Events once, with no synthetic additions.
10. Rendering is coalesced, the silent clock advances, one terminal render is forced, and the
    frozen panel remains visible.
11. The table horizontally scrolls, preserves keyboard access, uses limited announcements, honors
    reduced motion, and renders correctly in light and dark themes.
12. Full `py-screamingface` gates, notebook checks, build, and distribution checks pass.
