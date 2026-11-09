---
ticket: OME-1826
stack: repo
status: in_progress
started: 2026-10-15
finished:
---

# docs-align-sf-client-0-1-11: Align the SF Client docs with screamingface 0.1.11

Versions: 0.1.9 (2026-11-04), 0.1.10 (2026-11-04), 0.1.11 (2026-11-05). Plan sections 8 (R1 to R8, 0.1.10) and 9 (S1 to S10, 0.1.11). The review report and the Outcome record 0.1.11. The "Retarget results" sections list each version.

Epic: `OME-426` (Docs polish pass, launch).

## Intent

Fix drift between the SF Client docs (`public-docs`) and screamingface 0.1.11, the released package. Every statement, sample and number on the affected pages is verified against 0.1.11 on a local engine, and on the hosted engine where the account allows. The pass follows the OME-898 rules for writing, terminology, claims and review, restated in the spec.

## Planned changes

- `public-docs/src/pages/sf-client/**` and `public-docs/src/pages/learn/**`: correct false claims, samples and numbers; split local and hosted content into separate sections where behaviour differs; switch dev hosts to production; remove slash benchmark ids, `sf.reproduce`, `hle` and the `draco-lite` link; state that capture is off unless `capture=True`.
- `public-docs/src/lib/engine.ts`: production engine URL.
- `public-docs/src/navigation/sf-client.ts`: footer reads the release tag.
- New or extended reference pages for the 0.1.11 surface: reducers and blocks including `sf.Mean`, `Fusion(quorum=, optional=)`, `sf.reports`, `sf.cache`, `sf.analytics`, `sf.classify`, case media, accounting and trace members.
- Diagram sources, SVG and PNG in `docs/diagrams/`.
- Exact file list is fixed in `docs/spec/` before implementation.

## Test plan

- `public-docs` has no test suite. Gates: `npm run type-check`, `npm run lint`, `npm run build`.
- Every code sample on an edited page runs against a fresh 0.1.11 install (local engine; hosted where the account allows) and its printed output is reprinted from the run.
- Every number, id, count and revision on an edited page is re-read from a live 0.1.11 call.
- Every cost claim is measured on a run or removed.
- Link check over the built site: every internal route resolves and every external link answers 200.
- Review report: three passes, nine-item scorecard with quoted evidence, trust check.

## Acceptance

- No page states a dev host as a default.
- No page lists a slash benchmark id, `sf.reproduce`, `hle` or the `draco-lite` link.
- No page states that capture is on by default.
- Each page that differs between local and hosted has a section for each.
- Every sample on an edited page was run on 0.1.11 and matches the printed output, or is marked unverified with the reason.
- Every name in the 0.1.11 `__all__` has a page, or is a listed named exception.
- No page documents a name that is not in the 0.1.11 `__all__`.
- Every diagram in the spec's Diagram plan exists as source, SVG and PNG.
- The review report exists, in the required order.
- No edited page contains an em-dash, and no heading is in title case.
- The footer names the newest release tag.
- Type-check, lint and build pass.

## Retarget results (0.1.11)

