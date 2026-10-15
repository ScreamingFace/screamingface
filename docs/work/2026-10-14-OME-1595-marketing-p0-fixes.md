---
ticket: OME-1595
stack: scoreboard
status: done
started: 2026-10-14
finished: 2026-10-14
---

# OME-1595 — apply marketing's P0 copy/UI fixes to the leaderboard launch surfaces

## Intent

Lacey's marketing review of the leaderboard (landing, board and about pages), triaged by Irina into
P0 items plus trailing link fixes. Copy and small UI changes in `apps/scoreboard/portal` only: clearer
words ("submission", "all submissions"), the explainer above the table, the chart overlap, nav and
link targets, and a site-wide grant banner.

Owner decisions (2026-10-14): the banner is on every page and fixed (not dismissible); "spec" becomes
"submission" in visible text only (URLs, API fields and code names unchanged); both "Get started"
links go to `docs.screamingface.ai/sf-client/first-fusion`.

The "terminal window" item is the ABOUT note on the board page (`benchmark.html` `.note`), not
`about.html` (found from Lacey's screenshots in #scream-marketing, replies 14-16). Owner-approved copy
(2026-10-14): "The leaderboard's top row is the current state of the art. Every submission carries its
url4 expression, a complete recipe for the run. Copy it with the Copy button in the Run Locally column
to rerun, verify or build on any score here." with `url4` linked to `docs.screamingface.ai/learn/url4`.
The "remove portal" item is already done on main by #1308.

## Planned changes

- `portal/benchmark.html`: "Specs shown" → "Submissions shown"; the legend (Pareto explainer + gold
  row) moves above the table; chart key "dominated" → "all submissions"; nav "benchmarks" → "home".
- `portal/benchmark.html`: the ABOUT note gets the approved two-sentence copy and the url4 link.
- `portal/benchmark.js`: column header "Spec" → "Submission".
- `portal/pareto-chart.js`: short y-axis tick labels so they clear the "Score" title; point
  descriptions say "not on the Pareto frontier" instead of "dominated".
- `portal/spec.html`, `portal/spec.js`: visible "spec" words → "submission".
- `portal/about.html`: no em dash in the lead; `url4` links to `docs.screamingface.ai/learn/url4`;
  "Get started" → first-fusion; "Browse the board" → "Browse leaderboards"; "OpenMined" links to
  `openmined.org`; nav "benchmarks" → "home".
- `portal/index.html`, `portal/data.html`: nav "benchmarks" → "home"; landing "Get started" →
  first-fusion.
- Grant banner on every page (`index`, `benchmark`, `spec`, `about`, `data`) plus its CSS in
  `portal.css`.
- Tests: new portal tests only; no existing test changes.

## Test plan

- Python static test (`tests/unit/test_portal_static.py`-style, new file): every page carries the
  banner with the exact copy and link; no page's rail says "benchmarks"; both Get started links point
  to first-fusion; the explainer precedes the table in `benchmark.html`; the about lead has no em
  dash; `url4` and `OpenMined` are links with the agreed targets; visible "spec" words are gone from
  the listed strings.
- Node test (`tests/portal/`): the y-axis tick formatter returns at most 4 characters after "0.", and
  `describePoint` for a non-frontier priced point says "not on the Pareto frontier".
- Checks structured: parse the HTML with the standard library parser and compare element text and
  attributes, no substring searches over whole files (owner rule).

## Acceptance

- Every P0 and trailing item in OME-1595 except the terminal-window/citation item is visible on dev.
- Full scoreboard gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `apps/scoreboard/portal/{index,benchmark,spec,about,data}.html`, `benchmark.js`,
  `spec.js`, `pareto-chart.js`, `portal.css`; new tests `tests/unit/test_portal_launch_copy.py` (21
  cases, parsed with `html.parser`) and `tests/portal/pareto-chart-launch-copy.test.js` (4 cases);
  `tests/unit/test_portal_static.py` (two owner-approved edits, below); the new Node test is wired into
  `.github/workflows/scoreboard-tests.yml` and the scoreboard gate line of `.claude/sdlc.local.md`;
  `.claude/test-change-approvals/OME-1595.json` (byte-exact pin for the approved test edit).
- **Commits:** `fix(scoreboard): apply marketing's P0 copy and UI fixes to the launch pages` (one commit
  on `OME-1595-marketing-p0-fixes`).
- **Gates:** `run_gates.py scoreboard` ALL GREEN: append-only (approved OME-1595 transition), ruff check,
  ruff format, pyright, pytest 1170 passed / 9 skipped (coverage 90%), node 115/115.
- **Deviations:**
  - Prior test edits, owner-approved 2026-10-14 ("approved", option A):
    `test_rail_crumbs_show_only_where_you_are_below_home` now expects the spec.html crumb
    `submission`; `test_benchmark_board_carries_the_about_note_under_its_description` reads the
    `.note` text with `html.parser` (a module-level `_NoteText` helper, since an inline class broke
    ruff's C901 limit) and compares it with the new approved copy instead of a raw substring. Its
    order and retired-wording checks are unchanged. Pinned in `.claude/test-change-approvals/OME-1595.json`.
  - The theme toggle (`.rail .toggle`) is now `position: absolute` against the sticky rail instead of
    `fixed` to the viewport. With the banner above the rail, the fixed toggle sat inside the banner
    until the page scrolled. Measured in Chrome: centered in the rail at the top and after scrolling,
    on desktop and at 375px.
  - spec.html meta description reads "Run history for a screamingface benchmark submission, ..."
    ("Submission history for a ... submission" repeated the word).
  - The new copy strings inside `benchmark.js` and `spec.js` (column header, status messages) have no
    structured test: they are private literals in browser-only modules, so asserting them would need
    a substring search over the file or a DOM shim. They were checked by review.
  - Known edge: y-tick labels at 2 decimals can repeat on a board whose top score is under 0.04
    (quarters of the range round together). No current board is that low.

## Review round 1 (owner-approved 2026-10-14)

- **Changes:** on spec.html, each row is a "run": the stat label is "Runs", the table aria-label is "Run
  history", and spec.js says "latest run". The page eyebrow, title and crumb stay "submission". The
  y-axis now uses round ticks: `buildScoreTicks` picks the smallest 1/2/2.5/5 x 10^k step that needs
  at most 6 ticks, extends the score domain top to the next multiple, and labels each multiple with
  exactly the step's decimals. Points plot against the extended domain. This replaces round 0's
  2-decimal `formatScoreTick`, which is removed. The chart's fallback label is "Unnamed submission".
  Em dashes are removed from the about How it works and Contribute sentences, the spec.html note
  (which drops the retired desktop-app reference) and the board legend. The two
  `.grant-banner__link` colour rules that duplicated the base `a` rules are removed.
- **Tests:** `test_portal_launch_copy.py` gains 5 parsed-text cases (26 in total).
  `pareto-chart-launch-copy.test.js` is now 12 cases: the nice-tick domains 0.6869, 0.03, 1.0,
  all-negative, off-step negative floor, 0-100, a magnitude sweep and the single-value case, plus
  the model's extended domain, "Unnamed submission" and the 2 `describePoint` cases. The 2-decimal
  formatter cases went with the formatter. That file is new in this PR, so this is not a prior-test
  change. No prior test changed in this round.
- **Deviations:**
  - The spec.html note keeps its leading "History is newest-first." and only the sentences the
    review quoted are replaced.
  - Tick labels keep one decimal count across the axis ("0.0", "0.2", ...), not a bare "0", so the
    column of labels lines up.
  - A single-value board keeps one centred tick labelled with the exact value, unchanged from
    before; the pinned degenerate-domain test requires that.
  - Visual check: chart harness renders for a 0.69 board, a tiny 0.026 board and a negative
    -1.143..0.5 board. All labels clear the "Score" title.

## Review round 2 (Dmitry's CHANGES_REQUESTED; owner-approved 2026-10-15)

- **Finding:** `buildScoreTicks(0, 1e-101)` threw a RangeError from toFixed. `(-1e308, 1e308)`
  produced a null top and a "NaN" label. `(0, 1e-20)` gave 23-character labels. Because
  benchmark.js drew the chart before the table, a throw left a valid board on "Loading…" with the
  table hidden.
- **Changes:**
  - `pareto-chart.js`: the round-step search is bounded and returns null when it cannot fit. Its
    result is validated: finite domain and values, top >= high, positions in [0, 1], labels that
    are finite, unique and at most 6 characters. Any failure falls back to two endpoint ticks
    (floor and highest score) in short scientific form ("1.0e-101", "-1.0e308"). That form adds
    significant figures only until the two labels differ, and truncates toward zero where rounding
    would overflow ("1.7e308" for MAX_VALUE). The top is never below the highest score, on either
    path: the round path steps up once when nine-decimal rounding lands short. `normalize` halves
    every term when the range overflows, so points stay finite. A single-value board's mid-axis
    label is kept brief ("0.515").
  - `benchmark.js`: chart rendering runs last, after the table, summary and legend are visible. It
    is wrapped in try/catch: on any error the chart is cleared and hidden, and the error goes to
    `console.error`.
- **Tests:** `pareto-chart-launch-copy.test.js` gains 7 cases (19 in total). They cover the
  extreme-range sweep (0..1e-101, 0..1e-20, -1e308..1e308, 0..1e300, 0..MIN_VALUE, 0..MAX_VALUE,
  -MAX_VALUE..0, 0..123456789), the exact fallback labels, distinct labels for near-equal
  endpoints, top >= high after rounding, finite in-canvas points for extreme scores, the 6-character
  cap and the brief single-value label. New `benchmark-chart-isolation.test.js` (3 cases) loads the
  real leaderboard-logic.js, main.js and benchmark.js into a vm fake DOM with a throwing chart. It
  checks that the table head, rows, summary and legend render and are visible, that only the chart
  section is hidden and empty, and that the status ends as it does on a board whose chart renders.
  It is wired by name into scoreboard-tests.yml and the card's gate line. No prior test changed.
- **Deviations:**
  - The round-label cap is 6 characters, not the ~8 the owner suggested. A round label can sit
    level with the vertically centred "Score" title, and in the harness an 8-character label at
    that height reaches the title. The two fallback labels sit at the top and bottom and may run
    to 8 or 9 characters.
  - Two endpoints that agree to about 11 digits cannot have labels that are both unique and short.
    There, uniqueness wins and the label may exceed the length bound; this case is tested.
  - A single-value board's label at extreme magnitudes ("1.2e-101") still sits mid-axis.
