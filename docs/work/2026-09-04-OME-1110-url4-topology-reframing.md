---
ticket: OME-1110
stack: repo
status: done
started: 2026-09-04
finished: 2026-09-04
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
