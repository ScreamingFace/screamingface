---
ticket: OME-1110
stack: repo
status: in-review
started: 2026-09-04
finished:
---

# OME-1110 — Reframe url4 topology: node, host, discovery, addressing, transport (spec + PDF)

## Intent

Give url4's foundational components crystal-clear definitions before the Engine evolves further.
Deliver a short, plain-English PDF with diagrams that states the reframing, points into the
current spec (Kevin's Parts A/B v0.5; v0.2 monolith for §9–§40), and carries an appendix of
proposed spec deltas for the grammar owner. Research showed Parts C–I are unwritten stubs, so
this is the first execution/transport/discovery text. Decisions were locked in a grill session
on 2026-09-04 (18 decisions, 3 deferrals) — see the plan file and the Linear issue body.

## Planned changes

- `docs/spec/2026-09-04-OME-1110-url4-topology-reframing.md` — source document (≤ ~12 pages).
- `docs/spec/2026-09-04-OME-1110-url4-topology-reframing.pdf` — rendered PDF (weasyprint).
- `docs/diagrams/url4-topology-{anatomy,addressing,request-tree,discovery,delivery,engine}.{svg,png}`.
- `.claude/skills/url4-engine/SKILL.md` — T1 → SSE per node; N1 wording (RFC 9110 idempotent);
  F2 → OTLP durable export; F4 resolved; term table; pointer to the spec doc.
- `docs/tasks/2026-09-04-OME-1110-url4-topology-reframing.md` — mirror.

## Test plan

No code. Verification gates:
- PDF renders without errors; page count ≤ ~12; all six diagrams embedded.
- Every SVG converts with `rsvg-convert`; PNG committed alongside.
- Every spec citation resolves (script greps each `§` in Parts A/B or the v0.2 monolith).
- ASCII box diagrams pass a column-alignment check.
- Plain-English pass on the summary page (short sentences, no undefined acronym).

## Acceptance

- Owner can answer the eight original questions from the summary page alone.
- The discovery section lets the owner choose `.well-known` vs OPTIONS from the pros/cons given.
- Appendix A lists each proposed spec delta with its spec anchor.
- Appendix B lists the follow-up work items to file (Engine host surface, SSE binding, root path, …).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `docs/spec/2026-09-04-OME-1110-url4-topology-reframing.md` (source) and
  `…reframing.dark.pdf` (the deliverable; owner chose dark only, light PDF removed), six
  `docs/diagrams/url4-topology-*.{svg,png}` (light, embedded by the markdown) plus their `-dark`
  variants (embedded by the PDF; same generator, SFDS `[data-theme="dark"]` tokens), `.claude/skills/url4-engine/SKILL.md`,
  `docs/tasks/2026-09-04-OME-1110-url4-topology-reframing.md`, this ledger.
- **Commits:** see PR (squash).
- **Gates:** PDF renders (WeasyPrint 69 via `uv run --with weasyprint`, `DYLD_LIBRARY_PATH=/opt/homebrew/lib`):
  10 pages incl. title, all six diagrams embedded, Plex fonts embedded. `rsvg-convert` OK for 6/6 SVGs.
  Citation check: 64 `§` citations, 0 unresolved (Parts A/B headings; v0.2 monolith headings; Part C/G
  range check). Six diagrams reviewed visually at 2x for overlap/overflow after two fix rounds.
- **Deviations:** (1) `diagramming:architecture-diagram` was consulted for placement rules only; its
  dark HTML template violates the brand law (rounded corners, slate palette) and the stored feedback
  "SVG not HTML", so diagrams are SFDS-styled SVGs from a small generator (scratchpad, not tracked).
  (2) The PDF build (pandoc → HTML + SFDS CSS → WeasyPrint) lives in the session scratchpad, not the
  repo; the system `weasyprint` install is broken (tinycss2 mismatch) so the build runs it isolated.
  (3) IBM Plex TTFs were fetched from Google Fonts and installed to `~/Library/Fonts` so rsvg and
  WeasyPrint render the same faces. (4) Two spec deltas cite `v0.2 §33/§34` rather than `Part C`
  because the v0.5 index allocates those topics to Part H. (5) Q12 (plan/preflight) was deferred by
  the owner mid-grill after validation showed no such facility exists. (6) Q5/Q13 revised by the
  owner after review: delivery is negotiated in one request (`Upgrade: websocket` + `Accept`), the
  node picks WS → SSE → sync; sync is the only MUST, SSE/WS/async SHOULD; doc §6, the delivery
  diagram and doctrine T1/T3 updated accordingly. (7) Owner added the typed-payloads research
  (ComfyUI analogy): new §8, seventh diagram `url4-topology-payloads`, Appendix A delta for Part F
  §25, doctrine N6; Engine and Deferred renumbered to §9/§10. (8) Owner example added: any scheme is a
  source (`s3://`, `pg://`, `sqlite://`) via host-mounted adapters; §2, addressing diagram row,
  capabilities `schemes`, Appendix A delta 9, doctrine N7. (9) Owner question added to §10:
  authentication as a host concern (host issues run-scoped sessions; nodes never hold raw credentials);
  six questions listed, grounded on v0.2 §22, Part B §3.5 and the Engine's token-minting App.
  (10) Owner asked for the networking view: new §11 brainstorm (host egress vs delegated token vs
  sidecar; recommendation A for nodes, B between hosts) with the eighth diagram
  `url4-topology-auth-network` (light + dark). (11) Owner reopened plan/preflight as a question
  (§10): a host dry run via `Prefer: dry-run`, envelope-only answer; five sub-questions; removed from Deferred.
  (12) 2026-09-08: owner asked to reconcile with the `url4-refactor` branch of
  `OpenMined/screamingface-design`, which carries draft Parts C–I (2026-04-28, v0.4 text, unreviewed)
  and a v0.4 monolith that renumbers §21+. Three parallel readers compared the drafts against the
  document. Every `v0.2 §N` citation re-anchored to Part numbering (crosswalk by heading title;
  242 citations resolve); new §12 alignment table (18 rows); in-place corrections: capabilities
  document exists (Part G §27.2) and sub-paths are collections, `Capabilities` header as a third
  discovery mechanism (recommendation now A + C), mounts mapped onto intent-processor types,
  `delivery=async` + `poll_url` instead of `Prefer`/`Location`, dedicated
  `application/url4-envelope+json` wrapper type instead of overloading `Accept`, `;accept` short
  aliases, data-URI binary with `result.content_type`, four-value `ct_mismatch`, statelessness
  narrowed for agent sessions, host forwards (never mints) inter-host tokens per Part H §31,
  flow-constraint cautions, root/version tensions. Appendix A re-anchored and extended to 12 deltas.
  Doctrine skill T2/F3 corrected. Dark PDF 20 pages.
  (13) 2026-09-08, owner: vocabulary realigned to the spec's own words — **node** = origin serving a
  set of **endpoints** (`/claude`, `/codex`); "host" dropped; Appendix A delta 1 becomes "endpoint
  kinds" instead of a rename; diagrams, glossary and doctrine skill renamed. Document split into two
  renders from one source: core (§0–§9 + Appendix C/D, 16 pages) and open-work (§10–§13 +
  Appendix A/B, 10 pages). New §13: url4 as a network protocol (submit, not call; peer-to-peer
  resolution) recorded as a question with what the spec already gives it and what is new.
  (14) 2026-09-15, owner: reconcile against **Kevin's reply** — `OpenMined/screamingface-design`
  PR #19 (`url4/terminology-refresh`, **draft**, one commit `2a939bff`, opened 2026-09-15, no
  reviews, branched off `main` — *not* `url4-refactor`). It rewrites Part A §1.4 from one flat
  26-row table into five sub-tables (1.4.1 Grammar · 1.4.2 Network · 1.4.3 Expression Processing ·
  1.4.4 Transport · 1.4.5 General) and absorbs most of our Appendix D into the spec. **Kevin's text
  has priority wherever the two differ.** Scope of this round is recorded below.

