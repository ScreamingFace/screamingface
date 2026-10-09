---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: studio frontend (apps/screamingface-studio/frontend; not on the sdlc card, gates per the plan)
status: done
started: 2026-10-09
finished: 2026-10-09
---

# studio-benchmark-picker — Studio's Compose Fusion benchmark picker reads the Engine catalog

## Intent

Slice A of `docs/plan/2026-10-09-studio-compose-fusion-run.md` (umbrella ledger
`docs/work/2026-10-01-studio-compose-fusion-run.md`, epic OME-1308). The Run panel on Compose
Fusion offers five hardcoded benchmarks the Engine does not have, plus a custom upload the
Engine cannot run. This unit replaces both with the Engine's own catalog (`GET /v1/benchmarks`),
records what each benchmark needs (judge provider, web search) in a Studio presentation table
(plan U3), and clamps the sample-size presets to the chosen benchmark's case count. The
simulated run itself stays until slice C.

## Planned changes

- `frontend/src/lib/engine/types.ts`: `BenchmarkSummary`
- `frontend/src/lib/engine/client.ts`: `listBenchmarks()`
- `frontend/src/lib/benchmark-store.ts` (new): zustand store, not persisted
- `frontend/src/lib/benchmark-presentation.ts` (new): `{judgeProvider?, needsWebSearch}` table
- `frontend/src/app/(studio)/ensembles/new/page.tsx`: `RunsPanel` picker reads the store;
  hardcoded `benchmarks` and custom upload removed; presets clamped
- `frontend/vitest.config.ts`: coverage include `src/lib/benchmark-*.ts`
- Tests: `client.test.ts`, `benchmark-store.test.ts`, `benchmark-presentation.test.ts`,
  `ensembles/new/page.test.tsx`

## Test plan

- T-A1: `listBenchmarks` hits `/v1/benchmarks`; problem+json maps to an `EngineError` kind;
  fetch rejection is `unreachable`.
- T-A2: store loading→ready, loading→error, retry recovers; two concurrent `refresh()` make one
  request; presentation: draco/draco-3pass web search + openrouter judge; healthbench-* and
  gdpval-text openrouter; ifeval/medxpert/contracteval/unknown no requirements.
- T-A3: 8 options render; DRACO disabled with the Tavily label; "100" disabled for a 52-case
  fake; Custom 9999 clamps to `case_count`; error state with Retry; no Upload control.

## Acceptance

- The picker lists exactly the Engine's benchmarks, with title, focus/description and case
  count; DRACO and DRACO 3-Pass are listed but not runnable; Run is disabled until a runnable
  benchmark is chosen; presets never exceed `case_count`; loading, empty and error states each
  show an inline message. All frontend gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, all under `apps/screamingface-studio/frontend/`:
  `src/lib/engine/{types,client}.ts`, `src/lib/engine/client.test.ts`,
  `src/lib/benchmark-store.ts` + test, `src/lib/benchmark-presentation.ts` + test,
  `src/app/(studio)/ensembles/new/page.tsx` + `page.test.tsx`, `vitest.config.ts`; plus
  `src/lib/engine/oauth.test.ts` (one line: its typed fake `EngineClient` gains
  `listBenchmarks: vi.fn()`; no assertion changed). The first commit also carries the
  umbrella spec, plan and ledger (`docs/spec|plan|work/…studio-compose-fusion-run.md`).
- **Commits:**
  - 0492acd13 — docs: compose fusion run spec, plan and ledger
  - 4a0ec67c1 — feat(studio): list the Engine's benchmarks in the engine client
  - b76d06c2f — feat(studio): benchmark store and requirements table for the run picker
  - b418ee067 — feat(studio): pick a run's benchmark from the Engine catalog
- **Gates:** `npm ci && npm run lint && npm run typecheck && npm test -- --coverage && npm run
  build` all green. 11 files / 117 tests passed; coverage statements 92.47%, branches 88.88%,
  functions 92.36%, lines 93.24% (threshold 80). `benchmark-store.ts` and
  `benchmark-presentation.ts` at 100%. `next build` produced every route statically.
- **Deviations:**
  - ETag: the plan says `listBenchmarks` "supports ETag the same way `listModels` does".
    `listModels` has no ETag handling (every request is `cache: "no-store"`), so
    `listBenchmarks` has none either. The Engine sends an ETag; Studio does not use it yet.
  - Default sample size: the plan says "stays at 50"; the code defaulted to 100. It is now 50,
    as the plan says.
  - Label: the plan's U3 wording ("Needs a Tavily web-search key — not available in Studio
    yet") is used. The spec §4.4 has the older "Needs web search — …".
  - Each benchmark radio is named by its title, with the focus/description and the Tavily
    label as its accessible description (`aria-describedby`).
  - Preset and custom labels keep the existing `q` suffix (`50q`); the custom unit and the
    Full line say "cases". The run history and the simulated run (slice C replaces it) are
    unchanged apart from taking the title and the clamped size from the store.
  - No visual check against a live Engine in this unit (no runtime running here); covered by
    the slice C manual end-to-end (T-C5).
