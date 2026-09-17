---
id: OME-736
linear_url: https://linear.app/openmined/issue/OME-736/unblock-the-aigateway-ui-dependency-group-pr-typescript-6-peer
status: in_review
type: task
priority: P1
labels: [aigateway, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-736 — land the aigateway-ui dependency group, hold TypeScript at 5

Sub-issue of `OME-733` (Dependabot compliance + alert burndown). Unblocks the `aigateway-ui-npm`
group, red since 2026-07-31 across three successive PRs (#457 → #472 → #477), which carries the
`react`/`react-dom` 19.2.8 security bumps.

## Root cause — the first diagnosis was wrong

**Wrong:** "stylelint 17 / eslint 10 pull a TypeScript 6 peer." Verified against the registry:
none of the group's targets constrains TypeScript at all.

**Actual:** the group itself bumps `typescript` `^5` → `^7`, and `openapi-typescript@7.13.0`
declares peer `typescript@^5.x` with **no release supporting TS 6 or 7**. TypeScript 7 is the
Go-based compiler rewrite — a real major that arrived inside a routine group PR.

## Decision

**Hold `typescript` at `^5`.** A compiler migration needs its own verification pass; letting it
ride in beside security patches is the exact failure mode `OME-737` exists to prevent.

**A second hold was then required: `eslint` stays at `^9`.** ESLint 10 crashes
`eslint-plugin-react@7.37.5` bundled inside `eslint-config-next`
(`contextOrFilename.getFilename is not a function`). `eslint-config-next` declares peer
`eslint: ">=9.0.0"` at both 16.2.12 and 16.3.0 — the range is wrong, not a version we can pick
around. Not a product decision; the combination is broken.

## Result

All gates green — `npm ci` (the failure this fixes) · lint · lint:css · typecheck · test:ci
**13 files, 218 tests passed**, all unmodified. `npm run build` compiles and prerenders all 5
routes. 0 vulnerabilities.

Four breaking majors now run the suite — vitest 3→4, jsdom 26→30, @vitejs/plugin-react 4→6,
jest-dom 6→7 — with no test changes needed.

## Findings

- Local Node v25.2.1 is unsupported by `jsdom@30` (`^22.22.2 || ^24.15.0 || >=26.0.0`). CI is
  fine — `.nvmrc` pins 22 — but local gate runs use a Node CI never sees.
- `next` 16.3.0 vs `eslint-config-next` 16.2.12 skew (pre-existing, not widened here).
- Card defect: the `aigateway-ui` stack declares no **a11y** gate, which `sdlc-react` requires.
- `openapi-typescript` is manual codegen with committed output and sits in no npm script —
  dropping it from devDependencies would remove the TS-7 blocker entirely. Left for the TS 7
  ticket.

Ledger: `docs/work/2026-08-04-OME-736-aigateway-ui-deps.md`
