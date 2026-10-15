# Align the SF Client docs with screamingface 0.1.3: plan

Status: draft · Refs: `OME-426` · Spec: `docs/spec/2026-10-15-docs-align-sf-client-0-1-3.md` (approved)
Branch: `callis/ome-426-docs-polish-pass-launch`, renamed to `OME-<N>-<description>` at PR-open.
Landing: `public-docs` only.

## 1. Shape of the delivery

One pull request and one Linear issue under `OME-426`, filed at PR-open. The work is six parts, each its own commit. Part 1 comes first, parts 2 to 4 and 6 follow in any order, and part 5 comes after part 4.

| Part | Scope | Spec decisions |
|---|---|---|
| 1 | Site-wide constants: `lib/engine.ts` production URL, footer states 0.1.3 | D3, D16 |
| 2 | Get started pages: Overview, Installation, First fusion, Quickstart (Reproduce DRACO) | D1, D2, D3, D4, D5, D6, D17, D19 and the corrections on these pages |
| 3 | Guides: Connections, Models, Benchmarks, Evaluation, Clients, Leaderboards, Url4 | D1, D2, D7, D9, D10, D11, D12, D14 and the corrections on these pages |
| 4 | API reference corrections: Clients, Connections, Models, Benchmarks, Reports, CandidateResult, Events, Errors, Modules, Leaderboards, Usage | D7, D11, D12, D15 and the corrections on these pages |
| 5 | New 0.1.3 reference: combinators and blocks, `Fusion(quorum=, optional=)`, accounting and trace, notices, `sf.reports`; navigation entries | D15 and the missing-surface list |
| 6 | Learn pages: Engine, Architecture, Gateway, Caching, Leaderboard, Url4 | D5, D8, D9, D12, D19 and the url4 grammar correction |

## 2. Steps per part

1. Install 0.1.3 in a fresh environment: `uv venv`, then `uv pip install "screamingface[notebook,runtime]==0.1.3"`. Start the local stack with `screamingface up`.
2. Read each page in the part and list every statement, sample, number and id on it.
3. Check each against 0.1.3: run the sample, read the live value, or read the source. Record the result.
4. Edit the page. Reprint each printed output from the run. Split local and hosted into separate sections where behaviour differs.
5. Run the gates in `public-docs`: `npm run type-check`, `npm run lint`, `npm run build`.
6. Build and run the link check: every internal route resolves and every external link answers 200.
7. Show the diff and commit the part. After the last part: push, file the issue under `OME-426`, open the PR with `Refs: OME-<N>`.

## 3. Files

- Part 1: `public-docs/src/lib/engine.ts`, `public-docs/src/navigation/sf-client.ts`.
- Parts 2 to 4: the pages named in the table, under `public-docs/src/pages/sf-client/`.
- Part 5: new pages under `public-docs/src/pages/sf-client/api/`, routes in `public-docs/src/router/index.ts`, entries in `public-docs/src/navigation/sf-client.ts`.
- Part 6: the pages named in the table, under `public-docs/src/pages/learn/`.
- `public-docs/CLAUDE.md` is updated if a route or a page is added or removed.

## 4. Global constraints

- A statement stays only if it is true on 0.1.3. Where the team's answer describes intended behaviour (D19), the page states the intended behaviour.
- No dev host appears in any sample or sentence.
- Prose states facts. No narrative, no adjectives where a number exists.
- A page differing between local and hosted has one section for each.

## 5. Verification

- Gates after each part: type-check, lint and build pass.
- Link check after each part passes.
- After the last part, a search of `public-docs/src` finds none of: `fusion.dev`, `leaderboard.dev`, a slash benchmark id, `sf.reproduce`, `hle`, `05_draco_lite_e2e`, `07_ifeval_e2e`.

## 6. Risks

- A sample cannot be run because it needs DRACO or a provisioned hosted account. The page then states no printed output for it.
- Part 5 adds pages whose behaviour is read from the source. Each documented signature is checked by calling it on 0.1.3.
