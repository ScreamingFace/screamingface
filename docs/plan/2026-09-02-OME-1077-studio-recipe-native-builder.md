# Plan — OME-1077: Studio compose builder goes recipe-native

Spec: `docs/spec/2026-09-02-OME-1077-studio-recipe-native-builder.md`.

Written retroactively (2026-09-28) alongside the spec, mirroring the ledger
(`docs/work/2026-09-02-OME-1077-studio-recipe-native-builder.md`) and the actual commit
history on this branch rather than a plan written in advance.

## Phase 1 — quick wins

1. `src/components/app-sidebar.tsx` — remove the Scripts nav entry + badge +
   `useScriptStore` use (keep `scripts/page.tsx` + `script-store.ts` on disk).
2. `src/app/(studio)/models/page.tsx` — lower-right "Start building a fusion" button →
   `/ensembles/new/`.
3. `src/app/(studio)/ensembles/new/page.tsx` — sample size 1/50/100/Custom (keep Full); add
   `useCache` + `saveCache` run toggles (`saveCache` defaults ON).
4. `src/lib/ensemble-store.ts` — extend `SavedRun` with `useCache`/`saveCache`.

## Phase 2 — recipe-native builder + live url4

1. `src/lib/recipe.ts` — recursive `RecipeNode` union (`SoloNode`/`FusionNode`/
   `PipelineNode`), factories (`createSolo`/`createFusion`/`createPipeline`), `convertKind`,
   traversal (`collectSolos`/`memberSolos`/`rootSynthesizerSolo`), legacy migration
   (`fusionFromSlots`), and `recipeToUrl4`.
2. `src/lib/ensemble-store.ts` — `SavedEnsemble.root?: RecipeNode`, read-compatible with
   pre-rework saves (no destructive migration on read).
3. `src/app/(studio)/ensembles/new/page.tsx` — recursive builder UI (kind switcher,
   add/nest/remove members & stages, required synthesizer slot, Solo params drawer from
   `PARAM_CATALOG`); canvas zoom/pan; per-node rename; `deriveSlots`/`deriveJudge` feed the
   existing mock Runs panel from the tree.
4. Template gallery seeding prebuilt nested recipes (including self-corrective patterns).

## Follow-on — code-review fix round (2026-09-22, same ticket)

A `/code-review` pass against this branch (`ed1c67b7..HEAD`) surfaced correctness gaps in the
Phase 2 implementation, fixed under this same ticket per its "fold in, don't spawn
sub-issues" decision:

1. `convertKind()` — carry a populated fusion/pipeline's members/stages (and fusion
   synthesizer) across kind changes instead of discarding them.
2. Ensembles list — derive its label from the recipe tree (`describeRecipeKind`) instead of
   a hardcoded `strategy: "majority_vote"`.
3. `memberSolos()`/`rootSynthesizerSolo()` — pipeline-aware: treat a pipeline's last stage as
   its grader, earlier stages as members (mirrors fusion's member/synthesizer split).
4. Memoize the autosave dirty-check (`draftSnapshot`) to avoid re-stringifying the recipe
   tree on every unrelated render.
5. Extract a shared `useInlineRename()` local helper for the two rename controls (node label,
   ensemble title) that had drifted while independently reimplementing the same interaction.

Deliberately left open (see ledger for reasoning): the legacy-migration field-loss finding
(`customReduce`/`loopScriptId` dropped by `fusionFromSlots`) — the app is unlaunched with no
real persisted data at risk, so there is nothing to lose yet; and this spec/plan backfill
itself (finding #7), closed by this pair of files.

## Verification

- `npx tsc --noEmit` and `npx eslint` clean on every touched file (Studio has no registered
  `typecheck`/`test` script yet — see spec's Scope note on the deferred test harness).
- Manual verification against the running dev server for each UI-visible change (rename
  controls, list labels, pipeline run-panel derivation).
- No automated test suite exists for this stack yet; standing one up (vitest + Testing
  Library, `recipeToUrl4` structural coverage, `ensemble-store` migration coverage, builder
  add/nest/remove coverage) remains deferred to before this stack is registered in
  `.claude/sdlc.local.md`, per the ticket's own explicit deferral.
