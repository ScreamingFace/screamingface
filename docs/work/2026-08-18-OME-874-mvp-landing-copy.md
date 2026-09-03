---
ticket: OME-874
stack: scoreboard
status: done
started: 2026-08-18
finished: 2026-08-19
---

# OME-874 — Replicate the leaderboard-mvp landing copy and UI on the portal

## Intent

Bring `apps/scoreboard/portal/index.html` to the brand mockup at
https://brand.screamingface.ai/leaderboard-mvp/ — copy and UI — rendering the parts we cannot yet
back as visible-but-inert rather than omitting them. Requested by Irina in `#scream-dev`
(2026-08-18 13:18) and confirmed in DM at 13:55.

This unit reverses a rule I wrote and the owner approved four days ago. `OME-839` adopted only the
mockup copy that was true, under the §4 invariant *"no portal copy may claim reproduction,
verification status, or cost until the owning ticket lands."* Irina has now explicitly chosen the
aspirational framing: *"it's not dishonest, it's just to present what purpose this leaderboard
serves long term."* That is the owner's call to make, and this ledger records that the reversal is
deliberate rather than an oversight — so a future reader does not "fix" it back.

## Decisions carried in from the owner (Slack 2026-08-18 13:35)

**D1 — the verified-SOTA framing is adopted despite no verification existing.** Owner call, quoted
above. `OME-414`/`OME-821` still own making it true.

**D2 — "Best reproducible" column renders the board's top score.** Owner: *"The top score on that
leaderboard."* The number is real; only the column label is forward-looking.

**D3 — the pool toggle ships inert.** Owner: *"we can make the 'all' greyed out."* Rendered so the
affordance is visible, disabled so it cannot assert a filter that does not exist. The functional
toggle stays `OME-771` (Blocked).

**D4 — the cost chart is out of scope.** Nothing emits a run cost; owner is resolving it separately.

## Open questions (raised on the issue, not blocking a first pass)

1. Which side of the toggle is greyed — defaulting to *Reproducible* renders an empty board.
   Working assumption: default **All**, grey out *Reproducible*.
2. The `REPRODUCIBLE` glossary definition names machinery that does not exist ("shared compute",
   "global cache" — and *global cache* already means our cost-caching layer to this team).
3. *"By default, the leaderboard only shows results we've reproduced ourselves"* — literally
   implemented, the default view is empty.

**D5 — no internal references in files the browser receives.** Raised by the owner mid-build. The
portal's HTML, JS and CSS are served unminified, so every comment in them is public via View Source.
My first pass put ticket ids and implementation caveats in `index.html` — including, directly beneath
the glossary, an `AIDEV-NOTE` reading *"none of this is implemented yet … do not read these
definitions as a description of current behaviour."* On a public board whose copy claims
reproducibility, that is the internal contradiction stated out loud, in the shipped artifact.

All six of my HTML comments were removed and my JS/CSS comments rewritten without ticket ids or
implementation caveats, keeping only the technical rationale a maintainer needs. The reasoning lives
here and in the spec instead — neither is shipped. Verified: `git diff` adds **0** `OME-` references
to anything under `portal/`.

The rationale that moved here rather than staying in the served files:

- **`benchmarks` → `index.html#benchmarks`**, not the mockup's bare `benchmark.html`, because
  `benchmark.js` requires an `id` parameter and renders an error state without one (`OME-839`).
- **The glossary is aspirational, not descriptive.** Nothing behind `Reproducible` exists:
  re-run verification is `OME-414`, the real verified signal `OME-821`, the pool toggle `OME-771`.
  Shipped verbatim at the owner's instruction to stay consistent with brand copy.
- **The footer names the host that resolves.** The mockup's cell reads
  *"leaderboard.screamingface.ai · MVP preview · mock data"*; that hostname has no DNS record
  (re-checked 2026-08-18 — `leaderboard.dev.screamingface.ai` and `scoreboard.screamingface.ai` do
  resolve, it does not) and this board serves real submissions, so two of its three claims are
  false. Owner chose `scoreboard.screamingface.ai`; GitHub keeps its rail link.
- **`leaderboard-logic.js` must load before `main.js`** — the catalogue's Best-reproducible cell
  calls `SFLeaderboardLogic.bestEntryScore`. Same order `benchmark.html` already uses.
