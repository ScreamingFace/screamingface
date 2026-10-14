---
ticket: OME-1603
stack: screamingface
status: done
started: 2026-10-14
finished: 2026-10-14
---

# fix-dark-mode-widget-ink — widget panels go black-on-black in VS Code dark mode

## Intent

In a VS Code notebook with a dark theme, `sf.connect()` renders the Connections panel with its
dark background but black text: the title, provider names and every other line without its own
colour vanish. The panel root sets the SFDS ink, but ipywidgets paints every nested widget
`color:var(--jp-widgets-color)`, which resolves to `black` where the host defines no JupyterLab
theme (VS Code). VS Code also paints every widget output frame `#fff !important`, so a white
band surrounds the dark panel. The same cause hits every ipywidgets panel rooted on `.sf-ui`
(Connections, catalogue, report browser).

## Planned changes

- `packages/screamingface/src/screamingface/_ui/style.py` — in the shared `STYLE`: nested
  widget boxes and HTML widgets inside `.sf-ui` inherit the panel ink; a VS Code widget frame
  that holds an `.sf-ui` panel drops its white background.
- `packages/screamingface/tests/test_notebook_theme_contract.py` — pin both rules.

## Test plan

- Contract tests: `STYLE` carries the inherit rule and the scoped frame rule.
- Headless Chrome repro (scratch, not committed): real panel markup + the installed host rules
  (ipywidgets 8.1.9 `.jupyter-widgets` colour, VS Code Jupyter `.cell-output-ipywidget-background`)
  under `body.vscode-dark`; title/provider computed colour must be the dark-theme ink, frame
  transparent.

## Acceptance

- In the repro, title + provider name compute to `rgb(224, 229, 235)` (`--sf-ink` dark), was `rgb(0, 0, 0)`.
- Frame background computes transparent, was `rgb(255, 255, 255)`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`style.py`, `test_notebook_theme_contract.py`) plus this ledger and the `docs/tasks` mirror.
- **Commits:** see the PR for OME-1603 (squash-merged as one commit).
- **Gates:** RED first: the 2 new contract tests failed before the fix. After: `test_notebook_theme_contract.py`, `test_panels_opt_out_of_maths.py`, `test_live_candidate_progress.py` plus the connection/style/theme/panel/catalog/report_browser tests in `tests/unit` gave 45 passed (with `--extra notebook`). ruff check, ruff format and pyright clean on the touched files. Headless Chrome repro: title/provider `rgb(0,0,0)` → `rgb(224,229,235)`, frame `#fff` → transparent.
- **Deviations:** none. Owner verify: re-run `sf.connect()` in VS Code's dark theme; only the repro was rendered, not VS Code itself.
