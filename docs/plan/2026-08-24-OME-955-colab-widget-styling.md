---
title: Implement Colab notebook surface integration
ticket: OME-955
status: approved
date: 2026-08-24
spec: ../spec/2026-08-24-OME-955-colab-widget-styling.md
---

# Implement Colab notebook surface integration

1. Add failing shared-style tests that pin explicit Colab light/dark selectors, exact SFDS token
   reuse, and preservation of the existing JupyterLab and VS Code selectors.
2. Replace the inherited no-overflow assertions with approved narrow-table contracts: 820 px
   minimum width, labelled keyboard-reachable overflow, full-width table, and header-only inset.
3. Add a failing live-view regression that pins a stable, focusable ipywidgets scroll container
   whose identity survives `begin`, event, timer, reconcile, and abort renders.
4. Update the shared style with Colab host selectors, then split the live evaluation view into
   independently updated header, stable table-scroll container, and terminal content while keeping
   `evaluation_panel_html` as the canonical static representation.
5. Run focused style/evaluation/report tests, inspect both light and dark Colab-sized renders, and
   run the complete ScreamingFace gate suite.
6. Review `origin/main...HEAD` for SFDS and compatibility regressions, fill the ledger outcome,
   commit, and push the branch. Do not open a PR until the owner requests it.
7. Review follow-up: delete the unused static panel composition, route runtime and tests through one
   fragment projection, make the stable table HTML node the sole scroll/focus owner, correct host
   selector specificity, rerun all gates, and update the draft PR.
