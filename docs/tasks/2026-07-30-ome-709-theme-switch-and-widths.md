---
id: OME-709
linear_url: https://linear.app/openmined/issue/OME-709/add-a-theme-switch-defaulting-to-dark-and-fix-the-consoles-ragged
status: in_review
type: task
priority: P3
labels: [autonomous, agentic]
created: 2026-07-30
closed:
---

# OME-709 — Add a theme switch defaulting to dark, and fix the console's ragged column widths

> **Mirror created late.** The work landed as `9f76cc71` before this file existed — the
> `docs/tasks/` mirror was missed at filing time and is reconstructed here from the Linear issue
> and the work ledger. Recorded rather than backdated silently.

> **Missing landing label.** Like `OME-708`, this carries no `app › aigateway-ui` leaf because the
> label does not exist and agents cannot create labels. Owner action outstanding.

Two defects in the `OME-708` console, both found by an operator looking at it.

## 1 · No way to change the theme, and it never follows the OS

The vendored OMDS tokens key dark mode **only** off `[data-theme="dark"]` on `<html>` — there is no
`prefers-color-scheme` rule anywhere in `src/brand/tokens/`. Nothing set that attribute, so the
console was hard-stuck in light: not merely "no toggle", but not honouring the OS setting either.
Upstream's `ThemeToggle.astro` was not ported — `OME-707` vendored only the tokens, the components
being Astro.

Wanted: a real switch, **defaulting to dark**.

The part that is easy to get wrong is the flash. A React effect runs *after* first paint, so the
page renders light and then flips on every navigation. The theme must reach `<html>` from a
parser-blocking script in `<head>`.

## 2 · Ragged column widths

One page stacked **five** different max-widths (1100 / 720 / ~606 / ~530 / 420), so every block
began at the same left edge and ended somewhere different.

## Owner decision

A named measure scale was proposed. **Owner overrode it: remove `max-width` entirely — "it's
ugly".** The layout is full-bleed with padding. The cost is recorded in the ledger: on a very wide
display, prose lines get long. That is the owner's call and it is made.

## Outcome

Landed in `9f76cc71`. 181 tests. Four fixes: the theme switch, full-bleed layout, search-button
alignment, and the "New tenant" dialog. Six deviations are documented in the ledger — the most
significant being that the pre-paint script is a **served file**, not inline, so a future CSP needs
no `'unsafe-inline'`.

Full detail: `docs/work/2026-07-30-OME-709-theme-switch-and-full-width.md`.
