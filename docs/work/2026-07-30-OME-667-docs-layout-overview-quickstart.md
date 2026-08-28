---
ticket: OME-667
stack: repo
status: done
started: 2026-07-30
finished: 2026-08-05
---

# OME-667 — Update layout on the website + overview + quickstart

## Intent

First sub-issue of `OME-666` (Documentation for ScreamingFace Client V1). Every content page in
`public-docs/` is currently a 14-line component passing `DocLayout` a title and the literal text
`Stub page — replace with real content.` This unit delivers the three things in its title: the
sidebar **layout**, the **Overview** page, and the **Quickstart** page.

Branching follows the epic model: this branch is cut from
`callis/ome-666-documentation-for-screamingface-client-v1` and its PR targets that branch, not
`main`.

## Planned changes

- `public-docs/src/navigation/sf-client.ts` — Overview ungrouped, then a `Get Started` group with
  Quickstart and Installation
- `public-docs/src/composables/useDocNavigation.ts` — only if the empty-title section needs a type
  change
- `public-docs/src/components/layout/DocLayout.vue` — render no group heading when a section title
  is empty
- `public-docs/src/router/index.ts` — Quickstart route becomes `/sf-client/quickstart`
- `public-docs/src/pages/sf-client/Index.vue` — Overview page
- `public-docs/src/pages/sf-client/QuickstartPage.vue` — Quickstart page
- `public-docs/src/components/ui/` — one shared pending-figure affordance
- `public-docs/CLAUDE.md` — route and navigation tables

## Test plan

`public-docs` has no automated test setup and is not registered as a stack in
`.claude/sdlc.local.md`, so there is no RED→GREEN loop to run. Verification is the gate set the
project defines, plus manual render checks:

- `npm run type-check` · `npm run lint` · `npm run format` · `npm run build`
- Sidebar shows Overview ungrouped, then `Get Started`; active state correct
- Prev/next traverses Overview → Quickstart → Installation
- Quickstart resolves at `/sf-client/quickstart`
- Both pages in light and dark theme
- Both pages at mobile width with no horizontal scrolling of the page body

## Acceptance

- Sidebar shows Overview ungrouped, then `Get Started` with Quickstart and Installation; active
  state and prev/next work
- Quickstart resolves at `/sf-client/quickstart`
- Overview carries all five `OME-666` elements — what it is, headline gain figure, 6-line example,
  2-line how-it-works, links — and its example uses only shipped API
- Quickstart follows the six steps in order (`sf.config` → `sf.connect` → Models + Fusion →
  `sf.benchmarks.load("draco-lite@1")` → `benchmark.evaluate([candidates])` → read the
  `StudyReport`) and states the receipts: 1 case · 10 criteria · 1 judge pass · 7 solo + 9 Fusion
  candidates
- Unverified figures use one shared pending affordance
- Samples use `benchmark.evaluate(candidates)` → `StudyReport`
- Pages compose from existing `components/ui/` primitives; headings `h2` under `DocLayout`'s `h1`
- Both pages correct in light and dark theme, and at mobile width with no horizontal scrolling
- Gates green: type-check, lint, format, build

## Scope expansion (2026-07-31, owner-directed)

The unit grew beyond its acceptance criteria at the owner's request, mid-ticket:

1. **The notebook component kit was integrated.** The owner supplied a nine-component Vue SFC kit
   (`Provider Connections Component`) and asked for it to land in this ticket rather than a separate
   one. It is now `public-docs/src/components/nb/`.
2. **Two components were added to it.** `NbCell` (notebook cell chrome — the kit ships panels, which
   are notebook *output*, and they read as floating boxes without a cell around them) and
   `NbStateCarousel` (steps through component states with captions, replacing what the older docs did
   with screenshot carousels).
3. **The pages consume the kit.** Quickstart's steps are now notebook cells whose outputs are real
   panels, including a six-state walkthrough of the connection flow.
4. **The Quickstart prose was substantially expanded** after the owner judged the page too thin.

None of this was in the AC. Recorded here rather than silently absorbed.

## Decisions taken in-session

- **Result figures are placeholders — then superseded.** Placeholders were owner-approved on
  2026-07-30 because no notebook in the repo has committed outputs. On 2026-07-31 the owner ran
  `05_draco_quickstart.ipynb` and `00_quickstart.ipynb` against a live engine, and located the
  published full-benchmark chart. Both placeholders are gone: the pages now carry the owner's own
  `draco-lite@1` scores and the attributed `draco@1` figures (68.6% best fusion against 60.2% best
  single model).
