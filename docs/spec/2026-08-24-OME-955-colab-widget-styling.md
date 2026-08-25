---
title: Colab notebook surface integration
ticket: OME-955
status: approved
date: 2026-08-24
---

# Colab notebook surface integration

## Outcome

ScreamingFace evaluation and report surfaces render with the active Colab light or dark theme,
remain readable in narrow outputs, and do not jump back to the left while live data updates. The
same HTML keeps the current JupyterLab and VS Code behavior.

## Host theme contract

SFDS v2 remains the only colour and typography source. The shared notebook style applies its exact
light and dark token sets using host signals in this precedence order:

1. `prefers-color-scheme` is the generic fallback;
2. Colab output iframes override it with zero-specificity `:where(html[theme="light"])` or
   `:where(html[theme="dark"])` host qualifiers;
3. the existing explicit JupyterLab and VS Code selectors remain authoritative in those hosts.

The Colab selector is not guessed: official `googlecolab/colabtools` output CSS uses
`html[theme=dark]` for its own widgets. Light and dark selectors are both explicit so a light Colab
notebook never inherits a dark browser or operating-system preference.

Shared host integration stays in `screamingface._ui.style`; individual evaluation and report
views consume it without duplicating theme logic.

## Evaluation layout contract

- The six-column Candidate table has a readable minimum width of 820 px. Narrow outputs scroll
  horizontally instead of compressing or overlapping columns.
- The table is rendered only through the live ipywidgets path; no unused static panel projection is
  maintained.
- A stable, focusable `widgets.HTML` node owns horizontal overflow and carries a descriptive
  tooltip. Its table retains a caption for table semantics. Header, table HTML, and terminal/error
  content may update independently, but the scroll-owning DOM node is never replaced, so its
  `scrollLeft` survives every update without JavaScript, polling, or smoothing.
- The evaluation header owns its inset. The table remains full-width; no global `.sf-ui` padding
  is added, so report and other notebook surfaces do not acquire a new indent.

## Boundaries

- No public SDK, Report, Event, Engine, Benchmark, or URL4 contract changes.
- No new dependency or custom Jupyter widget model.
- No legacy/alternate responsive table layout and no hidden columns.
- No inferred or placeholder progress information.
- Existing SFDS v2 light/dark values, font roles, square geometry, status semantics, and table
  recipe remain unchanged.
- Report content and information architecture do not change; it receives only the shared Colab
  theme correction.

## Accessibility and compatibility

The scroll container is the sole table-area focus target and retains the table's caption. Current
JupyterLab and VS Code theme selectors stay present, ordered later, and carry greater specificity
than the Colab qualifiers. The generic media-query fallback remains for other HTML notebook hosts.
