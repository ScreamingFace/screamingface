---
id: OME-1603
linear_url: https://linear.app/openmined/issue/OME-1603/make-notebook-panels-readable-in-vs-codes-dark-theme
status: done
type: bug
priority: medium
labels: [bug, client-sf, agentic, autonomous]
parent: none (bug exception)
created: 2026-10-14
closed: 2026-10-14
---

# Make notebook panels readable in VS Code's dark theme

In VS Code's dark theme, ipywidgets reset every nested widget's text to a host colour VS Code leaves
black, so panel titles and provider names went black-on-black; VS Code also framed each widget
output in white. Two rules in the shared panel style hand the text back to the panel's ink and drop
the frame around outputs that hold a panel.

- 2026-10-14: filed at PR-open and done in the same PR. Owner verify: re-run `sf.connect()` in VS Code dark.
