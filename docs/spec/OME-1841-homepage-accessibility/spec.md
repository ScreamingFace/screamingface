# OME-1841 — Homepage accessibility

Approved: owner requested implementation after inspecting the before/after preview.
Source: https://linear.app/openmined/issue/OME-1841

Use semantic text colours for score captions, fine print, loading/empty states and
chart labels. Use the existing 38px display, 20px lead/card title and mono chart
text tokens. Keep the existing responsive body size on mobile. Use a consistent
ink focus outline for homepage controls; make rail/navigation/theme and grant link
hit areas at least 44px. Preserve the layout, search, score filter and paging.

Add a skip link and main/footer landmarks to the homepage. After each page reveal,
announce the number displayed and total matches in the existing polite status region.
Filtering resets the display count as before.

All five portal pages select a valid stored light/dark choice before first paint,
otherwise the OS preference. Denied storage must still allow OS preference and the
existing toggle. Invalid stored values behave like no preference. Initializing the
page must not store a preference; only an explicit toggle does that.

The gold text token is owned by the brand source and excluded. No vendored brand
files, API, dependencies or analytics behavior change. This is not a full-page
WCAG certification; report measured elements and the known gold limitation.

Review clarification (2026-11-11): only homepage interactive controls receive the
new focus rule. Main remains a focusable skip destination without an outline.
The original outer layout wrapper contains sibling main/footer elements, keeping
the footer a page-level landmark and preserving its content width and spacing.
