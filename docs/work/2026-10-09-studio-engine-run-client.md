---
ticket: OME-1554
stack: studio frontend (apps/screamingface-studio/frontend; not on the sdlc card, gates per the plan)
status: done
started: 2026-10-09
finished: 2026-10-09
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

- **Actual files:** as planned, all under `apps/screamingface-studio/frontend/`, plus:
  `scripts/gen-run-frames.py` and `src/lib/engine/__fixtures__/frames.json` (frame fixtures);
  `src/lib/engine/client.ts` (exports `problemDetail` for reuse); `src/app/(studio)/ensembles/page.tsx`
  (import box) and `src/app/(studio)/models/page.tsx` + `page.test.tsx` (Compose link) — see
  Deviations.
- **Commits:**
  - 392421bb1 — feat(studio): link a candidate into a benchmark exactly as the SDK does
  - 09d863a13 — fix(studio): render params in url4 query form and import exactly what Share url4 copies
  - ad4e0621a — feat(studio): Engine run client for one benchmark run
  - 619b09edc — fix(studio): encode prompt text as url4 text the way the SDK does
- **Gates (after the prompt-encoding fix):** lint, typecheck, `npm test -- --coverage`
  (14 files / 225 tests; statements 95.64%, branches 90.77%, functions 96.39%, lines 97.22%;
  `recipe.ts` 99.56%) and `npm run build` green.
- **Gates (first three commits):** `npm ci && npm run lint && npm run typecheck && npm test -- --coverage && npm run
  build` all green. 14 files / 209 tests passed; coverage statements 95.63%, branches 90.77%,
  functions 96.38%, lines 97.21% (threshold 80). `recipe.ts` 99.56% / 96.02% branches, `run.ts`
  93.6% / 85.63% branches, `url4.ts` 100%. `next build` produced every route statically. Both
  fixture scripts reproduce the committed JSON byte for byte; `uv run --frozen` left `uv.lock`
  untouched.
- **Deviations:**
  - **Other producers of the old form.** The Models page's "Compose a Fusion" link and the
    Ensembles page's import box also used `url4://name?models=`. Deleting that parser would have
    broken Models → Compose, so the link now emits `recipeToUrl4(fusionOf(models))` (members =
    the checked models, synthesizer unset, as the old import produced) and the import box
    validates with `parseRecipe`. The leaderboard (still the mock) is unchanged: its Remix link
    and copy still emit the old form, which now shows the import's rejection message. It goes
    with the leaderboard un-mock.
  - **Name and unknown models on import.** Canonical url4 carries no fusion name, so an imported
    recipe is named `fusion-1` (the builder's default). A model the catalog lacks is left as an
    unset model in place (structure kept) and named in the existing "Left out models" status,
    instead of being removed. An unparseable `?recipe=` now shows its message in an alert.
    Page tests reach their fusion through `recipeToUrl4(fusionOf(...))`; the "shared" name
    assertions became the equivalent model-count assertions, and a new test covers the refused
    old form.
  - **Frames are generated, not captured.** No runtime was running here, so the run fixtures are
    built with url4's own protocol models and codec (exact field names, aliases and the string
    `sequence` + `sequencetype: "Integer"`), in the order and with the attributes of the live
    IFEval check. The wire `sequence` is a positive-integer string; `run.ts` accepts a string or
    a number.
  - **Error mapping.** HTTP refusals (benchmark 404/422, start 4xx) reject as `failed` with
    `code: "http_<status>"` and the Engine's detail. Any `ai.url4.error` frame (`invalid_frame`,
    `unsupported`, `stream_reclaimed`, `stream_failed`) rejects as `stream_failed` with the
    Engine's code. An unsequenced log (the SDK's "advisory" case) is reported at once.
  - **Artifact redemption.** Fetched with the run's capability, as the plan says. The SDK mints a
    fresh token for this because tokens once lived ~60 s; the Engine's capability lifetime is now
    58 800 s (`config.py` `capability_lifetime_s`), so the run's token is valid. Size and sha256
    are verified before decoding, as the SDK does.
  - `deps` also takes `clearTimeout` and `engineUrl` (default `getEngineUrl()`); every dep is
    optional. `RunEvent.cost.totalUsd` is a number parsed from the decimal-string
    `cost.total_usd`; `started` carries no payload.
  - Covering `recipe.ts` needed tests for its pre-existing helpers too (`convertKind`,
    `describeRecipe*`, `memberSolos`, `rootSynthesizerSolo`, `fusionFromSlots`); added, none
    changed.
  - TDD order: the url4 tests were run RED first; the recipe and run tests were written with
    their code and run together, not observed failing first.
  - **Prompt encoding (fixed in 619b09edc, approved follow-up; TDD order followed).** The SDK
    goldens gained prompts with a newline, `$USD`, `$input`, `$$`, `'` and `\` (fusion member,
    synthesizer, solo); those tests and the round-trip tests were run and seen failing (10
    failures) before the fix. Rules now implemented, from source:
    - encode = SDK `_url4_text`, `packages/screamingface/src/screamingface/_evaluation/candidate.py:436-447`:
      CR LF and CR → LF (:437); LF → U+2028, tab → space (:438); other control characters
      (< U+0020, U+007F) are refused by the SDK (:439-446) and dropped by Studio; `$` → `$$`
      (:447). Then url4 `_quote`, `packages/url4/src/url4/core/render.py:367-368`: `\` → `\\`,
      then `'` → `\'`.
    - decode = SDK `_python_text`, `packages/screamingface/src/screamingface/url4.py:446-447`:
      U+2028 → LF, `$$` → `$`; the Engine collapses `$$` the same way when it substitutes
      (`packages/url4/src/url4/dag/semantics/ensemble.py:20,45`).
    - Behaviour change for prompts without those characters: runs of spaces and leading or
      trailing spaces are no longer collapsed or trimmed (the SDK keeps them); a blank prompt
      renders the default prompt (it used to render `''`). Tabs, CRs and a literal U+2028 in a
      prompt do not survive a round trip, exactly as in the SDK.