- **The Dataset column** is not in the mockup, whose data is mock; ours links published JSONL that
  `data.html` serves, so dropping it would break a working path to a real artifact. Owner confirmed.

**D5 was under-enforced and review caught it.** My audit grepped `*.html`, `*.js` and `*.css` — the
file types I had been editing — and missed that I had *created* a markdown file inside the served
tree. `portal/assets/mark/PROVENANCE.md` shipped publicly (`200 text/markdown`) carrying the ticket
id on line 20 and a `.claude/skills/...` path on line 41. The PR body's claim of "zero internal
references in served files" was false when written; both the file and that claim are corrected.

Worth recording because two reviews disagreed and both were right: the security pass explicitly
cleared this file — *"no secrets, no internal hostnames, no credentials"* — which is true against a
security bar, where this is a non-finding. The code review judged it against D5, where it is a
violation. A file can be harmless and still break a stated rule.

The real fix is not the scrub but the guard: `test_served_markdown_carries_no_internal_references`
now fetches every `*.md` under `portal/` through the app and fails on `OME-`, `.claude/` or
`worktrees/`. Verified by reintroducing the original leak and watching it fail. D5 had been a
paragraph in this ledger with nothing enforcing it, which is exactly how it was missed.

Scope of that guard is deliberately markdown-only — see below.

**Pre-existing leak, NOT fixed here.** The same audit found **~42** `OME-` references already on
`main` in served portal files — `benchmark.js` 19, `main.js` 11, `leaderboard-logic.js` 9,
`portal.css` 8, `index.html` 4 (the last now 0 of mine). Those predate this branch and sit in files
this unit does not otherwise touch. Cleaning them, or stripping comments at build time, is its own
unit of work — flagged for a follow-up ticket rather than smuggled in here.

## Planned changes

- `apps/scoreboard/portal/index.html` — hero, glossary block, READ THIS FIRST box, benchmark table
  head, pool toggle
- `apps/scoreboard/portal/main.js` — `benchmarkRow` columns (Focus, Best reproducible), toggle render
- `apps/scoreboard/portal/portal.css` — glossary + toggle rules, tokens only
- `apps/scoreboard/src/scoreboard/scores/models/benchmark.py` + schema + a migration — optional
  `focus` field
- seed + `charts/scoreboard/values.yaml` — `focus` values
- `apps/scoreboard/tests/portal/*` + unit tests

**D6 — `benchmark.html` copy aligned too (owner, option A2).** A security review of the branch found
that `index.html`'s new claim ("only shows results we've reproduced ourselves") directly contradicted
`benchmark.html`'s standing disclaimer ("every score here is self-reported") one click away — and
that `models/score.py` carried a codified invariant naming *both* files: *"change the default and
that copy together, or the board lies."*

The mockup's own benchmark page has **no** note box, so matching it exactly would have meant deleting
the disclaimer. The owner chose instead to reword it consistently with the landing framing (A2), on
the grounds that verification "will be done soon". The `score.py` invariant was amended in the same
change: the copy rule is recorded as consciously suspended, while the rule that still holds — nothing
may filter or rank on `verified_by_screamingface`, because it certifies nothing — is restated. Copy
may promise; code may not pretend.

**D7 — the name cell keeps its `description` subtitle and mono id (owner, option B2).** The mockup
renders only the linked name, putting its short line in the Focus column. We now show both: the
`description` subtitle *and* Focus. Accepted redundancy, owner's call. Consequence to note: this
leaves `OME-768`'s open question ("what should the catalogue subtitle be?") still open, since
`description` continues to fill that slot.

**D8 — Focus ships with authored placeholder copy (owner, option C1).** draco → *"Research reports
with citations"*; ifeval → *"Instruction following"*; healthbench-worst30 → *"Clinical safety,
hardest cases"*. Not brand-approved — editable in `values.yaml` without a code change, subject to the
deployed-values caveat in Owner-verify below.

## Test plan

Written RED first, then made green:

- `test_seed.py` — `focus` persists through seeding; an absent `focus` is `None`.
- `test_leaderboard_routes.py` — `/v1/benchmarks` exposes `focus`, serialising `null` when unset
  rather than omitting the key.