- **Receipts are real.** Verified from source: `_CRITERIA_LIMIT = 10` and `passes=1` in
  `_benchmarks/draco_lite.py`; one pinned case; `05_draco_quickstart.ipynb` builds 16 candidates
  (7 solo + 9 Fusions).
- **`baseline`/`gain` are not `StudyReport` fields.** `OME-666` lists them there, but `report.py`
  puts them on `Report` (single-candidate), where `baseline` is the best member score and
  `gain == score - baseline`. Quickstart reads `.best`, per-candidate `score`, and `.url4`; the
  Overview headline figure is a `Report.gain`. Correction raised with the owner.
- **Epic-level `docs/spec` and `docs/plan` deferred.** Owner's call, 2026-07-30 — the epic design
  stays in the `OME-666` Linear description for now.

## Blockers / notes

- **Page ordering is with the owner and Irina.** `OME-666` promises Quickstart shows "the ensemble
  beat the best single model". DRACO-Lite does not demonstrate that: across two live runs a *solo*
  model won both times (`gpt-5.5`, then `claude-opus-4.8`) and five candidates hit the 100% ceiling —
  expected for one case with one judge pass. The claim holds on the full `draco@1` run, which is
  cited. Open question: does the page lead with the published result, or keep the runnable
  walkthrough first? The published figures cannot be shown as the Quickstart cells' output — that
  code calls `draco-lite@1` on a different lineup, so the numbers would be output the code cannot
  produce.
- Linear MCP was unavailable for most of the ticket; it was activated on 2026-07-31 and the issue's
  labels (`repo`, `autonomous`, `agentic`, `task`) were applied, having been empty.
- Landing label `repo`, milestone Week 3, priority Medium — inherited from `OME-666`.
- Nav entries, routes, and pages for User Guides and API Reference belong to the sibling sub-issues
  that own them.
- `public-docs/Provider Connections Component.pdf` is left untracked — design source, and it would
  ship inside the app directory. `docs/diagrams/` would be a better home if it should be kept.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** 22 changed, +2387 / −23. Far more than planned, because of the scope expansion
  above.
  - `public-docs/src/components/nb/` — 15 files: the nine-component kit plus `NbCell`,
    `NbStateCarousel`, `tokens.css`, `types.ts`, `index.ts`
  - `public-docs/src/components/layout/DocLayout.vue` — empty-title guard, group-label weight, and
    the `.not-prose` guards
  - `public-docs/src/navigation/sf-client.ts`, `public-docs/src/main.ts`
  - `public-docs/src/pages/sf-client/Index.vue`, `QuickstartPage.vue`
  - `public-docs/CLAUDE.md`, plus this ledger and the `docs/tasks` mirror
- **Commits:**
  - `6ffe4895` — feat(public-docs): sidebar layout plus Overview and Quickstart pages
  - `ca55dc2d` — fix(public-docs): distinguish sidebar group labels from their items
  - `826737d2` — docs(work): record the actual OME-667 commit shas in the ledger
  - `c2889c50` — feat(public-docs): notebook panel component kit
  - `3fc45f8f` — fix(public-docs): honour .not-prose across the doc layout prose styles
  - `87d1862f` — feat(public-docs): notebook cells, real run output and fuller Quickstart prose
  - `6ac85da8` — docs(public-docs): sharpen the Quickstart connection and report prose
  - `9a07bce5` — docs(work): bring the OME-667 ledger up to date
