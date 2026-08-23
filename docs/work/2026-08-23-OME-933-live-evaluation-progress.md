---
ticket: OME-933
stack: screamingface
status: in_progress
started: 2026-08-23
finished:
---

# OME-933 — redesign live Evaluation progress

## Intent

Replace the aggregate notebook progress panel with a truthful, always-alive per-Candidate table.
Use the existing typed Event stream for activity, cost, cache, lifecycle, and exact terminal Case
counts; keep final Candidate Results authoritative for scores and outcome classification.

## Planned changes

- `docs/tasks/2026-08-21-OME-933-live-evaluation-progress.md`
- `docs/spec/2026-08-23-OME-933-live-evaluation-progress.md`
- `docs/plan/2026-08-23-OME-933-live-evaluation-progress.md`
- `docs/work/2026-08-23-OME-933-live-evaluation-progress.md`
- `packages/screamingface/src/screamingface/_evaluation/runner.py`
- `packages/screamingface/src/screamingface/_evaluation/progress.py`
- `packages/screamingface/src/screamingface/_evaluation/url4.py`
- `packages/screamingface/src/screamingface/_ui/evaluation_state.py`
- `packages/screamingface/src/screamingface/_ui/evaluation_view.py`
- `packages/screamingface/tests/test_live_candidate_progress.py`
- `packages/screamingface/tests/test_evaluation_progress_panel.py`
- `packages/screamingface/tests/test_progress.py`
- `packages/screamingface/tests/test_check_disclosure_display.py`

## Test plan

- RED first for Candidate-scoped event routing and exact terminal Case span counting.
- RED first for 10 Candidates × 100 Cases, concurrent out-of-order completion, replay-safe folding,
  terminal failures, and final-result reconciliation.
- RED first for SFDS table structure, six-column width fit, native table semantics, reduced motion,
  and light/dark token use.
- Preserve existing Event callbacks, final Reports, cache provenance, cost accounting, notebook
  distribution, and all prior progress tests.

## Acceptance

- Every Candidate has one stable row in input order with truthful Status, Cases, Score, Cost,
  and Cache-hit evidence.
- Progress counts only `(operation="RelUrlNode", name="/benchmarks/case-execution")` terminal spans
  and uses the Evaluation's selected Case count as its denominator.
- Existing Events keep running rows alive; the UI never fabricates phases, delays, values, or Case
  identities.
- Scores appear only from successfully decoded final Candidate Results.
- The app-register SFDS v2 surface remains accessible, readable in light and dark, and fits all six
  columns without its own horizontal scrollbar.
- The full `screamingface` quality gate passes.

## Outcome

- **Actual files:** the spec/task mirror and every production/test file listed above.
- **Commits:** `f718b42b` (approved spec/plan), `aa7d3282` (Candidate-scoped implementation).
- **Gates:** the latest compact-header follow-up passes 79 focused progress/evaluation tests,
  Ruff, Pyright, and the full package suite (1,064 passed, one skipped). The earlier complete
  official `screamingface` gate also passed ≥95% coverage, notebook validation, build, and
  distribution checks before the owner's two local notebook edits; those edits remain untouched.
- **Deviations:** opaque URL4 replay cannot know its selected denominator before result decoding,
  so it truthfully renders the exact observed numerator until the final Report supplies the total.
  The approved plan intentionally replaced aggregate-panel assertions with Candidate-table
  assertions; the append-only detector was skipped only for that recorded contract replacement,
  while every retained and new test still ran in the full gate.

## Owner visual-QA follow-up

The first live notebook check showed that the full model route duplicated Candidate identity and
that the table's forced minimum width created unnecessary horizontal scrolling. The approved
follow-up removes that secondary route line and lets all six columns fit the notebook width. This
replaces the earlier horizontal-scroll acceptance rule; no legacy layout fallback is retained.
The same visual check exposed duplicate terminal text in Status. Status is therefore a single
compact lifecycle line, while detailed Event activity remains available in the collapsed log.
Per-row progress bars were also removed after owner review because they duplicated the exact Case
fraction and consumed width without adding information.
The per-Candidate Cache header was clarified to Cache hit; its cell stays a percentage while the
existing aggregate band owns detailed hit, miss, bypass, and reason evidence.
Terminal rows without a CandidateResult say Not scored rather than the still-pending Not scored
yet used by Queued and Running rows.
The owner-approved liveness pass adds an exact state/elapsed subtitle. A subsequent strict-brand
review removed the custom pulse: Running uses the canonical static blue SFDS status square.
The same review approved one uncapped overall Candidate-Case progress track. Its first iteration
used exact summed evidence, a static solid-blue fill, and disappeared when a denominator was
unavailable.
Owner visual QA then removed the redundant visible title/count above that track; accessible current
and maximum values remain on the progressbar itself.
The next live comparison identified the exact branded target in `screamingface-brand`'s run widget.
The approved correction replaces the generic blue fill with its anchored SFDS fusion gradient,
`.11s linear` width transition, and compact `evaluating… · percent · completed/total` line.
The final header simplification makes the benchmark name the stable title and removes the large
dynamic Evaluation headline plus the redundant aggregate row-state subtitle. Terminal workflow
state moves into the compact progress line.
Owner visual QA replaced the three large usage boxes with one compact evidence-only receipt, with
running cost first, then model calls and tokens. The empty-prone aggregate cache band and collapsed
Run activity were removed from the live widget; their underlying Event/Report evidence remains.
The widget's redundant 14px side padding was removed because Jupyter already owns the output-cell
inset; every widget element now shares the notebook output edge.
Final width QA reduced the oversized Cases allocation and reassigned it to Cost and Cache hit so
their truthful `Not reported` values do not clip.
The final SFDS fidelity pass uses the generated tokens and table recipe from
`OpenMined/screamingface-brand` commit `7ea35a12608776ba3f811811578cec9fd5193b4f`
(2026-08-18). Because the shared notebook token bridge had drifted from that source, the approved
change updates it centrally and aligns the Evaluation table's typography, spacing, separators,
weights, and semantic status colors with the same revision.
Owner visual QA removed the aggregate `completed/total` suffix from the progress label because the
Candidate table already owns exact visible Case fractions. The compact line now reads
`evaluating… · percent`; the progressbar retains exact current and maximum accessibility values.
Candidate elapsed time now truncates fractional seconds because the panel refreshes once per
second. It renders integral seconds below an hour and drops seconds at hour scale.
The final owner-approved table pass replaces vague `Partial` with exact graded coverage, retains
authoritative final duration, right-aligns numeric columns, and reserves the compact receipt's
height before usage evidence arrives so the table never jumps.
Cache diagnosis found that the local stack intentionally leaves `AIGW_REQUEST_CACHE_ENABLED` off,
so its model calls report bypass rather than hit/miss. The table now renders `Bypassed` for that
reported state and reserves `Not reported` for genuinely absent cache outcome evidence.
The fully cached receipt is now an evidence-gated success state: all observed model calls must be
accounted for as hits per Candidate, with no miss, bypass, non-zero usage, or non-zero cost. It
renders `model calls · fully cached · no tokens billed` and leaves `$0.00` to the Cost column.
The final owner-approved header compaction places live Evaluation state at the right edge of the
benchmark-title row so changing receipt digits never shift it. The canonical progress track stays
visible only while progress is actionable, including partial stopped/failed runs; successful
completion removes the redundant full bar and 100% and reports `complete · duration` from
authoritative Candidate Result timestamps. The receipt remains left-aligned and reserved, and the
Candidate table remains the canonical detail surface for both one and many Candidates.