- `tests/portal/leaderboard-logic.test.js` — six cases on `bestEntryScore`: empty/missing board,
  `null` vs a real `0`, highest-not-first, an all-negative board, **baselines never counting as our
  best**, and a malformed entry being skipped.
- `test_portal_static.py` — the hero mark is served as `image/png`, and the `.o-mark` `src` resolves
  to a path this app serves (behavioural, so it cannot be satisfied by a hotlink).
- `tests/smoke/` — opt-in drift alarms against the brand site: the three glossary definitions, the
  note copy, and the mark's upstream sha256. Excluded from CI by the new `smoke` marker, because an
  editor at another company must not be able to turn our build red.

## Acceptance

- Landing page matches the live mockup on every element in the spec's §4, both themes. ✓
- The hero mark renders from a vendored asset with no off-origin request. ✓
- `focus` round-trips model → schema → `/v1/benchmarks` → rendered cell; `—` when unset. ✓
- `Best reproducible` shows the top submission score; `—` when there are none. ✓
- No internal reference (ticket id, implementation caveat) in any file the browser receives. ✓
- `index.html` and `benchmark.html` no longer contradict each other. ✓
- Full gates green. ✓

## Outcome

- **Merged:** `bf0d95f8` — squash of 8 commits, PR #631, approved by @HupBaHa 2026-08-19 15:56.
  Merged under the new org: the repo transferred from `OpenMined/` to `ScreamingFace/` mid-flight
  and the PR, its number and its history carried across intact.
- **Actual files:** as planned, plus four not in the plan — `portal/benchmark.html` (the
  cross-page contradiction, D6), `models/score.py` (the copy invariant), `tests/smoke/` (the drift
  lane), and `routes/leaderboard.py` (the duplicate projection).
- **Gates:** ruff ✓ · ruff format ✓ · pyright ✓ · pytest --cov **324 passed, 2 skipped** ✓ ·
  portal JS **25 passed** ✓. Run with `--skip-append-only`, owner-approved under rule 5: exactly one
  prior assertion changed (the hero-copy string this unit replaces), rewritten structurally so the
  next copy edit will not break it again.
- **Rebased twice** — once onto the engine rename (`url4-cloud` → `screamingface-engine`), which
  merged cleanly but would otherwise have reintroduced stale paths into comments main had just
  fixed; once before merge. Verified at merge time that main's 10 newer commits touched no
  scoreboard file, so the `OME-852` semantic-conflict shape did not apply.

### Deviations

1. **The forward-looking copy was reverted in review.** D1–D3 are superseded: review (Dmitry,
   2026-08-19) showed the board never filters on the verified flag, so S1 and S3 described a default
   filter and a toggle that do not exist. Both deleted; S2 keeps the SOTA payoff with one word
   changed, `verified` → `submitted`. Net brand-copy deviation: one word, two deletions.
2. **A DRY fix outside the plan.** `routes/leaderboard.py` carried a second hand-written
   `BenchmarkSchema` projection; adding `focus` broke that copy and not the store's. One mapper now.
3. **D5 was under-enforced and review caught it** — `PROVENANCE.md` shipped publicly with a ticket
   id and a `.claude/` path. Fixed, and a guard test now fetches every `*.md` under `portal/` and
   fails on internal references.
4. **`tests/smoke/` and the `smoke` marker are new to this app.** Opt-in, excluded from CI, so an
   editor at another company cannot turn our build red.

### Owner-verify

- **`index.html` S1 and S3 were copy @Irina approved verbatim on 2026-08-18** and were removed
  because review showed they describe a filter and a toggle the board does not have. Flagged in the
  PR body; **still unconfirmed by her.**
- `Focus` values are placeholder copy, not brand-approved, and `values.yaml` does not propagate —
  deployed environments keep their own file, so the platform team must sync it.
- Visual check on the deployed board: light and dark, and the `.kv` glossary at the 620px breakpoint.

### Follow-ups left open

Ticket states re-checked 2026-09-03, on the way to closing this ledger out.

- `OME-885` — ~42 internal references still public in `benchmark.js` / `main.js` /
  `leaderboard-logic.js` / `portal.css`. **Still open**, moved to `Pick Immediately` on 2026-08-31.
