---
ticket: OME-426
stack: repo
status: in_progress
started: 2026-10-15
finished:
---

# docs-align-sf-client-0-1-10: Align the SF Client docs with screamingface 0.1.10

> Retargeted on 2026-11-04 from 0.1.9 to 0.1.10 after the 0.1.10 release. The review report and outcome below record the 0.1.9 pass as committed; plan section 8 (parts R1 to R8) re-verifies it on 0.1.10 and the outcome is rewritten at R8.

Epic: `OME-426` (Docs polish pass, launch).

## Intent

Fix drift between the SF Client docs (`public-docs`) and screamingface 0.1.10, the released package. Every statement, sample and number on the affected pages is verified against 0.1.10 on a local engine, and on the hosted engine where the account allows. The team's answers to the open questions decide which side is right. The pass follows the OME-898 rules for writing, terminology, claims and review, restated in the spec.

## Planned changes

- `public-docs/src/pages/sf-client/**` and `public-docs/src/pages/learn/**`: correct false claims, samples and numbers; split local and hosted content into separate sections where behaviour differs; switch dev hosts to production; remove slash benchmark ids, `sf.reproduce`, `hle` and the `draco-lite` link; state that capture is off unless `capture=True`.
- `public-docs/src/lib/engine.ts`: production engine URL.
- `public-docs/src/navigation/sf-client.ts`: footer reads the release tag.
- New or extended reference pages for the 0.1.10 surface: reducers and blocks including `sf.Mean`, `Fusion(quorum=, optional=)`, `sf.reports`, `sf.cache`, `sf.analytics`, `sf.classify`, case media, accounting and trace members.
- Diagram sources, SVG and PNG in `docs/diagrams/`.
- Exact file list is fixed in `docs/spec/` before implementation.

## Test plan

- `public-docs` has no test suite. Gates: `npm run type-check`, `npm run lint`, `npm run build`.
- Every code sample on an edited page runs against a fresh 0.1.10 install (local engine; hosted where the account allows) and its printed output is reprinted from the run.
- Every number, id, count and revision on an edited page is re-read from a live 0.1.10 call.
- Every cost claim is measured on a run or removed.
- Link check over the built site: every internal route resolves and every external link answers 200.
- Review report: three passes, nine-item scorecard with quoted evidence, trust check.

## Acceptance

