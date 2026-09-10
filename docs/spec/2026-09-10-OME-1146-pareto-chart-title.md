# OME-1146 (part 1) — Rename the Pareto chart

Status: owner-approved · Stack: scoreboard

## Problem

The benchmark page's Pareto chart is headed "Score for cost". OME-923 part B introduced the term
"Pareto frontier" in the same page's legend and mark labels, so the chart and the thing it plots
now have two different names. "Pareto Frontier (cost/score)" is the name used everywhere else.

## Scope — the rename only

OME-1146 asks for two changes. This unit delivers one of them.

### D1 — The heading and its accessible label are renamed together

`<h2>Score for cost</h2>` becomes `<h2>Pareto Frontier (cost/score)</h2>`, and the scroll region's
`aria-label` becomes `Pareto Frontier (cost/score) chart, horizontally scrollable`. They are one
change: a screen-reader user navigating by region hears the label, and a sighted user reads the
heading. Renaming one without the other makes the page describe itself two ways.

### D2 — The self-reported-costs disclaimer is NOT touched

OME-1146 also asks to delete the disclaimer at `benchmark.html:85` and `:123`, on the grounds that
submissions are verified by default. That half is **deliberately excluded from this unit** and the
ticket stays open for it. Two reasons, both recorded in the codebase:

- `scores/models/score.py`, above `verified_by_screamingface = True`: *"the public portal must not
  claim more than this … Change the default and that copy together, or the board lies."* The
  default is a placeholder from `OME-820`; `OME-821`, which would give it a real signal, is in
  Backlog.
- `scores/schemas.py`, on `LeaderboardEntry.run_cost_usd`: *"Self-reported and unverifiable:
  re-running a submission tells us what *we* paid, not what the submitter paid … never as a
  verified figure."* Cost verification is not score verification, so the disclaimer stays true
  even after `OME-821`.

`OME-1143` — filed the same afternoon — additionally reports that the costs on this chart are
currently wrong for cache-served runs. Removing the line that says they are unverified while that
is open is the wrong direction.

Dropping the disclaimer also reverses `OME-770` D11. A reversal of a recorded decision is an owner
call, and the question is posted on the ticket awaiting an answer.

### D3 — No behaviour changes

No JS, no data, no API. `pareto-chart.js` never referenced the old string, confirmed by grep over
`apps/scoreboard/`.

## Verification contract

- the rendered page has no "Score for cost" anywhere;
- the heading and the scroll region's `aria-label` carry the same new name;
- the disclaimer, the provenance comment, and every other caption line are unchanged;
- full Scoreboard gates green.

## Confidence-Gate exception

`test_portal_static.py::test_pareto_chart_shell_is_bounded_provenanced_and_loaded_before_its_caller`
asserts the old `aria-label` string at line 189. That assertion names the exact text this unit
renames, so it cannot survive it. Its seven other assertions — including the disclaimer at line
192, which this unit deliberately preserves — are unchanged.

## Non-goals

- the disclaimer at `:85` and `:123`, and the `OME-770` D11 provenance comment at `:113–116`;
- any change to what the chart plots or how the frontier is computed;
- `OME-1145`'s open-share figure, which sits on the same page.