## Round 2026-09-15 — reconciliation with Part A §1.4 (PR #19) + committed builder

**Why a continuation of OME-1110, not a new item.** Linear had OME-1110 *In Review* and draft PR
[#838](https://github.com/ScreamingFace/screamingface/pull/838) open on `OME-1110-url4-topology`
(14 commits ahead of `main`): the document has never landed. Kevin's PR #19 is review feedback on
an unmerged deliverable, so it continues this unit rather than splitting one document across two
issues and two PRs. Issue moved back to In Progress; this ledger is reopened rather than replaced.

**Adopted by Kevin from our Appendix A / Appendix D** — `Mount` (our three kinds verbatim),
`Evaluator` / `Evaluation`, `Dry run`, `Degradation`, `Response ladder` (WS → SSE → sync),
`Scheme adapter`, `Flow constraints`, `Attribution`, `Collection`, `Holdings`, `Request Tree`,
`Run handle`, the `Accept: application/url4-envelope+json` envelope switch, and `websocket` as a
fourth `delivery` value. Appendix A deltas 1, 4, 7, 9, 10 have therefore landed; delta 1
("endpoint kinds") is superseded — Kevin kept Node/Endpoint and added `Node address` and
`Endpoint path`.

**Decisions locked by the owner this round**

1. **Appendix D → crosswalk.** The 2-page parallel glossary is replaced by a one-page
   `our term → Part A §1.4.x → adopted / delta / still ours` table, moved beside §12 in the
   open-work render: it is a delta record, and core is better as purely the settled definitions.
2. **host vs node — flag as erratum, stay node-only.** Our prose keeps zero uses of "host".
3. **Commit the builder** to `docs/tools/specpdf/`.

**New Appendix A deltas this round** — (13) host vs node: `Host system` is welcome in §1.4.2 as a
deployment word, but §1.4.4 `Delivery mode` / `Response ladder` and the §1.4.3 `Scheme adapter`
row all write "host" where the actor is the **node**; (14) `Request Tree` lost its strictness
("an evaluator may expand the tree") against Part H §29.1; (15) our doctrine numbering leaked into
the spec — the `Mount` row cites "**N4**", which is `.claude/skills/url4-engine/SKILL.md`, not a
spec anchor; (16) `Holdings` carries `Collection`'s anchors (Part B §5.3, Part G §27.4) where ours
had Part B §5.6, and `Self-reference` / `Identity-reference` were dropped as rows — confirm the
fold is intentional; (17) branch/anchor hazard — PR #19 targets `main`, where Parts C–I are "Not
yet written" stubs, yet its new rows cite Part C §10.2, Part G §27.3 and Part H §31, which resolve
only on `url4-refactor`; (18) typos: "Inter-host **tone**" → token, "Request **identifer**" ×2,
"Extention", unclosed bold in "nested **Expression\*" and "one or more **nodes\*", "ore more",
"executing **then** intent", "advertising **a its** collections", stray `.` in `Scheme adapter`.

**The build had to be reconstructed, not re-run.** Deviation (2) above put the pandoc → SFDS CSS →
WeasyPrint pipeline, the core/open-work split and the SVG diagram generator in the session
scratchpad; `/private/tmp/…/4eaaa65c-…/scratchpad/build/` has since been emptied by the tmp
reaper. The committed SVGs were the only surviving diagram artifact and the `weasyprint` on PATH
is still broken (tinycss2 mismatch, deviation 2). Hence decision 3: `docs/tools/specpdf/` now
carries `build.py`, `sfds-print.css`, `diagrams.py`, `split.toml`, vendored Plex fonts and a
pinned WeasyPrint, so the next revision recompiles instead of reconstructing. This also retires
deviation (3) — the build no longer depends on `~/Library/Fonts`.

**Layout defects fixed in the same pass** (all verified against the 2026-09-08 renders): the
"Three candidate mechanisms" table on open-work p4–p5 overlapped its own cells
("Whereredentialslive", "Policy,disclosure,cache,budgets,ratelimits"); core p6 (§5) and p8 (§6)
each stranded ~40% of a page under an orphaned heading; neither PDF carried bookmarks, a TOC or a
single internal link across 240+ `§` cross-references; both files shared one `/Title`.

**Risk.** PR #19 is a draft opened hours before this round and can change. The front matter, §12
and the crosswalk pin `2a939bff`; Appendix B carries a re-review follow-up for when it leaves
draft.

**Gates (2026-09-15).** 34 builder tests pass. Both PDFs render via
`uv run --directory docs/tools/specpdf build.py --part all`: core 16pp, open-work 14pp, distinct
`/Title`, 12 bookmarks each, 22 and 15 internal links. `rsvg-convert` 16/16 SVGs; all 16 have PNG
twins. Citations: 5/5 `§1.4.x` anchors resolve against Part A at `2a939bff`, 228 `Part X §N`
citations, 0 dangling `delta N` references, 0 internal `§N` pointing at a section that does not
exist. No prose uses "host" for "node" — the 22 remaining occurrences are `Host system`, quoted
Kevin text, the `s/host/node/` proposal, or the `Inter-host tone` typo being flagged. No ASCII box
diagrams in this document, so that check is N/A.

**Deviations this round.** (a) Continued on OME-1110 rather than filing a new work item — see the
reasoning at the top of this round. (b) `break-before: avoid` on figures was tried to close the
whitespace above §2's diagram and **reverted**: it moved the gap up a page and grew the core render
to 17 pages. With 980×580 figures on A4 some whitespace above a figure is unavoidable; the defect
that mattered — a heading alone at the foot of a page — is fixed. (c) The eight diagrams needed no
regeneration: their text carries no ownership claim and no stale term, so `diagrams.py` was not
reconstructed this round. `docs/tools/specpdf/README.md` records what the builder does and does not
yet own.

**Open for the owner.** `docs/diagrams/url4-topology-request-tree.{svg,png}` is committed but
referenced nowhere in the source (pre-existing, not introduced this round). Delta 14 is precisely
about request-tree strictness, so it could earn a place in §13 — or it should be removed.

**Vocabulary validation (2026-09-15, owner-requested).** A mechanical audit of the rendered PDF
text against every term in Part A §1.4 at `2a939bff` (45 terms; local copy verified byte-identical,
blob `0d9d071b`) found drift the reconciliation pass had missed: "requester" ×7 where the spec's
word is **requestor**; §0 Q1 still defining an endpoint as "a stateless function behind a path"
(the 2026-09-08 wording, contradicting §1's own row and §1.4.2's *logical interface … identified by
an endpoint path*); "plan" as a noun ×3 after the word was retired for **dry run**; and bare
"ladder" as the headword where the spec's term is **response ladder**. The anatomy diagram caption
carried the stale endpoint definition and the delivery diagram the bare "Ladder, not error"; both
fixed in light + dark with PNGs regenerated. Doctrine skill: "requester" and "Ladder:" corrected.
Residuals judged legitimate: three "ladder" anaphora inside the §6 paragraph that names the
response ladder one sentence earlier; "host" only inside delta 13, which quotes Kevin verbatim;
sentence-case "request tree" against Kevin's "Request Tree", noted in the crosswalk — his other
terms are sentence case. Rebuilt PDFs are text-identical to a fresh build from source.
