---
ticket: OME-885
stack: scoreboard
status: done
started: 2026-09-08
finished: 2026-09-08
---

# OME-885 — Public portal source hygiene

## Intent

Stop exposing internal engineering commentary through the public Scoreboard portal while keeping
the portal dependency-free, its behavior unchanged, and its useful maintenance rationale recorded.

## Planned changes

- `apps/scoreboard/tests/unit/test_portal_static.py` — append the served-asset boundary guard.
- `apps/scoreboard/portal/**/*.{html,js,css,md,txt}` — remove or rewrite forbidden internal
  commentary without changing executable or rendered content.
- `docs/tasks/2026-08-18-OME-885-portal-source-hygiene.md` — repair the missing task mirror.
- `docs/spec/2026-09-08-OME-885-portal-source-hygiene.md` — record the selected source-cleaning
  contract.
- `docs/plan/2026-09-08-OME-885-portal-source-hygiene.md` — implementation sequence.
- This ledger — retain internal rationale removed from the served tree and record the outcome.

## Test plan

- RED: every file below `portal/` is reachable through its corresponding public path; each raw
  response rejects ticket identifiers, agent-only anchors, and internal repository paths.
- Boundary: binary font and image responses remain fetchable and are scanned without text decoding.
- Regression: the existing Markdown-only guard and all portal behavior tests remain unchanged and
  green.

## Acceptance

- The entire served tree is free of `OME-<number>`, agent-only note anchors, internal invariant
  anchors, agent paths, worktree paths, repository source paths, and Python source-file references.
- Removed internal reasoning is summarized below rather than discarded.
- No runtime dependency, portal build step, or user-visible behavior is introduced.
- Full Scoreboard gates pass.

## Preserved rationale

The public files now retain concise explanations of current behavior. The internal history removed
from them is preserved here:

- **Column and mark design (`benchmark.html`, `benchmark.js`, `portal.css`).** OME-769 originally
  reserved a dedicated mark slot so marked and unmarked names stay aligned. An earlier in-cell
  badge changed the width available to `.cell-wrap` and shifted only marked names. OME-923 later
  used the slot for the server-computed Pareto mark. Colour is not the sole carrier: the diamond has
  screen-reader text, while the gold row independently means highest score.
- **Why no reproduced-SOTA badge is wired (`benchmark.js`, `leaderboard-logic.js`).** The medal was
  descoped during OME-769 review because the leaderboard returns one score-selected row per spec.
  A higher unverified run can therefore hide the same spec's lower verified run, and client logic
  cannot identify the reproduced winner from the bounded result. OME-771 was intended to solve
  that at query time. The dormant, tested helpers only accept strict `true`; they must not be wired
  until the API exposes a trustworthy reproduction signal.
- **Why verification summaries remain absent (`benchmark.js`, `main.js`).** OME-820 established
  that `verified_by_screamingface` had no operational evidence behind it and changed the default
  without backfilling older rows. Counting or filtering the field would therefore partition rows
  partly by submission age while presenting the result as verification. OME-821 owns giving that
  field a real signal.
- **Cost semantics (`benchmark.js`, `leaderboard-logic.js`).** OME-770 chose a fixed-six-decimal
  string on the wire so SQLite and Postgres serialize money identically. Comparisons must convert
  explicitly, null means unknown rather than free, and the exact stored value remains available in
  the cell title when rounded display values coincide. The sub-cent formatter branches after
  rounding so one cent cannot render in two formats; that edge was found in review on 2026-08-31.
- **Benchmark-native scores (`benchmark.js`, `leaderboard-logic.js`, `main.js`).** OME-866 replaced
  the old binary-accuracy assumption. Scores render as plain numbers and bars normalize from
  `min(0, lowest visible score)` so negative HealthBench values never produce negative widths.
- **Summary and empty states (`benchmark.js`, `main.js`).** The frontier card is an optional third
  summary cell; removing `.stats--two` only when it becomes visible prevents a wide-screen wrap.
  Baseline-only boards still have a meaningful open share even though they have no current entry.
  The zero-entry path renders table structure because the earlier return left an empty benchmark
  with only a message and no columns. The landing-page count is best-per-spec, not raw submissions,
  because there is no aggregate submission-count endpoint. That also requires one leaderboard
  request per benchmark; it was accepted for the current handful and should be revisited if the
  catalog grows materially.
- **Chart module boundary (`benchmark.js`, `pareto-chart.js`).** Chart modelling and SVG rendering
  stay separate from page lifecycle wiring. Besides keeping those concerns isolated, this split was
  chosen to keep `benchmark.js` below the repository's focused-file limit.
- **Responsive and accessible layout (`benchmark.html`, `portal.css`).** Adding Cost pushed the
  table beyond its container at intermediate widths; horizontal scrolling preserves the columns,
  and the region must stay keyboard-focusable. The legend is necessary because the visual mark
  column has an empty heading. The sticky-rail override avoids content overlap; fragment scroll
  padding uses the same rail-height token; `.stats--two` stays inside its min-width query; and the
  legend sibling selector excludes hidden items to avoid a leading separator.
