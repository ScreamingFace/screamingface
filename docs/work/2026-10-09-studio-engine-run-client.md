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

## Review follow-up (PR #1327)

HupBaHa's six blocking items. I checked each one against the source before changing anything,
and all six held. Item 6 turned out stricter than the review said. Tests were written first and
seen failing: 20 recipe tests, 1 page test and 33 run-client tests went RED, then GREEN. All
fixes land in one commit.

1. **The run's root node.** Verified: the SDK takes as root the `started` frame whose
   `data.url4` equals the url4 it sent. It keeps that frame's `source`, accepts result and
   terminated frames only from it, counts subtree cost only from it, and fails a `terminated`
   that arrives before the root is known (`packages/screamingface/src/screamingface/_engine/contract.py:191-199,246-279`).
   `run.ts` `dispatch` now does the same. Fixtures: `gen-run-frames.py` puts the SDK's
   `link_candidate` url4 in the root `started` frame and adds child frames
   (`childStarted/Result/Cost/Terminated`).
   - RED→GREEN: "takes the result and terminal state only from the root node", "fails a run
     whose root never started", "does not take a started frame for another url4 as the root".
   - Test setup change: "rejects a run the Engine timed out" now sends the root `started` frame
     before its `terminated` frame. Its assertion is unchanged.
2. **Bounded, cancellation-safe phases.** Each phase now has its own deadline, taken from the
   SDK:
   - A start request gets 30 s, the SDK's HTTP client timeout (`transport.py:141`). If no
     answer comes, Studio sends `DELETE` in case the run began, then rejects as `unreachable`.
     If the user had already aborted, it rejects as `stopped`, or `stop_unconfirmed` when the
     `DELETE` fails.
   - A start accepted after an abort is stopped.
   - `DELETE` gets 5 s (`_STOP_TIMEOUT_SECONDS`, `transport.py:62`). A 2xx, 404, 409 or 410
     answer counts as `stopped` (`_ALREADY_STOPPED_STATUSES`, `transport.py:64`). Any other
     answer, or no answer in time, gives the new kind `stop_unconfirmed`.
   - An artifact fetch gets 30 s per attempt, with the SDK's retry delays 0 / 200 / 800 ms
     (`transport.py:1265`). That bounds a stalled artifact at about 91 s.
   - RED→GREEN: "gives up on a start the Engine never answers and deletes the run in case it
     began", "settles an abort whose start never answers once the start deadline passes",
     "reports a stop it could not confirm when the DELETE refuses it / never answers", "does
     not wait forever on an artifact the Engine never sends".
   - These two tests passed before the fix too. They pin behaviour that was already right:
     "stops a run the Engine accepts after the user aborted" and "treats a DELETE for a run
     that is already gone as stopped".
3. **Artifact memory.** The cap is `MAX_ARTIFACT_BYTES` = 256 MiB. It is large enough for a full
   ContractEval result: 4,182 cases from a 209 MB dataset (spec D10). It also keeps the decoded
   text well below V8's maximum string length (about 512 Mi UTF-16 units), so decoding and
   `JSON.parse` cannot throw a RangeError. The Engine sets no artifact cap of its own.
   - `size_bytes` is checked before fetching.
   - If the response has a `Content-Length` and no `Content-Encoding`, the length must equal
     `size_bytes`.
   - The body is read in chunks, and the read is cancelled as soon as it passes `size_bytes`.
   - The bytes are checked against the sha256, then decoded with
     `TextDecoder("utf-8", {fatal: true})`.
   - RED→GREEN: "refuses an artifact above the browser-safe maximum without fetching it",
     "refuses a Content-Length that disagrees with the ticket before reading", "stops reading
     once the body passes the ticket's size", "refuses an artifact that is not UTF-8".
