---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: studio frontend (apps/screamingface-studio/frontend; not on the sdlc card, gates per the plan)
status: in_progress
started: 2026-10-09
finished:
---

# studio-engine-run-client — Studio's Engine run client, url4 linking and recipe fixes

## Intent

Slice B of `docs/plan/2026-10-09-studio-compose-fusion-run.md` (umbrella ledger
`docs/work/2026-10-01-studio-compose-fusion-run.md`, epic OME-1308). **Stacked on
`studio-benchmark-picker` (slice A)**: this branch starts from `origin/studio-benchmark-picker`,
not `origin/main`, and its PR must merge after slice A's.

Studio cannot run a fusion yet: it has no client for the Engine's run protocol, it cannot link a
Candidate into a Benchmark, its `recipeToUrl4` renders params in a form url4 cannot parse
(`?k=v(<context>)`), and `?recipe=` import accepts a `url4://name?models=` form that Copy never
produces. This unit adds the run client (no UI; slice C wires it), the SDK-identical link, the
param fix, and a parser for exactly what `recipeToUrl4` emits (spec D4, D8, D9; plan U4, U5).

## Planned changes

All under `apps/screamingface-studio/frontend/`:

- `src/lib/engine/url4.ts` (new): `quoteText`, `linkCandidate` (T-B1)
- `src/lib/engine/__fixtures__/linked.json` (new): SDK-generated golden links
- `scripts/gen-link-fixtures.py` (new): regenerates the fixtures from the SDK
- `src/lib/recipe.ts`: `paramQuery` emits `?k=v&…&q=`; `parseRecipe` (T-B2)
- `src/app/(studio)/ensembles/new/page.tsx`: drop the old `parseRecipe`, import via `recipe.ts`
- `src/lib/engine/run-types.ts`, `src/lib/engine/run.ts` (new): `startRun`, `RunError` (T-B3)
- `src/lib/engine/__fixtures__/frames.ts` (new): run frames in the live wire shape
- `vitest.config.ts`: coverage include `src/lib/recipe.ts`
- Tests: `url4.test.ts`, `recipe.test.ts`, `run.test.ts`, `ensembles/new/page.test.tsx`

## Test plan

- T-B1: `linkCandidate(candidate, benchmark)` equals the SDK's `link_candidate` for a fusion with
  and without params, a pipeline and a solo; `quoteText` escapes `'` and `\`.
- T-B2: `recipeToUrl4` equals the SDK's compiled candidate text (param golden
  `/openai/gpt-4o?temperature=0.7&seed=3&q=($input)!'…'`); round trip
  `recipeToUrl4 → parseRecipe → recipeToUrl4` for fusion, pipeline and solo, with and without
  params and prompts; the old `url4://` form and a truncated string are rejected with a message.
- T-B3: the ten cases in the plan (happy path + event order; attach `from_sequence: null` and
  cache intent; `useCache: false`; 428 retry; artifact fetch; `failed benchmark_unavailable`;
  reorder / duplicate / unfilled gap; 120 s silence; abort → stop → `DELETE` after 5 s; the
  token never in an error message).
- Page: the recipe-import tests reach their fusion through canonical `recipeToUrl4` output.

## Acceptance

- `startRun` drives the Engine's real protocol (frames as checked live 2026-10-05) to a
  `CandidateResult` or a typed `RunError`; Studio's link matches the SDK byte for byte; a copied
  recipe imports back to the same url4. All frontend gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
