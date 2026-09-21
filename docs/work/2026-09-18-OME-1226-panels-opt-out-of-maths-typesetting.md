---
ticket: OME-1226
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-09-18
finished: 2026-09-18
---

# OME-1226 — Panels opt out of the notebook's maths typesetter

## Intent

Our notebook panels are transcripts: they exist so a researcher can read exactly what a
candidate was asked and exactly what it replied. A benchmark prompt that mentions money
carries literal `$` characters, and the notebook's maths typesetter (MathJax) runs a
*separate pass over the already-rendered DOM*, pairs those dollars up, and re-typesets the
text between them as inline maths — italic, with every space deleted. GSM8K's instruction
text alone contains three (`ANSWER: $ANSWER (without quotes)`, `$2 per fresh duck egg`), so
the flagship `12_imported_benchmarks.ipynb` currently shows a corrupted copy of its own
prompt. HTML escaping cannot stop this: `$` is not an HTML-special character, so it reaches
the DOM untouched and the damage happens one layer later, in the browser.

MathJax honours an opt-out class on any element and skips that element's whole subtree. This
unit marks every panel root with it. Presentation only — no stored artifact, protocol
payload, or engine behaviour changes; the panels keep emitting the same characters and only
the browser's post-processing changes.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/style.py` — add the shared opt-out class
  names as the single source of truth (`NO_MATH_CLASSES` tuple for widget roots that call
  `add_class`, `NO_MATH` joined string for HTML `class='…'` attributes), with the INVARIANT
  anchor explaining why two names are needed.
- HTML-string roots gain `{NO_MATH}`:
  - `_ui/report_view.py:192` (`sf-ui sf-report`)
  - `_ui/score_view.py:52` (`sf-ui sf-report`)
  - `_ui/connection_view.py:176` (`sf-ui sf-connections`)
  - `_ui/cards.py:46,63,78,166,190,210` (`sf-ui sf-card`) and `:222` (`sf-ui sf-catalog`)
  - `_ui/leaderboard_view.py:89` (`sf-lb sf-lb-list`) and `:113` (`sf-lb sf-lb-board`) —
    these do NOT carry `sf-ui` and are easy to miss
  - `_ui/notice_view.py:50` (`sf-notice sf-notice--<severity>`) — likewise no `sf-ui`
- Widget roots gain the classes via `add_class`:
  - `_ui/evaluation_widget.py:58` (the VBox wrapping every evaluation fragment)
  - `_ui/catalog.py:93`
  - `_ui/connection_view.py:208` (the class tuple)
- `packages/screamingface/tests/test_report_panel.py` — new pinning test.
- `packages/screamingface/tests/test_live_candidate_progress.py:997` — the exact-list
  `_dom_classes` assertion is updated to the new intended set (kept exact, not weakened to a
  membership check: the exactness is what makes an accidental class change loud).

## Test plan

- RED: render a report whose prompt text contains a literal `$` and assert the root element
  carries **both** `mathjax_ignore` and `tex2jax_ignore`. Names the invariant it defends —
  *panels are transcripts, so the notebook must never typeset their contents as maths*.
- RED: a sweep over every panel renderer (report, score, connections, each card kind,
  catalog, both leaderboard views, both notice severities) asserting both class names sit on
  the emitted root — this is what catches the two non-`sf-ui` roots regressing.
- RED: the widget roots (`evaluation_widget`, `catalog`, `connection_view`) carry both class
  names in their `_dom_classes`.
- Boundary: `sf-ui` stays the FIRST class on the HTML roots — two existing tests slice the
  rendered document with `html.index("<div class='sf-ui")`, so class order is load-bearing.
- Regression: prompts with no dollar sign render byte-identically apart from the root's
  class attribute (the existing panel suites cover this and must stay green, unmodified).

## Acceptance

1. Every root listed under *Planned changes* carries both `mathjax_ignore` and
   `tex2jax_ignore`.
2. A pinning test fails loudly if a future refactor drops either class.
3. `test_live_candidate_progress.py:997` still asserts an exact class list.
4. The whole `screamingface` package suite is green; no stored artifact, protocol payload, or
   engine behaviour changes.
5. Owner visual check: re-run `12_imported_benchmarks.ipynb` against `inspect-gsm8k` and
   confirm the prompt reads `ANSWER: $ANSWER` and `$2 per fresh duck egg` — upright,
   correctly spaced, no italics.

Known and intended consequence: anything genuinely written as maths inside a *model's answer*
also stops being typeset. For a transcript surface that is the correct behaviour, not a
regression.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus two that the plan did not name. `_ui/style.py` holds the
  single source of truth — `NO_MATH_CLASSES` (tuple, for the three ipywidgets roots that call
  `add_class` once per name) and `NO_MATH` (the same two names joined, for an HTML
  `class='…'` attribute). Every root listed in Planned changes now appends it. The pinning
  tests landed in a new `tests/test_panels_opt_out_of_maths.py` (13 rendered roots plus the
  three widget roots) and one report-specific test in `tests/test_report_panel.py`.
- **Commits:** f10e4c10 — fix(py-screamingface): stop the notebook typesetting panel text as maths (PR #986).
- **Gates:** `run_gates.py screamingface --skip-append-only` — ALL GATES GREEN (ruff check ·
  ruff format · pyright · pytest with coverage ≥95 · notebook determinism · uv build ·
  distribution check). Full suite: 1617 passed, 25 skipped.
- **Deviations:**
  1. **Append-only gate skipped, with owner approval.** Acceptance #4 requires editing a
     prior test (`test_live_candidate_progress.py:997`), which the gate refuses by design.
     The assertion stays an EXACT list — `["sf-ui", "sf-eval", "mathjax_ignore",
     "tex2jax_ignore"]` — not weakened to a membership check, because the exactness is what
     makes an accidental class change on that root loud. Approved in session before running.
  2. **The pinning tests live in their own module**, not appended to `test_report_panel.py`
     alone. The invariant spans thirteen roots across eight modules; keeping it in one file
     named after the invariant makes it greppable and gives a new panel one obvious place to
     register. The report-with-a-dollar-sign test asked for by acceptance #3 is still in
     `test_report_panel.py`, beside the other report-panel contracts.
  3. **Two extra assertions beyond the ticket.** A `sf-ui`-stays-first test, because two
     existing suites slice a rendered document with `html.index("<div class='sf-ui")` — the
     leading class is load-bearing markup, so the new classes are appended, never prepended.
     And a check that the tuple and the joined string stay in step.
  4. **`uv sync --extra notebook` is required** to run this package's suite at all (three of
     the new tests drive real ipywidgets roots, and `tests/test_connection_panel.py` already
     imported `ipywidgets` at module scope). CI already does this; a fresh worktree does not.
- **Known and intended:** anything genuinely written as maths inside a *model's answer* also
  stops being typeset. For a transcript surface that is correct behaviour, not a regression.
- **Owner-verify:** re-run `12_imported_benchmarks.ipynb` against `inspect-gsm8k` and confirm
  the prompt reads `ANSWER: $ANSWER` and `$2 per fresh duck egg` — upright, correctly spaced,
  no italics. This is the one acceptance criterion a test cannot cover: the tests pin the
  classes on the root, but only a browser proves MathJax honours them.