- **Merged:** [#459](https://github.com/ScreamingFace/screamingface/pull/459) into the epic branch
  `callis/ome-666-documentation-for-screamingface-client-v1` on 2026-08-05, not to `main` — the
  epic lands when `OME-666`'s remaining sub-issues are done. The shas above are the pre-rebase
  ones: the epic was later rebased onto `origin/main`, which replayed all eight with new shas and
  dropped the merge commit. `#459` is the stable pointer.
- **Gates:** `type-check` clean · `lint` clean · `format` clean on every file this unit touches ·
  `build` succeeds. During the ticket `lint` also reported 3 pre-existing
  `vue/multi-word-component-names` errors (`Collapsible.vue`, `sdk/Index.vue`,
  `sf-client/Index.vue`) — verified identical on a clean tree via `git stash`, so not introduced
  here, and renaming components was out of scope. They are gone as of the 2026-08-05 rebase onto
  `origin/main`: re-run on the rebased base with the bare commands CI uses (no `--fix`),
  `npx oxlint .` and `npx eslint .` both exit 0.
- **Deviations:**
  - **Route left unchanged.** Planned to rename `/sf-client/quickstartPage` →
    `/sf-client/quickstart`; owner chose to keep the existing path to keep the diff small. The
    matching AC line in `OME-667` was amended. Stale `NOTEBOOK_ROUTES` entries were therefore left
    alone too.
  - **No `PendingFigure` component, and no placeholders left.** A shared pending affordance was
    planned; design was owned separately at the time, so the figure went in as prose instead. It is
    now moot — the owner produced real numbers, so no placeholder survives.
  - **Two components added to the supplied kit.** `NbCell` and `NbStateCarousel` are not in the kit
    as delivered. `NbCell` exists because the kit's panels are notebook *output* and read as
    decoration without a cell around them; its geometry is lifted from the kit's own reference
    mockup rather than invented. `NbStateCarousel` slides rendered components rather than images,
    chosen over a screenshot carousel so the walkthrough follows the theme and cannot drift from the
    components it demonstrates.
  - **`.not-prose` was broken and had to be fixed.** Only `h2`, `pre` and `a` honoured it, so any
    component rendered in the content slot lost its typography and spacing. Fixed for the remaining
    eleven selectors. This is a shared-file change affecting every doc page — isolated in `3fc45f8f`
    for that reason.
  - **`--nb-*` tokens carry brand values, not only site-theme references.** Mapping them all onto the
    site theme (the owner's first instruction) turned the kit's gold accent into the site's primary
    purple and broke the visual tie to the SDK's own notebook cards. On the owner's revision, the
    structural tokens follow the site theme and the brand tokens carry their own light/dark pair.
  - **A dark prism theme on a light cell.** The shared `prism-theme.css` targets the site's dark code
    blocks; its near-white punctuation was invisible on the notebook cell's light fill, so dots and
    parentheses vanished from every sample. Syntax tokens were added for the cell.
  - **Hand-authored, not `NotebookViewer`.** `NOTEBOOK_ROUTES` maps `/sf-client` and the Quickstart
    route to notebooks, but it is stale scaffolding from the ported `syft-space-hub-docs`: it names
    `00_overview`, which exists nowhere in the SDK. The parent's per-page spec (outcome-first
    ordering, ≈ one screen, five named Overview elements) is not a notebook shape, and no `.ipynb`
    ships with the docs site.
  - **Repo-wide Prettier run reverted.** `npm run format` reformatted 20 files because Prettier had
    never been run here. Sixteen unrelated files were reverted so the diff stays scoped to this unit
    and does not collide with in-flight design work.
  - **Light/dark and mobile checks were the owner's.** Design ownership moved mid-ticket. The owner
    verified rendering in the browser and reported the defects that drove several of the fixes above.
  - **Overview's "User guides" link renders as plain text**, not a link — that section has no route
    until the sibling sub-issues create it, and a dead link is worse than a marked placeholder.
  - **Two factual errors were caught in review and corrected.** The page claimed candidates were
    "ranked by score" (neither `CandidateScores` nor `NbScoreList` sorts — rows render in declared
    order and only the maximum is marked) and that `report.url4` reproduces a run "exactly" (it pins
    the run's definition; model outputs vary, as the page's own variance note says). Both are
    corrected in `6ac85da8`.

## Follow-ups

- **Quickstart framing is still undecided.** `OME-666` promises the ensemble beats the best single
  model. The DRACO-Lite run this page walks through does not show that — a solo won both runs and
  five candidates hit the 100% ceiling on a 1-case study — so the page leads with the runnable
  walkthrough and carries the published `draco@1` result on the Overview instead. Whether the
  Quickstart should instead open with the published figure is an owner/Irina call, not a code
  change. Raised, not resolved, before merge.
- **The supplied design PDF still has no home** — see Blockers above. It stayed untracked through
  the merge.
- **`OME-668` onward now have a real base.** The epic carries the layout, the `nb/` kit and the
  `.not-prose` fix, and was rebased onto `origin/main` on 2026-08-05, so it also carries the
  `public-docs` major dependency bump and the new CI lane. Sibling sub-issues branch from the epic.