- **S1:** spec, plan, ledger, mirror and diagrams renamed and amended (`0d0d68dbc`). `len(sf.__all__)` is 105.
- **S2:** the chain syntax on Recipes, Fusions, Pipelines, Evaluation, Quickstart and First fusion (`12e5b6e92`). The text from PR #1680 was run with about 40 probes.
- **S3 and S4:** the Reducers reference, the Gate and the declared signals (`ed0799260`). `Logprob` and `Entropy` returned no value on any model tried (I-10).
- **S5:** the combine evidence, the trace keys and `JudgeWriterWarning` (`b5565bbad`). The report-browser Combine section is not described: not verified.
- **S6:** the url4 changes (`b83a7d1a7`). The single-model and plain-fusion url4 are byte for byte equal to 0.1.10. A scoring-judge url4 and a field-pick url4 changed. The old ones do not rebuild.
- **S7:** two diagrams updated and the narrow-chain diagram added (`c6cb7213e`).
- **S8:** 24 audit scripts run on 0.1.11 and diffed against the 0.1.10 outputs (`7eea0be1f`). Drift: local `models.list()` 109 to 110, `len(sf.__all__)` 92 to 105. No change: capture default, error texts, cost reporting, url4 length, connections. Run-to-run variation: tokens, costs, run ids. `part2b.py` (provider calls counted from the runtime log) gave 7 and 10 on the same SDK. `guides_ctor.py` checks the old Pipelines sample names and fails.
- **S9 (hosted, read only):** 112 models, 91 benchmarks, 91 leaderboards, `ifeval` 541 Cases, `medxpert` 2,450, `draco-3pass` 100, `PullResult(rows_read=4631, ...)`. All equal to 0.1.10. `cases=[999999]` returns `PlanningError invalid_benchmark_selection`. A chain ending after `sf.Fanout` raises `ValueError`. Both happen before any model call. Not verified: whether the hosted engine serves the narrow step.
- **S10:** the media sample, the `media_not_kept` error and the text-only refusal re-run on the engine of the `screamingface-v0.1.11` tag (`just local-stack-notebooks`): outputs equal to 0.1.10. Analytics re-measured on a fresh config home: unchanged.

## Retarget results (0.1.10)

- **R1:** spec, plan, ledger and diagrams renamed and amended (`b018a31c9`).
- **R2:** `evaluate(cases=)` documented from measured runs (`81f7c34b8`). Source only: the SDK refuses before any model call when the Engine does not echo the list.
- **R3:** analytics on by default, measured on a fresh config home (`10c710dac`). Not run: Colab, and the notebook (standard output) path of the notice.
- **R4:** local engine list (`medxpert` only from `screamingface up`) and the media sample re-run on the 0.1.10 release-tag engine (`920441c76`).
- **R5:** the connection listing has no SDK change; the text-only model refusal on picture benchmarks documented (`7a668c2bb`).
- **R6:** 36 audit scripts run on 0.1.9 and on 0.1.10 against the same engine and diffed. The only deterministic SDK differences are the `cases` parameter and the analytics default. Counts (109 local models, 7 providers, `medxpert` 2,450 Cases, 92 `__all__` names), error texts, cache and capture behaviour, url4 length and the Mean and Pick outputs (`'3.75'`, `'green'`) are identical. Differences in token counts, costs, run ids and model-echoed JSON spacing are run-to-run variation. No page contains the string "0.1.9". `p5_reducers.py` timed out at 420 s on both versions (provider latency on `deepseek-v4-pro`) and was re-run with a longer limit.
- **R7 (hosted, read only):** 112 models, 91 benchmarks (89 before; `labbench2_figqa2_img` and `labbench2_tableqa2_img` are new), 91 leaderboards, `ifeval` 541 cases, `medxpert` 2,450, `draco-3pass` 100, and `PullResult(rows_read=4631, ...)` for `claude-opus-4.8`. `cases=[999999]` on the hosted engine returns `PlanningError invalid_benchmark_selection` with no model call, so the hosted engine serves the selection route. The provider status of this account is `not_connected` for all seven providers on both SDK versions.
- **Not verified on 0.1.10:** a hosted `evaluate`, publish and replay, which write data or spend hosted compute.

## Review report

Method: three passes over the edited pages in the reader's order (Overview, Installation, First fusion, Quickstart, then guides, API reference, learn pages), the nine-item scorecard, the trust check. Scans over all pages in `public-docs/src/pages` for performance adjectives, claims words, title-case headings and terminology counts. Unavailable context slots: time budget and operational metrics (no source supplies them).

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
- The Caching page: a state table of partial reasons that matches the code, with a state diagram.
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

### Addendum for 0.1.11

Scope: the chain syntax, the Reducers reference, the combine evidence and the url4 changes. Scan over all pages: no performance adjective, no claims word and no dash in a page. "simplest" appears on two learn and API pages and "state-of-the-art" in one link title.

