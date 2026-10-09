# OME-1425 spec — "Closed weights" meets WCAG AA contrast

## Problem

The leaderboard's Backends cell shows "Open weights" or "Closed weights" per row (OME-1386). Closed uses the SFDS `.status` off-state from the vendored `style.css`: `.status:not(.on) { color: color-mix(in oklch, var(--ink-2) 64%, transparent) }`. In the light theme that text is 2.77:1 on `--bg` and 2.69:1 on the row-hover `--surface`. That fails AA (4.5:1) and even the large-text floor (3:1). The word is the data the column exists to show.

The open rule, `.status.status--open`, only wins over `.status:not(.on)` because `portal.css` loads after `style.css`. Both selectors have specificity (0,2,0).

## Decision (owner triage, 2026-09-30)

Fix in the portal, not in SFDS. The vendored `style.css` stays untouched.

- Closed rows get their own modifier, `status--closed`. Its text is full `--ink-2`: 5.99:1 on light `--bg`, 5.63:1 on light `--surface`. Dark already passes. The square stays `--ink-3`, so open and closed still differ by square fill and text tone.
- Both modifier rules carry `:not(.on)`, raising them to (0,3,0). They then win over the base off-state by specificity, not load order.
- No success green; green means verified in SFDS.

## Acceptance

- "Closed weights" is at least 4.5:1 against `--bg` and `--surface` in light and dark.
- Open and closed stay visually distinct.
- A test pins the tone and the specificity, so a stylesheet reorder cannot flip it.

## Out of scope

The SFDS `.status` recipe itself, and the unknown-dash (`.faint`) tone, which already passes.
