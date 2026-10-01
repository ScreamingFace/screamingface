# OME-1146 (part 2) — Drop the self-reported-costs disclaimer

Status: owner-approved (in conversation, 2026-09-29) · Stack: scoreboard

## Problem

Part 1 renamed the Pareto chart but deliberately kept the "Costs are self-reported, not verified
by re-running" disclaimer, because dropping it reverses `OME-770` D11 and `OME-1143` (costs are
wrong for cached runs) was open. Both conditions are still technically true today — `OME-1143`
hasn't shipped its fix (`OME-1382`) yet — but the owner has decided to proceed anyway rather than
wait, accepting the chart will be temporarily inaccurate-but-undisclaimed in the meantime.

## Scope — the disclaimer removal, folded into an existing note

### D1 — The two disclaimer lines are removed

`benchmark.html:85` (figcaption) and `:120` (legend item), both reading "Costs are self-reported,
not verified by re-running" / "costs are self-reported, not verified by re-running".

### D2 — Their job moves into the page's existing "Read this first" note

`benchmark.html:45-49` currently reads: "The top of this board is the best submitted result: the
current SOTA. Every row keeps its URL4 expression, so you can rerun any claim before trusting it."

New: "...so you can rerun any claim, score, or cost, before trusting it." One shared instruction
covering score and cost alike, rather than a cost-specific caveat living apart from it. This was
the owner's own proposed alternative, posted to the ticket 2026-09-25, adopted here without a
reply from Irina — a deliberate choice to proceed rather than wait, recorded on the ticket.

### D3 — The now-dangling provenance comment is removed

`benchmark.html:111-113` explains why the legend disclaimer exists ("states that frontier
membership uses self-reported costs rather than presenting those figures as verified"). Once the
thing it explains is gone, the comment would describe a line that no longer exists. Remove it.

### D4 — No behaviour changes

No JS, no data, no API — same boundary part 1 drew. `pareto-chart.js` doesn't reference either
disclaimer string.

## Known trade-off, not a mistake

`OME-1143` (cached runs submit $0.00 for `draco-3pass`) is still open. `OME-1382` (rank/display
on spend + cache savings, gated on `run_cost_status`) is designed but unimplemented. Until it
ships, this chart's cost numbers for cache-hit rows are genuinely misleading, and after this unit
nothing on the page calls that out specifically — the general "rerun any claim... before trusting
it" note is the only remaining hedge. Accepted knowingly; not something this unit fixes.

## Verification contract

- no "self-reported" cost disclaimer anywhere in `benchmark.html`
- the "Read this first" note's new wording is present
- part 1's rename (heading, aria-label, "Score for cost" absent) is untouched
- full Scoreboard gates green

## Confidence-Gate exception (expected)

`test_pareto_chart_heading_and_label_name_the_pareto_frontier`'s existing assertion at line 233
names the exact string this unit removes, so it cannot survive unchanged — same append-only
pattern part 1 hit and recorded.

## Non-goals

- `OME-1143`'s actual cost-accuracy bug — tracked separately, `OME-1382` fixes it
- `OME-1319`'s broader "nothing is verified by re-running" question — a different axis, still open
  with Irina, untouched by this change
- any change to what the chart plots or how the frontier is computed