- No page states a dev host as a default.
- No page lists a slash benchmark id, `sf.reproduce`, `hle` or the `draco-lite` link.
- No page states that capture is on by default.
- Each page that differs between local and hosted has a section for each.
- Every sample on an edited page was run on 0.1.10 and matches the printed output, or is marked unverified with the reason.
- Every name in the 0.1.10 `__all__` has a page, or is a listed named exception.
- No page documents a name that is not in the 0.1.10 `__all__`.
- Every diagram in the spec's Diagram plan exists as source, SVG and PNG.
- The review report exists, in the required order.
- No edited page contains an em-dash, and no heading is in title case.
- The footer names the newest release tag (the owner's decision).
- Type-check, lint and build pass.

## Retarget results (0.1.10)

- **R1:** spec, plan, ledger and diagrams renamed and amended (`b018a31c9`).
- **R2:** `evaluate(cases=)` documented from measured runs (`81f7c34b8`). Source only: the SDK refuses before any model call when the Engine does not echo the list.
- **R3:** analytics on by default, measured on a fresh config home (`10c710dac`). Not run: Colab, and the notebook (standard output) path of the notice.
- **R4:** local engine list (`medxpert` only from `screamingface up`) and the media sample re-run on the 0.1.10 release-tag engine (`920441c76`).
- **R5:** the connection listing has no SDK change; the text-only model refusal on picture benchmarks documented (`7a668c2bb`).
- **R6:** 36 audit scripts run on 0.1.9 and on 0.1.10 against the same engine and diffed. The only deterministic SDK differences are the `cases` parameter and the analytics default. Counts (109 local models, 7 providers, `medxpert` 2,450 Cases, 92 `__all__` names), error texts, cache and capture behaviour, url4 length and the Mean and Pick outputs (`'3.75'`, `'green'`) are identical. Differences in token counts, costs, run ids and model-echoed JSON spacing are run-to-run variation. No page contains the string "0.1.9". `p5_reducers.py` timed out at 420 s on both versions (provider latency on `deepseek-v4-pro`) and was re-run with a longer limit.
- **Not verified on 0.1.10:** hosted values (112 hosted models, 89 hosted benchmarks, 91 leaderboards, the 4,631-row cache pull), until the hosted login in R7.

## Review report

Method: three passes over the edited pages in the reader's order (Overview, Installation, First fusion, Quickstart, then guides, API reference, learn pages), the nine-item scorecard, the trust check. Scans over all pages in `public-docs/src/pages` for performance adjectives, claims words, title-case headings and terminology counts. Examples were run in earlier parts; this part runs none. Unavailable context slots: time budget and operational metrics (no source supplies them).

**Reader:** ensemble routing researcher (priority 0). **Goal:** install the Client, run a fusion on a benchmark, read the score and the cost, share or replay the run.

### 1. Verdict

A researcher can reach a first scored run from the docs alone on the local engine, and the printed outputs match 0.1.9. Understanding flows through the Overview, Installation and First fusion. It breaks in the Quickstart: it uses "candidate" in its first sentence and defines it at step 3, and step 2 carries provider-connection reference (OAuth flows, panel states) before the reader has composed anything. The largest open defect is terminology: "engine" is lower case 356 times and "Engine" 46 times.

### 2. Friction log

| # | Location | Sentence | Status |
|---|---|---|---|
| 1 | Overview, intro | "fully reproducible and trackable across the cost-quality Pareto frontier" | fixed |
| 2 | Overview, features | "Lower cost through shared caching" (adjective, no number) | fixed |
| 3 | Overview, intro | "the best fusion reached 68.6%, while the best single model managed 60.2%" (method and conditions are on the linked source only) | open, owner |
| 4 | Overview | "pointing the SF Client at a local engine" (the same page also says "ScreamingFace Client") | fixed on the page; nav label "SF Client" open (issue tracker) |
| 5 | Installation 1 | "Everything else, including url4, resolves automatically." (url4 is defined on the Overview, not here) | open |
| 6 | First fusion, intro | "It takes a few lines and a couple of minutes." (no measurement) | fixed |
| 7 | First fusion 3 | "This is the most accessible kind of fusion" | fixed |
| 8 | First fusion 4 | "so this stays quick and cheap while you are finding your feet" | fixed |
| 9 | First fusion 5 | "Nothing here was mocked." | fixed |
| 10 | Quickstart, intro | "a scored comparison of 4 candidates" (defined at step 3: "A candidate is anything you are submitting to be scored") | fixed ("four recipes") |
| 11 | Quickstart 2 | "walking through all six states of the auth flow" (reference material inside a tutorial) | fixed: panel states and OAuth moved to links |
| 12 | Quickstart 3 | heading "Caching keeps reruns cheap" | fixed |
| 13 | Url4 guide | "This makes results auditable." (the claims rule reserves "auditable" for held-out scores) | fixed |
| 14 | Url4 files (learn) | a draft-status sentence that names a reviewer | open, owner (Sergey) |

### 3. Flow map

- Quickstart intro uses "candidate" before step 3 defines it. Move the definition before the count, or say "four recipes" in the intro.
- Quickstart step 2 (connect) holds reference content: panel states, OAuth flow, `flow.wait()`. It serves two page types. The reference belongs on the Connections guide, which already covers it. The tutorial keeps one script connection.
- The Quickstart step "The request cache" is explanation inside a tutorial. The Caching page holds it.
- The "Two ways to run" choice (local or hosted) is stated in prose on the Overview, Installation and First fusion. Each page restates it.

### 4. Scorecard

| # | Item | Score | Quoted evidence |
|---|---|---|---|
| 1 | First contact | 4 | "an open-source, Python-first toolkit for composing model fusions ... and measuring them as a single system with uniform grading" |
| 2 | Time to first success | 4 | "On medxpert with limit=3 the fusion answered two of three correctly. The run cost $0.17" |
| 3 | Concept ordering | 3 | "a scored comparison of 4 candidates" before "A candidate is anything you are submitting to be scored" |
| 4 | Learning-curve shape | 3 | Quickstart step 2: "walking through all six states of the auth flow", before the first fusion exists |
| 5 | Example quality | 4 | "The run below cost $0.26 for the four candidates." (reprinted from a run) |
| 6 | Reference navigability | 4 | every name in the 0.1.9 `__all__` has a page under `sf-client/api/` (checked by script) |
| 7 | Terminology discipline | 2 | "engine" 356 times against "Engine" 46; "AI gateway" 10 against "AI Gateway" 2; "SF Client" 5 against "ScreamingFace Client" 4 |
| 8 | Honest operations | 4 | "A local engine started with screamingface up serves medxpert"; item 3 of the friction log is the gap |
| 9 | Visual clarity | 4 | six diagrams added in part 11, labels match the prose |

### 5. Diagram plan

All six planned diagrams exist (part 11). Open:

1. **Overview, local or hosted** (decision). Question: which engine do I point the Client at? Boxes: "ScreamingFace Client" to "local ScreamingFace Engine (your keys, empty cache)" and to "hosted ScreamingFace Engine (shared cache, access from the OpenMined team)". Source:

```
flowchart LR
  C[ScreamingFace Client] -->|your keys, empty cache| L[local ScreamingFace Engine]
  C -->|access from the OpenMined team, shared cache| H[hosted ScreamingFace Engine]
```

2. **Architecture, cloud diagram.** The subtitle read "SUBSIDIZED CLOUD · OPENMINED RUNS THE ENGINE · YOU JUST COMPOSE" (sales register). Applied: "HOSTED · THE OPENMINED TEAM RUNS THE ENGINE".

### 6. Top fixes

| Priority | Location | Before | After | Status |
|---|---|---|---|---|
| 1 | All pages | "engine" lower case 356 times | "ScreamingFace Engine" at first use and "the Engine" after, "an engine" kept where the word is generic | open, owner decides the rule |
| 2 | Quickstart intro and step 3 | "4 candidates" before the definition | "four recipes: three solo models and one fusion", with "candidate" defined at step 3 | applied |
| 3 | Quickstart step 2 | panel states and OAuth inside the tutorial | one script connection, links to the Connections guide and reference | applied |
| 4 | Overview, intro | "fully reproducible and trackable across the cost-quality Pareto frontier" | "grade every system the same way and show its score next to its cost, and each result carries its url4" | applied |
| 5 | First fusion | "stays quick and cheap while you are finding your feet" | "runs three cases" | applied |
| 6 | Url4 guide | "This makes results auditable." | "This makes a result reproducible." | applied |
| 7 | Overview, intro | DRACO 68.6% against 60.2% | add the method and conditions beside the figure, from the linked source | open, owner |

### 7. What already works

- First fusion: one printed result with its cost, `limit=3`, local and hosted split.
- The Caching page: a state table of partial reasons that matches the code, now with a state diagram.
- The Installation FAQ: each entry gives the symptom, the cause and the command.
- Every public name has a page, and every printed output was reprinted from a 0.1.9 run.

### Trust check

| Check | Result |
|---|---|
| Plain limits | pass: hosted access, local benchmark coverage and unverified items are stated at the point of use |
| Numbers over adjectives | three adjectives fixed (items 2, 7, 8); item 3 open |
| Operational reality at the decision | pass: cost lines are measured or removed |
| Marketing residue | one sentence fixed (item 1); cloud diagram subtitle open |
| Versioning and stability | the sidebar footer names the release; no migration or changelog statement exists on the site. Open, owner. |

Rewrites of sentences that failed are in the Friction log and Top fixes tables.

## Outcome

- **Actual files:** 84 files in the 12 unpushed commits (plus the earlier pushed ones): `public-docs/src/pages/sf-client/**` (guides, API reference, new `ClassifyPage.vue`), `public-docs/src/pages/learn/**`, `HomePage.vue`, `public-docs/src/router/index.ts`, `public-docs/src/navigation/sf-client.ts`, `public-docs/src/components/ui/ThemedDiagram.vue`, `public-docs/CLAUDE.md`, `public-docs/public/diagrams/`, `docs/diagrams/` (five new diagrams as SVG and PNG with their generator, four request-architecture diagrams corrected), this ledger.
- **Commits:** `bca712edb` get-started pages, `b59b89b44` guides, `9075d0054` API reference, `3ad7d0093` recipe reference, `3f8bbc96c` learn pages, `c5c182a0c` cache and analytics, `e9ff1fbb3` capture off by default, `f23a4e797` reducers, `e39f0e051` validation fixes, `9597e70f4` classify and case media, `f70488d7b` diagrams, `b440b5e69` review report and fixes.
- **Gates:** `npm run type-check`, `npm run lint` (0 errors), `npx prettier --check src` and `npm run build` pass. Search checks over `public-docs/src` find none of `fusion.dev`, `leaderboard.dev`, a slash benchmark id, `sf.reproduce`, `hle`, `05_draco_lite_e2e`, `07_ifeval_e2e`, `cases=`, `Fanout`, `JudgePick`, `draco-lite`, a dev host. No em-dash or en-dash in a page, a heading or a diagram; the dashes left in `src` are in code comments of files this pass did not edit. All 12 external links answer 200. Every internal route resolves (the one dead path, `/roadmap`, is in a commented-out block). Every name in the 0.1.9 `__all__` has a page.
- **Deviations:** (1) The footer reads 0.1.10: the branch contains the `screamingface-v0.1.10` tag and the label is the newest reachable release tag. The owner decided the footer follows the tag, so the acceptance line "the footer names 0.1.9" is replaced by "the footer names the newest release tag". The pages document 0.1.9. (2) Not verifiable on 0.1.9 and marked so on the pages: hosted `evaluate`, publish, private, partial and unsubmitted replays, exact replays, `edit` and `metadata_events` on a real board, Colab analytics, the `openai` and `huggingface` cached-provider rows (source only). (3) The case media sample ran on an engine from repository `main`, not on a released engine; the page says so. (4) The report-browser media buttons are not described, because they were not verified. (5) Findings that need an owner are in `issues-tracker.md` (I-5 to I-9), outside the repository.
