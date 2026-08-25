---
ticket: OME-955
stack: screamingface
status: in_progress
started: 2026-08-24
finished:
---

# OME-955 — Clean up Colab widget styling

## Intent

Make shared ScreamingFace notebook styling respect Colab's explicit theme and make the live
evaluation table usable at narrow output widths without losing horizontal position during updates.

## Planned changes

- Add the missing OME-955 task, approved spec, plan, and ledger artifacts.
- Update `packages/screamingface/src/screamingface/_ui/style.py` with explicit Colab host selectors.
- Update the evaluation HTML view with header-owned spacing and a readable table floor, then move
  the live ipywidgets host into a focused module with a stable scroll container.
- Add deterministic regressions in the focused shared-style, evaluation, and report test surfaces.

## Test plan

- RED: light and dark Colab selectors override the generic media preference using the unchanged
  SFDS token sets; JupyterLab and VS Code selectors remain.
- RED: a narrow Candidate table exposes labelled horizontal overflow, an 820 px floor, and no
  overlapping/compressed column contract.
- RED: the live view preserves the identity of its scroll-owning widget across all render phases.
- GREEN: existing evaluation content, progress, accessibility, report, JupyterLab, and VS Code
  tests remain unchanged unless the approved narrow-overflow contract directly replaces them.

## Acceptance

- Every observable OME-955 acceptance criterion is pinned by deterministic tests.
- Light and dark renders use exact SFDS v2 tokens and no raw new visual values.
- Focused tests and the complete ScreamingFace quality gates pass.
- Work is committed and pushed without opening a PR.

## Review follow-up

- Remove the unused static `evaluation_panel_html` composition and make tests exercise the same
  fragments consumed by the live widget.
- Make the stable `widgets.HTML` table node the sole focusable horizontal-scroll owner; remove the
  inert nested region/focus target while retaining the table caption and a descriptive tooltip.
- Give the live widget root a descriptive tooltip and lower Colab selector specificity so the
  existing JupyterLab and VS Code host selectors remain authoritative.
- Pin the actual runtime composition, focus ownership, and host precedence with regressions before
  updating the draft PR.

## Colab visual follow-up

- Keep Status to lifecycle plus elapsed time so long grading coverage cannot overflow into Cases.
- Render incomplete grading coverage as a muted second line beneath the Score it qualifies.
- Keep fully graded Score cells single-line and preserve the existing Cases execution meaning.
- Raise the numeric alignment selector above the table-cell base rule so Cases, Score, Cost, and
  Cache Hit share a right edge in the rendered Colab table.

## Theme ownership follow-up

- Generate the browser, Colab, JupyterLab, and VS Code theme matrix from one shared helper while
  retaining each surface's existing light/dark SFDS values.
- Apply the shared matrix to the independent Leaderboard and notice token blocks and to the
  connection panel's provider-logo variants.
- Pin every independent notebook theme selector with one parameterized contract test.

## Outcome

- **Actual files:** shared notebook theme tokens and host-rule generator, the runtime evaluation
  fragment projection, a
  focused live ipywidgets host, its internal observer import, focused UI/report regressions, and the
  OME-955 SDLC artifacts. Review follow-up removed the dead static panel composition and made the
  stable table HTML widget the only scroll/focus owner. Colab visual follow-up moved result
  qualifiers beneath Score so Status remains lifecycle plus elapsed time without column overlap.
  Theme follow-up brought Leaderboards, notices, and connection provider logos under the same host
  matrix without changing their visual tokens.
- **Commits:** `fix(screamingface): clean up Colab widget styling`;
  `fix(screamingface): align Colab widget runtime semantics`;
  `fix(screamingface): keep grading coverage with Score`;
  `fix(screamingface): align numeric evaluation columns`;
  `fix(screamingface): unify notebook theme detection`
- **Gates:** 101 focused Leaderboard/notice/connection/theme-contract tests pass; complete
  `screamingface` gate passes Ruff,
  formatting, Pyright, the full pytest suite at the 95% coverage floor, notebook checks, package
  build, and distribution validation.
- **Deviations:** the append-only assertion gate was skipped because this owner-approved ticket
  intentionally replaces the inherited no-horizontal-overflow contract and the review explicitly
  corrected tests that targeted a dead static path. The in-app browser had no connected runtime, so
  deterministic CSS/DOM and real-ipywidgets verification replaced screenshot inspection; owner
  Colab visual verification remains before PR readiness.
