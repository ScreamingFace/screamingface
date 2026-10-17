---
ticket: OME-1638
stack: scoreboard
status: in_progress
started: 2026-10-15
finished:
---

# scoreboard-og-meta — link-preview image and tags on the public leaderboard

## Intent

Shared leaderboard links (and screamingface.ai, which redirects to the board) unfurl in Slack,
X and LinkedIn with a grey placeholder: the portal pages carry a title and description but no
Open Graph or Twitter card tags. This adds them, with the brand guide's link card as the image.

## Planned changes

- `apps/scoreboard/portal/{index,about,benchmark,spec,data}.html`: `og:*` and `twitter:*` tags
  with absolute URLs, reusing each page's existing title and description.
- `apps/scoreboard/portal/assets/social/sf-og-1200x630.png` + `PROVENANCE.md`: the brand link
  card, vendored unchanged so previews never depend on another host.
- `apps/scoreboard/tests/unit/test_portal_static.py`: every page names a large-image card whose
  image path this app serves as a PNG.

## Test plan

- New test: each of the five pages has `twitter:card=summary_large_image` and an absolute
  `og:image` whose path returns 200 `image/png` from the app.

## Acceptance

- Sharing the board, the about page or screamingface.ai shows the card image in Slack and X.
- `run_gates.py scoreboard` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see PR.
- **Gates:** `run_gates.py scoreboard` → ALL GATES GREEN (ruff, format, pyright, pytest with
  coverage, node portal tests).
- **Deviations:** none.