| # | Item | Score | Quoted evidence |
|---|---|---|---|
| 3 | Concept ordering | 3 | Reducers: "the block ends in one reducer, a step the engine runs without writing a new answer, or in one sf.Synthesize writer" comes before "Narrow steps" and "Gate", which it uses |
| 6 | Reference navigability | 4 | every one of the 105 names in `__all__` has a page (checked by script) |
| 7 | Terminology discipline | 2 | "engine" 370 times against "Engine" 50; "stage" 73 against "step" 113 in the same chain pages (the SDK's own errors say "stage") |
| 8 | Honest operations | 4 | "No model that was tried returned a value, so no printed value is shown for these two signals." |
| 9 | Visual clarity | 4 | seven diagrams, including the narrow-chain flow whose values come from a run |

Open from this addendum: the Reducers page carries 9 notebook cells and 8 tables on one page (reference, as the Divio type requires); the printed `Logprob` and `Entropy` values are unverified (I-10); the report-browser Combine section is not described.

## Outcome

- **Actual files:** `public-docs/src/pages/sf-client/**` (guides, API reference, the new `ClassifyPage.vue`, the rewritten `ReducersPage.vue`), `public-docs/src/pages/learn/**`, `HomePage.vue`, `public-docs/src/router/index.ts`, `public-docs/src/navigation/sf-client.ts`, `public-docs/src/components/ui/ThemedDiagram.vue`, `public-docs/CLAUDE.md`, `public-docs/public/diagrams/`, `docs/diagrams/` (six new diagrams as SVG and PNG with their generator, four request-architecture diagrams corrected), `docs/spec`, `docs/plan`, `docs/work`, `docs/tasks`.
- **Commits (0.1.9 pass):** `bca712edb`, `b59b89b44`, `9075d0054`, `3ad7d0093`, `3f8bbc96c`, `c5c182a0c`, `e9ff1fbb3`, `f23a4e797`, `e39f0e051`, `9597e70f4`, `f70488d7b`, `b440b5e69`, `e9cf55b04`.
- **Commits (retarget to 0.1.10):** `b018a31c9`, `81f7c34b8`, `10c710dac`, `920441c76`, `7a668c2bb`, `ed0abf6f2`, `4e92622a7`, `fd0b0e5aa`, `0f6d65faa`, `ff570d9c0`.
- **Commits (retarget to 0.1.11):** `e60610f22` merge of `origin/main`, `0d0d68dbc` rename and amend, `12e5b6e92` chain syntax, `ed0799260` Reducers, `b5565bbad` combine evidence, `b83a7d1a7` url4, `c6cb7213e` diagrams, `7eea0be1f` counts, and the commit that closes the pass.
- **Gates:** `npm run type-check`, `npm run lint` (0 errors), `npx prettier --check src` and `npm run build` pass. Search checks over `public-docs/src` find none of `fusion.dev`, `leaderboard.dev`, `sf.reproduce`, `hle`, `draco-lite`, `sf.Pick`, `sf.Reduce`, `.then(`, `stages=`, `extract=`, a dev host, "0.1.9", or a dash in a page. Every name in the 0.1.11 `__all__` (105) has a page and no `sf.*` name in a page is unresolved. All external links answer 200, and every internal route resolves.
- **Deviations:** (1) The footer reads the newest release tag. (2) Not verifiable on 0.1.11 and marked on the pages or here: a hosted `evaluate`, publish and the replays (they write data or spend hosted compute); whether the hosted engine serves the narrow step; `edit` and `metadata_events` on a real board; Colab analytics and the notebook path of the analytics notice; the `openai` and `huggingface` cached-provider rows (source only); a printed `sf.Logprob` or `sf.Entropy` value (no model returned one, I-10); the SDK refusal when an Engine does not echo `cases=` (changelog only); the report-browser Combine section and the media buttons. (3) The case media sample ran on the engine of the release tag from a repository checkout, not on the engine that `screamingface up` starts. (4) Findings that need an owner or Eng are in `issues-tracker.md` (I-5 to I-14), outside the repository. (5) The text of PR #1680 is the base of the Fusions, Pipelines and Recipes pages.
- **Review report:** written against the 0.1.9 pages, with an addendum for 0.1.11.
