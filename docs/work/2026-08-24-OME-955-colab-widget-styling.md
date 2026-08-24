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

## Outcome

- **Actual files:** shared notebook theme tokens, evaluation static HTML, a focused live ipywidgets
  host, its internal observer import, focused UI/report regressions, and the OME-955 SDLC artifacts.
- **Commits:** `fix(screamingface): clean up Colab widget styling`
- **Gates:** 69 focused evaluation/report tests pass; complete `screamingface` gate passes Ruff,
  formatting, Pyright, the full pytest suite at the 95% coverage floor, notebook checks, package
  build, and distribution validation.
- **Deviations:** the append-only assertion gate was skipped because this owner-approved ticket
  intentionally replaces the inherited no-horizontal-overflow contract. The in-app browser had no
  connected runtime, so deterministic CSS/DOM and real-ipywidgets verification replaced screenshot
  inspection; owner Colab visual verification remains before PR readiness.
