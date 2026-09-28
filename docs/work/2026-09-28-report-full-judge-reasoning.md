---
ticket: OME-1340
stack: screamingface
status: done
started: 2026-09-28
finished: 2026-09-28
---

# report-full-judge-reasoning — the notebook report shows a judge's whole reasoning on demand

## Intent

The notebook report cuts a judge's reasoning under each criterion at 400 characters, and
nothing in the report holds the rest. On our own boards about one in five HealthBench
reasonings run past that (54 of 268 in a saved run, longest 812). Once `OME-1339` lands,
imported boards carry one ~2,800-character reasoning for a whole rubric, and the cut leaves
roughly the first item. Keep the 400-character preview, and add a collapsed "full reasoning"
section holding the whole escaped text with its line breaks.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/report_view.py` — `_check_html` renders the
  reasoning through a new helper: short text exactly as today; long text as today's preview
  plus a `<details>` block with the full text. New CSS rules for that block, using the
  report's existing tokens.
- `packages/screamingface/tests/test_full_judge_reasoning.py` — new.

## Test plan

- Long reasoning (505 characters) renders today's preview plus a collapsed full-text section
  whose text holds the tail the preview dropped.
- Boundary: exactly 400 characters renders no toggle; 401 renders one.
- Short reasoning renders byte-identical to today's row, no toggle.
- HTML placed after character 400 (so only the full-text block carries it) is escaped.
- The full text keeps the judge's line breaks (the characters survive, and the block's style
  preserves them).

## Acceptance

- Ticket acceptance: preview + collapsed escaped full text for long reasoning; short reasoning
  unchanged; tests pin both plus escaping; line breaks kept.
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_ui/report_view.py` (new `_reasoning_html` helper,
  `_REASONING_PREVIEW` constant, `.sf-check__full*` CSS) and the new test file; plus the
  `docs/tasks` mirror for OME-1340.
- **Commits:** see the PR (squash-merged).
- **Gates:** `run_gates.py screamingface` — ALL GATES GREEN (ruff, format, pyright, pytest
  with coverage ≥95, notebooks, build, distribution). 6 new tests; RED showed 5 failing for
  the missing block and the short-text guard passing before the change.
- **Deviations:** one addition beyond the ticket: when the full text is open, CSS
  (`:has`) hides the preview, because the full text repeats its first 400 characters.
  Browsers without `:has` show both, which is harmless. Verified visually in headless
  Chrome, closed and open. `report_view.py` was already over the 450-line guideline
  (934 lines) and is now 966; splitting it is out of scope.
