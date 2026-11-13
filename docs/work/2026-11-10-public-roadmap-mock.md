---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: public-docs (Vue 3 + Tailwind; no test suite — gates are type-check/lint/build)
status: in_progress
started: 2026-11-10
finished:
---

# public-roadmap-mock — Public roadmap page (mock) in public-docs

## Intent

A single public surface that (1) shows what's shipping and roughly when, and (2) lets users tell us
what to build. Lives as a real `/roadmap` page in the public-docs Vue app (reserved route + the
commented-out navbar link already exist). Seeded with ~20 real `OME-N` items curated into user-facing
titles; votes/comments are localStorage (mock, no backend); "Suggest an idea" opens a prefilled
GitHub issue. Marketing register (gold accent), light + dark, responsive. A prototype to react to
before committing to a real data pipeline.

## Planned changes

- NEW `public-docs/src/pages/RoadmapPage.vue` — landing-style page (not DocLayout); scoped SFDS
  styles copied from HomePage.vue recipes; inline baked data; inline localStorage vote/comment logic.
- EDIT `public-docs/src/router/index.ts` — add `/roadmap` route before the catch-all.
- EDIT `public-docs/src/components/layout/TheNavbar.vue` — enable the roadmap link (desktop + mobile).

## Test plan

- No automated test suite in public-docs. Verification is manual + gates:
  - `npm run dev` → /roadmap renders; tabs switch Now/Next/Later/Shipped/Under consideration with
    counts; default Now; ETA ranges only on Now; Shipped shows green ✓ + date, no vote.
  - Vote toggles and persists on reload; comment appends inline and persists; "Suggest an idea"
    opens a prefilled GitHub issue.
  - Dark mode holds; mobile grid collapses; navbar switcher shows Roadmap.
  - Gates: `npm run type-check` && `npm run lint` && `npm run build` all green.

## Acceptance

- The page is reachable at /roadmap, matches the docs look in both themes, exercises all five
  buckets, and the three interactions (vote, comment, suggest) work. Gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — NEW `public-docs/src/pages/RoadmapPage.vue`; EDIT
  `public-docs/src/router/index.ts` (added `/roadmap` before the catch-all); EDIT
  `public-docs/src/components/layout/TheNavbar.vue` (added Roadmap to `products` + `currentProduct`,
  which surfaces it in the desktop row and the mobile switcher — cleaner than uncommenting the old
  standalone link).
- **Commits:** none yet — left uncommitted in the worktree pending user review + an epic decision.
- **Gates:** type-check clean (`vue-tsc --noEmit`), lint clean (oxlint + eslint), build ✓ (RoadmapPage
  chunk emitted). No test suite in public-docs.
- **Deviations:** (1) card grid uses individually-bordered cards + gap instead of HomePage's seamed
  1px-gap grid — the seamed look leaves gray blocks on partial rows, and roadmap buckets have variable
  counts. (2) ETA chips made neutral (not accent/gold) — gold is rationed to interaction + the win.
- **Verified:** light + dark + mobile; all five buckets; vote toggle + persist; comment add + persist;
  Shipped shows green ✓ + date and no vote; "Suggest an idea" → prefilled GitHub issue URL.
- **Follow-up (per Irina):** both the upvote and the comment now take an OPTIONAL name so we can reach
  back. A 👍/comment still counts anonymously; the upvote reveals an inline name field once toggled on,
  comments carry an optional name (shown, else "Anonymous"). Stored in `sf_roadmap_voter_names` +
  on each comment; dropping a vote clears its name. Older string[] comments normalized on load.

## v2 pass (2026-11-11) — faithful descriptions, vertical timeline, real statuses

- **Faithful copy from Linear.** Every card now carries a plain one-sentence `blurb` (topline) + a
  `detail` (2–4 sentences) grounded in its real Linear ticket (resolved via read-only MCP sweep) or,
  for the strategic epics (E1/E3/E6/E8/E9), the requirements capture `.docs/sf-roadmap-epics.md`.
  No em dashes, no AI-tells. Targeted lookups confirmed OME-1800/1315/1317/473 for the four cards the
  first sweep didn't join.
- **Data model.** `Item` gained `detail?`, `epic` (family label shown as a tag), `status`
  ('in-progress' | 'planned' | 'done', from real Linear state). `Bucket` gained `'shipped'` as a
  first-class key; `BucketDef` gained `band` (per-bucket month anchor).
- **Read more.** Detail is collapsed by default; an inline `Read more ▾ / Read less ▴` reveals it in
  place (`expanded` ref, session-only, `<transition name="reveal">`).
- **Vertical timeline.** Replaced the single-bucket tabbed board with one scrollable stack of bucket
  sections (Now → Next → Later → Under consideration → Shipped), each with a spine dot, time band and
  count. A horizontal time rail sits above. The old tabs became **filter chips** (`All` default +
  per-bucket) that scope the stack to one bucket; `active` is now `'all' | Bucket`.
- **Statuses.** Shipped cards read green (`.card--done` success left-seam, keeps ✓ + month).
  In-progress cards show a gold "In progress" badge — only in Now/Next (`showWip`), so a card parked
  under Later/Considering still reads as planned even if a ticket is open.
- **Hero copy** rewritten: compact, plain, no em dashes. Bucket notes trimmed; legend shows bands.
- **Epic worksheet (separate deliverable).** `.docs/sf-roadmap-epic-proposals.md` — read-only Linear
  sweep: 66 existing epics already map to buckets; only ~4 new groupings proposed (Support Requests &
  Hotfixes, Leaderboard Submission Controls, Run Queue Reliability, SDK DX) for one-by-one review.
  Nothing written to Linear.