- **Vendored visual assets (`portal.css`, `assets/fonts/OFL.txt`).** The verified-badge mask must be
  cleared, not only hidden with `content: none`, because Chrome otherwise fetches the absent Remix
  icon and returns a 404 (PR #558 review). The font binaries came from the ScreamingFace Design
  System origin; its repository retains the detailed provenance and drift-check procedure. The
  Parastoo copyright line was taken from the archived `rastikerdar/parastoo-font` OFL license and
  matches the family name, but the exact binary served by the design system has not been verified
  against that upstream. The old public note named Bennett Farkas as the person who could confirm
  the original source and copyright holder; that follow-up remains an internal provenance concern.

## Outcome

- **Actual files:** the additive public-response guard in
  `apps/scoreboard/tests/unit/test_portal_static.py`; source-comment and provenance-text cleanup
  across `benchmark.html`, `benchmark.js`, `leaderboard-logic.js`, `main.js`, `pareto-chart.js`,
  `spec.js`, `portal.css`, `assets/fonts/OFL.txt`, and `assets/mark/PROVENANCE.md`; the repaired task
  mirror, spec, plan, and this ledger. No executable JavaScript, HTML structure, CSS declaration,
  route, dependency, or build step changed.
- **Self-review:** widened the guard from known text media types to raw response bytes so a generic
  MIME type cannot evade it; removed three remaining source-file paths; and corrected the font note
  to retain its concise attribution uncertainty rather than accidentally presenting it as verified.
- **Second self-review:** made the HTTP guard prove byte identity rather than status alone, then
  removed semantic leaks that had no forbidden token: a task-line instruction, an internal prototype
  and source filename, repository sizing rationale, a deferred scaling note, withdrawn-verification
  history, and a future icon-vendoring instruction.
- **Commits:** this commit — `chore(scoreboard): keep served portal source public-safe`.
- **Gates:** RED confirmed on `/assets/fonts/OFL.txt`; focused public-response guard 1 passed;
  `test_portal_static.py` 16 passed; full Scoreboard pytest 619 passed / 3 skipped / 3 deselected;
  portal Node suite 50 passed; `run_gates.py scoreboard --base origin/main` ALL GATES GREEN
  (append-only check, Ruff check, Ruff format, Pyright, pytest coverage ≥80%, portal Node suite).
- **Deviations:** the ticket's August baseline counted 42 ticket references in four served files;
  current `main` had 79 matching lines across eight served text files after subsequent portal work.
  The same source-cleaning design covered the larger set. The public font-license note also
  contained an internal attribution follow-up without a forbidden marker; its uncertainty is
  preserved above and its served text now carries only the external attribution reference.

## Rebase onto current `main`, 2026-09-23

The unit was finished and pushed on 2026-09-08 and **no PR was ever opened**. Fifteen days
later `main` had moved far enough that the branch no longer merged. Rebased onto `c6774ea1`.

### Conflicts, and how they were resolved

Two files, across two of the three commits — `portal/leaderboard-logic.js` and
`tests/unit/test_portal_static.py`. Both are places where `main` added content in the same
region this unit was editing.

* **`test_portal_static.py` — additive on both sides.** `main` added
  `test_pareto_chart_heading_and_label_name_the_pareto_frontier` (`OME-1146`) and
  `test_portal_index_filters_private_boards_through_the_shared_logic_module` (`OME-1147`); this
  unit added the served-bytes guard. **All three kept.** The second commit's rename of the guard
  (`…_text_asset…` → `…_asset…`, widening it from known text media types to raw bytes) was
  applied by hand on top of `main`'s version.

* **`leaderboard-logic.js` header — merged, not taken.** `main`'s text describes behaviour this
  unit predates (the index catalogue filter). Taking either side wholesale would have lost
  something. `main`'s substance was kept and only the internal markers stripped.

### The guard immediately earned its keep

With the rebase complete and before any further edit, the suite failed:

```
/leaderboard-logic.js publicly exposes internal ticket prefix, agent-only note,
                      internal invariant anchor
/main.js              publicly exposes internal ticket prefix
```

**Five new leaks that `main` introduced after this unit was written** — an `OME-1147` reference
and a `FEATURE:` anchor on the catalogue filter, an `INVARIANT:` block, an `AIDEV-NOTE:`
carrying internal product detail and an `OME-1112` roadmap pointer, and one more `OME-1147` in
`main.js`.

This is the third time the count has moved: the ticket's August baseline was 42 references in
four files, the build found 79 across eight, and the rebase found five more. **The number is not
converging on its own**, which is the argument for the guard rather than a one-off sweep.

All five removed. The load-bearing content was kept in every case — in particular the fail-open
reasoning on `listedBenchmarks` ("this is cosmetic, NOT an access control… the rule fails OPEN")
survives in full, with only the anchors and ticket numbers gone. Internal product specifics went
with them: which board is private, and where a future provenance field should live.

### Gates after the rebase

`run_gates.py scoreboard --base origin/main` — **ALL GATES GREEN**, and notably **without**
`--skip-append-only`. The append-only check passes against current `main`: `main`'s two new tests
are preserved intact and this unit only appends.

`test_portal_static.py` alone: **18 passed** (16 before, plus `main`'s two).

One formatting fix was needed after the manual conflict resolution — a missing blank line before
the guard, caught by `ruff format --check` and corrected, not suppressed.
