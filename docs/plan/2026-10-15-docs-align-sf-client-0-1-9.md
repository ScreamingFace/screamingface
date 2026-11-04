# Align the SF Client docs with screamingface 0.1.9: plan

Status: draft · Refs: `OME-426` · Spec: `docs/spec/2026-10-15-docs-align-sf-client-0-1-9.md` (draft)
Branch: `callis/ome-426-docs-polish-pass-launch`, renamed to `OME-<N>-<description>` at PR-open.
Landing: `public-docs`, `docs/diagrams`, `docs/spec`, `docs/plan`, `docs/work`, `docs/tasks`.

## 1. Shape of the delivery

One pull request and one Linear issue under `OME-426`, filed at PR-open. The work is thirteen parts, each its own commit. Every commit is approved before it is made. Part 1 comes first. Parts 2 to 6 and 8 to 10 follow in any order. Part 7 comes after part 6. Part 11 follows parts 2 to 10. Part 12 follows part 11. Part 13 is last.

| Part | Scope | Spec decisions |
|---|---|---|
| 1 | Site-wide constants: `lib/engine.ts` production URL, footer reads the release tag | D3, D16 |
| 2 | Get started pages: Overview, Installation, First fusion, Quickstart (Reproduce DRACO) | D1, D2, D3, D4, D5, D6, D17, D19, D20, D21, D31 and the corrections on these pages |
| 3 | Guides: Connections, Models, Benchmarks, Evaluation, Clients, Leaderboards, Url4 | D1, D2, D7, D9, D10, D11, D12, D14, D21 and the corrections on these pages |
| 4 | API reference corrections: Clients, Connections, Models, Benchmarks, Reports, CandidateResult, Events, Errors, Modules, Leaderboards, Usage | D7, D11, D12, D15, D23 and the corrections on these pages |
| 5 | Reference for the 0.1.9 surface already documented before this pass: combinators and blocks, `Fusion(quorum=, optional=)`, accounting and trace, notices, `sf.reports`; navigation entries | D15 and the missing-surface list |
| 6 | Learn pages: Engine, Architecture, Gateway, Caching, Leaderboard, Url4 | D5, D8, D9, D12, D19, D22 and the url4 grammar correction |
| 7 | `sf.cache` and `sf.analytics` reference pages; routes and navigation | D22, D32 |
| 8 | Capture default: Caching, Evaluation guide, Leaderboards guide, Clients API, CandidateResult API | D26 |
| 9 | Reducers reference and Fusions guide: `sf.Mean`, weights, `Judge(order=)`, `Filter(judge=)`, `Pick(output=)`, `Reduce(select=)`, the selection input | D25, D27 |
| 10 | `sf.classify`, case media, Errors and Modules entries, the Benchmarks guide judge input | D28, D29, D30, D33 |
| 11 | Diagrams: six sources in `docs/diagrams/`, rendered to SVG and PNG, placed on their pages | D36 |
| 12 | Review: three passes, scorecard, trust check, report; the fixes it lists | D35, D37, D38, D39, prose rules |
| 13 | Gates, link check, search checks, PR | Acceptance |

## 2. Steps

**Start of work**

1. `git fetch origin`, then confirm the worktree for this branch is branched from `origin/main`. No edit happens in the shared checkout.
2. Keep the work ledger `docs/work/2026-10-15-docs-align-sf-client-0-1-9.md` current: status `in_progress`, outcome filled at the end.
3. Install 0.1.9 in a fresh environment: `uv venv`, then `uv pip install "screamingface[notebook,runtime]==0.1.9"`. Start the local stack with `screamingface up`.

**Per part**

1. List every statement, signature, number and id on each page in the part.
2. Check each against 0.1.9: run the sample, read the live value, or read the source. Record the result.
3. Fix the context for the page: the reader, the register and the page type. A page that serves two types is split before any content is added.
4. Edit the page. Reprint each printed output from the run. Split local and hosted into separate sections where behaviour differs. Apply the prose rules to every sentence added or changed.
5. Run the gates in `public-docs`: `npm run type-check`, `npm run lint`, `npm run build`.
6. Run the link check: every internal route resolves and every external link answers 200.
7. Show the file list, the diff summary and the exact commit message. Wait for approval. Commit.

