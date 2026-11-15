# OME-1841 implementation plan

1. Add failing behavioral tests for theme initialization and paging announcements,
   and structural HTML checks for landmarks and controls.
2. Add a tiny shared synchronous head script for OS/stored theme selection, leaving
   the vendored toggle alone. Wire it on every portal HTML entry point.
3. Apply the approved CSS changes in portal.css, update homepage semantics and
   refresh the live count in the normal page-reveal handler.
4. Run the scoreboard gates. Preview actual files with representative public data
   on desktop/mobile in both themes, inspect screenshots and record contrast/hit
   areas. Review the final diff and open a draft PR with evidence.

## Approved review fixes — 2026-11-11

Address Khoa's three comments: suppress the main-container focus outline while
retaining skip navigation; share the original wrapper between main and footer to
restore spacing; limit the new interactive focus rule to an explicit homepage
body class. Browser regression checks cover all three and both viewport/theme pairs.
