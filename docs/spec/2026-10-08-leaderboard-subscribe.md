# leaderboard-subscribe — email updates for ScreamingFace and for each leaderboard

## Problem

The Q4 objective is views and subscriptions, and the leaderboard has no way to leave an email.
Marketing wants two lists: people who want ScreamingFace news, and people who want updates on one
specific board — and to know which boards and which page placements bring subscribers in.

## Rule

- **Per board:** on `benchmark.html`, a gold "Follow this board" button under the title opens an
  inline form: email + "Follow this board", and a tick-box "Also send me ScreamingFace news".
- **Site-wide:** every page carries a "ScreamingFace updates" form above the footer. The landing
  hero links to it ("Subscribe for updates", next to a gold "Get started").
- **Where it goes:** the browser posts to HubSpot's public Forms API (portal 6487402, form
  "😱 leaderboard.screamingface.ai → Subscribe for updates"). Each submission records the email,
  `sf_subscribe_board` (board id or `all`), `sf_subscribe_placement` (`board-header` | `site-band`),
  `sf_subscribe_all`, the URL's UTM tags, the page URL, the HubSpot visitor cookie, and consent to
  the subscription types "😱 Leaderboard Alerts" (board) and/or "😱 ScreamingFace Updates".
- **States:** invalid email, sending, success, failure; a returning visitor who already subscribed
  sees the confirmation instead of the form (browser storage, best-effort). A hidden honeypot field
  drops bot submissions. Plausible receives a `Subscribe` event with `scope` and `placement`.
- **Design:** SFDS marketing register — gold primary buttons, the field's border turns the same
  gold on focus, square corners, tokens only, light and dark.

## Not changed

- No API or backend change; no secret is added (the HubSpot form ids are public by design).
- Sending is out of scope: nothing emails subscribers yet. What counts as a board being "topped",
  the sender, and the cadence are open questions for marketing.

## Tests

- Portal (Node): payload shape for a board and a site-wide submission, consent per scope and the
  tick-box, UTM pass-through, visitor cookie, email validation, copy.
- Static (pytest, new file): every page carries the site-wide mount point and loads
  `subscribe.js`; the script is served. (Additive — no existing test is modified.)