After the last part: push after approval, file the issue under `OME-426` after confirmation, rename the branch, and open the PR with `**Refs:** OME-<N>`.

## 3. Part detail

**Part 7: `sf.cache` and `sf.analytics`**

Pages under `public-docs/src/pages/sf-client/api/`: `CachePage.vue` (title "Shared cache") and `AnalyticsPage.vue`. The cache pull needs a hosted sign-in. Its printed output comes from a pull of one model's rows into the local gateway database.

**Part 8: capture default**

The set of sentences is found by search, not by memory. Each rewritten sentence is checked with a local run: `capture_status` and `pinned_cache` are `None` without `capture=True`, and present with it.

**Part 9: reducers**

Each signature is checked by calling it on 0.1.9. Each behaviour is run once with a one-case example on the local engine, within the measurement cap.

**Part 10: classify and media**

`sf.classify` needs a text classifier on the caller's own endpoint, so a live call is not available. Case media needs an engine that parks media. Whether the local engine does is checked first. Where a sample cannot run, the page carries signatures and no printed output, and the ledger records the check that replaced the run.

**Part 11: diagrams**

Six diagrams from the spec's Diagram plan. Each has text source in `docs/diagrams/`, an SVG and a PNG, one question, and labels that match the prose. The diagramming plugin is proposed if it is absent. The existing local-flow diagram on the Overview is reviewed for current names, and corrected or deleted if stale.

**Part 12: review**

Run the three passes on the edited pages as the reader in the spec's context table. Score the nine items, each with a quoted line. Run the trust check and rewrite each failing sentence. Write the report in the required order, and record it in the ledger. Apply its top fixes in the same part.

## 4. Files

- Part 1: `public-docs/src/lib/engine.ts`, `public-docs/src/navigation/sf-client.ts`, `public-docs/vite.config.ts`, `public-docs/env.d.ts`, and the two workflows that build `public-docs`.
- Parts 2 to 4, 6, 8 to 10: the pages named in the table, under `public-docs/src/pages/`.
- Parts 5 and 7: new pages under `public-docs/src/pages/sf-client/api/`, routes in `public-docs/src/router/index.ts`, entries in `public-docs/src/navigation/sf-client.ts`.
- Part 11: `docs/diagrams/`.
- `public-docs/CLAUDE.md` is updated if a route or a page is added or removed.

## 5. Global constraints

- A statement stays only if it is true on 0.1.9. Where the team's answer describes intended behaviour (D19), the page states the intended behaviour.
- No dev host appears in any sample or sentence.
- Prose states facts. No narrative, no adjectives where a number exists, no em-dash or en-dash in any sentence added or changed.
- A page differing between local and hosted has one section for each.
- A cost claim is measured on a run or removed. A full-benchmark sample says it is paid.
- Measured runs use `limit=` and a cheap model, with a total cap of $5 on the OpenRouter key.
- No hosted call writes anything or spends hosted compute. A hosted sample prints no output that was not observed.

## 6. Verification

- Gates after each part: type-check, lint and build pass.
- Link check after each part passes.
- After the last part, a search of `public-docs/src` finds none of: `fusion.dev`, `leaderboard.dev`, a slash benchmark id, `sf.reproduce`, `hle`, `05_draco_lite_e2e`, `07_ifeval_e2e`, an em-dash, an en-dash used as a connector, `cases=`, `Fanout`, `JudgePick`.
- Every acceptance line in the spec is checked and recorded in the ledger.

## 7. Risks

- A sample cannot be run because it needs DRACO, a classifier endpoint, parked media or a provisioned hosted account. The page then states no printed output for it.
- Parts 5, 9 and 10 add reference whose behaviour is read from the source. Each documented signature is checked by calling it on 0.1.9.
- The product-context canon and the docs disagree on which benchmark ids are supported. The pass records every id it names and flags the mismatch for its owner. It does not resolve it.