- **Gates:** type-check clean, lint clean, build ✓ (RoadmapPage chunk emitted). Still uncommitted in
  the worktree pending review + the epic decision.

## v2.1 pass (2026-11-11) — review tweaks

- **Card header** restructured: epic kicker takes the left and can wrap; the "In progress" badge +
  month/shipped chip are one `.card__tags` cluster pinned top-right, so they sit in the same place
  on every card regardless of epic length.
- **OME id** removed from the card face; now a muted "Tracked in OME-N" line at the end of the
  expanded detail.
- **Equal / shorter cards:** title clamps to 2 lines, topline to 3; dropped the min-height reserves
  and tightened card padding/gap; grid `align-items: stretch` equalizes each row. Cards are notably
  shorter now that comments moved off the face (below).
- **Copy:** removed "Dates are rough and will change" (hero) + "Dates are rough and will move" (Now
  note, now just "Being built.") + the curated-roadmap disclaimer paragraph. Later band `H1 2027` →
  `2027`. Added a hero line: "Add new feature requests as GitHub issues in screamingface/screamingface"
  (linked). Both GitHub entry points (Suggest an idea + the lead link) now go to `issues/new/choose`.
- **Votes + comments → modal.** The card foot now shows a compact "↑ N votes" toggle + an "N comments"
  opener. Clicking opens a Teleport modal (Esc / backdrop close) with a Votes block (your vote +
  optional name, the seed as "+ N earlier votes") and a Comments block (name or Anonymous + text,
  readable) with the composer. Removed the inline comment list / add-comment / name field from cards.
- **Contributors section** ("Built by") pulls live from the public repo contributor API
  (`/repos/ScreamingFace/screamingface/contributors`), filters bots, merges a guaranteed extra
  (Dave `dbckz`; Bennett `bennettfarkas` already comes through the API; Osam skipped per Irina),
  de-dupes by login, sorts by contributions. Falls back to the seeded extra if the fetch fails.
- **Gates:** type-check / lint / build all green.

## v3 pass (2026-11-12) — content review + bucket merge + 2027 expansion

- **Buckets merged 5 → 4:** `later` + `considering` collapsed into one directional **Exploring 2027**
  bucket (key `exploring`, band 2027, note that order is open and votes/comments steer it). Timeline
  rail + open-dot updated.
- **Card rewrites (per Irina):** BYOM (local model + publish-to-gateway path); Submit →
  "Open submit to leaderboard"; Manage runs → "Manage evaluation runs"; Routers → "Routers,
  cascades, gates" with the full feature list (label/classifier/decision/encoder routing, multi-tier
  cascades on condition/failure/low-confidence, adaptive sampling, agreement gates, lazy judge
  fallback, budget caps); Outside leaderboards → "External results" (grounding vs established boards,
  not first-class/reproducible); Accurate cost & cache → "Cost across providers"; Concurrency limits →
  "Scale the platform" (dropped the documented-limit sentence); Ensembles in your IDE → "Fusions in
  any harness"; Syftspace → "Private data in url4". Sandboxed evaluations moved Now → Next. Scale-to-30
  dropped (covered by Scale the platform).
- **New cards:** NOW "Decision models" (encoders/classifiers as deciders). NEXT "Task decomposition",
  "Latency tracking" (on par with cost). EXPLORING 2027: Agentic loops & debate, Tools in fusions,
  Per-agent retrieval store, Train routers, Multi-turn benchmarks, Token-level ensembling, ForestBench,
  More domain benchmarks, Custom join functions (OME-1293), Recipe provenance (OME-1316), Verified
  submissions (OME-1319). SHIPPED: Pipelines, Image + text benchmarks.
- **Research (read-only, no writes):** three agents swept Linear triage/backlog, the user-request
  intake, and HubSpot declined applications. Full candidate list + sourcing in
  `.docs/sf-roadmap-2027-candidates.md`. **Public copy carries no reference to declined/rejected
  applicants** — demand is phrased as "a common/frequent request from researchers".
- **Titles** clamp to one line; most rewritten to fit. **Gates green.**
- **Stale:** `roadmap-cards.md` (root) predates this pass — regenerate on request.

## v4 pass (2026-11-12) — strip voting/comments for the PR

- **Votes + comments removed from the PR** (per Irina). The page is now a read-only roadmap:
  cards (epic tag, one-line title, topline, Read-more detail, eta/shipped chip, "Tracked in OME-N"),
  the vertical timeline + filter chips, "Suggest an idea" (GitHub), and the Built-by contributors
  pull. Removed: the 👍/💬 controls, the votes/comments modal, all localStorage logic, and **all
  seeded mock voters/comments** (no fake names/quotes land in the repo). The `votes` field is kept
  as an inert placeholder demand count; the interactive voting/comments feature is split to its own
  ticket for eng to decide where/how to persist (Supabase / KV / GitHub Discussions / SF service).
- Card content continued to firm up: many renames + a clarity pass for non-experts; buckets are
  Now / Next / Exploring 2027 / Shipped; new cards incl. modalities (audio, video, tabular, graph,
  3D+sensor), coding benchmarks, prompt optimization, config sweeps, latency tracking, budget
  management, decision models, pin-OpenRouter-providers. Verified submissions → Next.
- **Gates:** type-check / lint / build all green.
