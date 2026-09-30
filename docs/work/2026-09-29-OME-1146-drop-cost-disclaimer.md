---
ticket: OME-1146
stack: scoreboard
status: in_progress
started: 2026-09-29
finished:
---

# OME-1146 (part 2) — Drop the self-reported-costs disclaimer

## Intent

Part 1 (2026-09-10) renamed the Pareto chart and deliberately left the disclaimer alone, because
`OME-1143` (cached runs submit $0.00) was open and `OME-770` D11 required the "self-reported, not
verified" caveat while costs could be wrong. This unit does the second half: drop the disclaimer,
and fold its job into the page's existing "Read this first" note instead.

**Known, accepted trade-off:** `OME-1143` is still open; `OME-1382` (its fix) is designed but not
shipped. This chart will show a temporarily-inaccurate cost picture for `draco-3pass` with no
disclaimer calling that out specifically, until `OME-1382` lands. Decision recorded on the ticket,
owner-approved in conversation.

## Planned changes

- `apps/scoreboard/portal/benchmark.html`:
  - `:45-49` — extend the "Read this first" note: "...so you can rerun any claim, score, or cost,
    before trusting it."
  - `:85` — remove the figcaption disclaimer span
  - `:111-113` — update/remove the comment explaining the legend disclaimer (it would dangle once
    the thing it explains is gone)
  - `:120` — remove the legend-item disclaimer span
- `apps/scoreboard/tests/unit/test_portal_static.py`:
  - `:192` (`test_pareto_chart_shell_is_bounded_provenanced_and_loaded_before_its_caller`) —
    disclaimer assertion flips from present to absent
  - `:216-233` (`test_pareto_chart_heading_and_label_name_the_pareto_frontier`) — docstring and
    assertion both currently pin "renamed but still disclaimed"; rewrite for part 2's actual state
  - new assertion (or new test) for the extended "Read this first" copy

## Test plan

RED first:
- disclaimer absent from `benchmark.html` (figcaption and legend both)
- "Read this first" note contains the new cost-rerun wording
- existing rename assertions (heading, aria-label, "Score for cost" absent) stay green — untouched
  by this unit

## Acceptance

- no self-reported-costs disclaimer anywhere in the portal
- "Read this first" note covers cost the same way it already covers score/claims
- rename from part 1 untouched
- full Scoreboard gates green, append-only exception recorded the same way part 1's was

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `apps/scoreboard/portal/benchmark.html` — extended note, removed
  figcaption disclaimer, removed the now-dangling provenance comment, removed the legend item.
  `apps/scoreboard/tests/unit/test_portal_static.py` — flipped one assertion, rewrote one test's
  docstring/assertions, added one new test.
- **Commits:** `176519ab` fix(scoreboard): drop the self-reported-costs disclaimer on the Pareto
  chart (PR #1123); review-round-1 fix on top (below).
- **Gates:**
  - `run_gates.py scoreboard --base origin/main --skip-append-only` → ALL GATES GREEN: ruff check,
    ruff format, pyright, pytest with `--cov-fail-under=80`, all three portal node suites.
  - `run_gates.py scoreboard --base origin/main` → append-only FAILS on
    `tests/unit/test_portal_static.py`, citing exactly the lines this unit's spec named
    (192, 222-225, 233) as changed. Matches the recorded Confidence-Gate exception — an existing
    test's docstring and assertion changed to reflect the new state, not a silent deletion.
- **Deviations:** none from the plan.

## Review round 1 (2026-09-30, self-review)

**Declined, owner 2026-09-30: rewording the note to "your own run cost".** The finding: a rerun
measures what the rerunner pays now, not the submitter's historical cost, so "rerun any claim,
score, or cost" overstates what a rerun checks. It was applied (`7b049f25`) and reverted. The
owner's reasons for keeping the decided sentence:

- the 2026-09-29 decision chose that sentence precisely because it covers cost "without singling
  out cost"; "your own run cost" singles it out again;
- the ticket's premise is that submissions are treated as verified by default, and a cost-specific
  "yours may differ" line re-introduces a softer form of the disclaimer it removes;
- the wording was the one put to Irina on 2026-09-25, so changing it belongs in that thread, not in
  this PR.

The note and `test_pareto_chart_disclaimer_is_folded_into_the_read_this_first_note` are back to
`176519ab` exactly. The only lasting change from this round is the Commits line above.