- `OME-871` (Khoa's hero reword) is superseded by this unit. **Canceled by its owner 2026-08-24.**
- The OpenMined link sweep after the org transfer — **filed since**, as `OME-914` (docs, portal,
  public-docs) and `OME-945` (PyPI issue URLs, README), both In Progress. 115
  `github.com/OpenMined` references remain in the tree.
- Unauthenticated `POST /v1/scores` in the shipped production config — **still unfiled, and
  re-confirmed live on `main` at this date.** `charts/scoreboard/values.yaml` sets
  `authMode: disabled`, and `values-prod.yaml` enables an Ingress on `scoreboard.screamingface.ai`
  without overriding it — so the public host trusts client-supplied `submitted_by` free text.
  `OME-895` is adjacent but not this: it widens *who* may submit once identity is enforced, and
  does not turn identity on. Worth contrasting with the aigateway chart, which fails the Helm
  render outright on `cloudflare_headers` + `ingress.enabled` (`aigateway/templates/_helpers.tpl`);
  the scoreboard chart has no equivalent guard.

## Review finding (Dmitry, 2026-08-19): two mockup sentences describe machinery we do not have

Both points were correct and both are fixed with the smallest possible edit to the brand copy.

**Verified against the query, not the wording.** `_build_leaderboard_query` selects
`verified_by_screamingface` but never filters on it, and orders by `score DESC` — so an unverified
`0.99` genuinely outranks a verified `0.40`.

The mockup's note is three sentences. Two of them describe *mechanisms*, and no rewording makes a
missing mechanism present:

| | Mockup sentence | Outcome |
|---|---|---|
| S1 | *"By default, the leaderboard only shows results we've reproduced ourselves."* | **Deleted** — describes a default filter that does not exist |
| S2 | *"The top of each leaderboard is the best **verified** result: the current SOTA."* | **One word**: `verified` → `submitted`. Now true, and the SOTA payoff survives |
| S3 | *"Toggle on self-reported runs…"* | **Deleted** — names a control that exists nowhere; `OME-771` is Blocked |

Net deviation from the brand copy: **one word changed, two sentences removed, nothing invented.**

`benchmark.html` carries the **same two sentences as the landing page**. Two facts settled this:
the mockup has no note box on its benchmark page at all — it conveys the same meaning through a row
legend, a per-row Status column, a "SOTA (reproducible)" stat and the pool toggle, every one of
which needs the filter we lack — and Irina's instruction was scoped to *"the copy from the landing
page"* (2026-08-14, repeated 2026-08-18). So there is no brand copy for that page to deviate from;
its note was ours before this PR and stays ours.

Matching the landing wording also fixes a gap the single-sentence version left: `benchmark.html`
has **no glossary** (0 `kv defs` vs 1 on index), and deep links — the `Open →` column, spec pages,
anything shared — land there directly. Without the second sentence that page offered a reader no
context at all for what the numbers mean.

### What was tried and rejected first

An earlier pass rewrote both notes into honest-but-defensive prose ("we do not re-run submissions
yet", "nothing has been independently reproduced", "verified ranking arrives with re-run
verification"). Owner rejected it: it buried the ambition under a disclaimer and used the
"not yet / until that lands" construction throughout. The lesson recorded for next time — when copy
asserts something untrue, cut the assertion, do not add a confession.

**The aspiration never left the page.** The glossary is untouched and still carries Irina's
vocabulary verbatim: *"Reproducible — Ran on shared compute and stored on the global cache. Anyone
can re-run it and get the same score"* and *"Unverified — Self-reported… Not yet reproduced on the
global cache."* The note does not need to restate it.

### Owner action

S1 and S3 were verbatim mockup copy @Irina locked on 2026-08-18. Removing them is a deviation from
that instruction, made because review showed they describe behaviour the board does not have — her
call was a wording decision on what turned out to be an implementability question. The copy and the
pool filter (`OME-771` → `OME-821` → `OME-414`) are one change, not two. She should confirm before
merge.

**Status as of 2026-09-03.** #631 merged on 2026-08-19 without that confirmation, so
"she should confirm before merge" above records the intent at the time, not what happened.
The item is still open: `OME-874` carries two comments, both mine, and Irina has not replied
in the fifteen days since. S1 and S3 remain absent from the live landing page. Tracked in
Owner-verify above; the full mockup wording returns with `OME-771`.