4. **Runtime check of `CandidateResult`.** The new `src/lib/engine/run-result.ts` checks the
   fields Studio reads against the Engine's models
   (`apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py:205-219,234-242,262-278,431-479`):
   - top level: `schema` v1, `benchmark_id`, `benchmark_revision`, `case_count`, `score`,
     `coverage`, `metrics`, `failures[]` (`code`, `message`), `cases[]`;
   - each case: `status`, `case_id` (integer or string), `input` (non-empty), `output`,
     `grade` (null, or `method`, `score`, `metrics`, `checks`), `failures`.
   - A bad field rejects with `RunError` kind `invalid_result` (code `invalid_result`), and the
     message names the field.
   - RED→GREEN: "rejects a result with a bad <field>, naming it" (21 cases). "accepts a null
     score and an ungraded case" is a positive control.
5. **Fusion context.** Verified: the SDK compiles a fusion's members against the fusion's own
   input, and puts that input in the synthesizer context as url4 text
   (`_evaluation/candidate.py:176-186,394-406,313-318`). `recipeToUrl4` now passes the current
   context to the members and writes `input: quoteText(context)`. The parser rebuilds chains
   against that input; this rewrote `buildTree`. There is a new SDK golden,
   `pipeline_into_fusion`.
   - RED→GREEN: "renders the SDK's compiled candidate text (pipeline_into_fusion)", "round-trips
     a pipeline into a fusion", "… with a pipeline synthesizer", "round-trips a fusion whose
     synthesizer is a fusion".
   - Not SDK-identical: in a fusion whose synthesizer is another fusion, the SDK numbers the
     outer fusion's synthesis first (`synthesis_2` for the inner synthesizer). Studio numbers in
     emit order. The context text matches. Names and topology were agreed out of scope.
6. **Parameter validation.** Verified, and stricter than the review said. url4's `param-value`
   allows only letters, digits and `. - _ , : /` (`packages/url4/src/url4/core/_annotations.py:63-67`,
   `validate_param` :107-136). The renderer refuses `,` in a query value (`url4/core/render.py:504-511`),
   and the SDK refuses `';(),&` and control characters (`_candidate_policy.py:68-77`). Because
   the SDK renders through url4 and re-parses the result (`render.py:85`), a parameter value the
   SDK can send is `[A-Za-z0-9._\-:/]+`. A value with a space, `=` or `\n` cannot be sent.
   - Keys must match `[A-Za-z0-9._]+` and must not be reserved (`_candidate_policy.py:12-28`).
   - `recipeIssues(root)` lists every bad value or key. `recipeToUrl4` throws a typed
     `RecipeError` that carries the issues. `renderRecipe(root)` returns them for the UI.
   - The builder shows the issues in place of the url4 preview and disables Share url4.
     `parseRecipe` rejects them.
   - New SDK golden `params_text`: `stop=END:of/answer-1.0_x&reasoning_effort=high&logprobs=true`.
   - RED→GREEN: "reports a value with an ampersand / a comma / parentheses / a semicolon / a
     quote / a space / a backslash escape / a newline / a control character / an equals sign
     instead of emitting it", "reports a name with a space / a dash / a reserved name / another
     reserved name", "accepts every value url4 carries unquoted, and skips unfinished rows",
     "refuses to import a parameter value url4 cannot carry", and the page test "shows a
     parameter url4 cannot carry and will not share the recipe".
   - Product note: because of these url4 rules, the builder's `stop` field cannot hold a
     typical stop sequence such as `\n\n` or a phrase with spaces. Supporting that would need
     quoted parameter values in the SDK or the url4 grammar.

**Gates:** lint, typecheck, `npm test -- --coverage` (14 files / 288 tests; statements 95.09%,
branches 90.34%, functions 96.56%, lines 96.78%; `recipe.ts` 98.9%, `run.ts` 92.0%,
`run-result.ts` 98.2%) and `npm run build` all pass. Both fixture scripts regenerate the
committed JSON byte for byte, and `uv run --frozen` left every lockfile untouched.
