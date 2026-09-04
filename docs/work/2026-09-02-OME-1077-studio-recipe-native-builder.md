---
ticket: OME-1077
stack: screamingface-studio   # NOT yet registered in .claude/sdlc.local.md (sdlc-react); gates TBD before PR
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-02
finished:
---

# OME-1077 — Make the Studio compose builder recipe-native (solo/fusion/pipeline) with live url4

## Intent

Reshape the ScreamingFace Studio frontend so the compose panel matches ScreamingFace's real
artifacts (Solo / Fusion+required-synthesizer / Pipeline, nested arbitrarily; reduction is the
synthesizer, not a separate primitive) and generates url4 live as the user builds — plus a set
of UX improvements (nav cleanup, run controls). Frontend-only / mock this pass; url4 is a
structurally-faithful TypeScript preview, not the engine's canonical string. Delivered as
lightweight live iteration under this single ticket.

## Planned changes

**Phase 1 — quick wins**
- `src/components/app-sidebar.tsx` — remove the Scripts nav entry + badge + `useScriptStore` use
  (keep `scripts/page.tsx` + `script-store.ts` on disk). Nav → Fusions · Models · Leaderboard.
- `src/app/(studio)/models/page.tsx` — lower-right "Start building a fusion" button → `/ensembles/new/`.
- `src/app/(studio)/ensembles/new/page.tsx` — sample size 1/50/100/Custom (keep Full); add
  `useCache` + `saveCache` run toggles (saveCache defaults ON).
- `src/lib/ensemble-store.ts` — extend `SavedRun` with `useCache` / `saveCache`.

**Phase 2 — recipe-native builder + live url4** (later units in this ticket)
- New `src/lib/recipe.ts` — recursive `RecipeNode` union + `recipeToUrl4`.
- `src/lib/ensemble-store.ts` — `root: RecipeNode` + persist migration.
- New `src/components/builder/*` — recursive builder UI; remove Loop/Reduce/strategy/judge.
- New `src/lib/recipe-templates.ts` + template picker.

## Test plan

Studio has no test harness yet. Before PR: register the stack, add vitest + Testing-Library +
a `typecheck` script, then cover (RED-first): `recipeToUrl4` structural output, the
`ensemble-store` migration (legacy slots → Fusion), and builder add/nest/remove actions.
During live iteration: manual verification against the running dev server.

## Acceptance

- Nav shows only Fusions/Models/Leaderboard; `/scripts/` no longer linked.
- Models page has a lower-right "Start building a fusion" opening an empty builder.
- Sample size offers 1/50/100/Custom (+Full); cache toggles present, saveCache on by default.
- Builder is recipe-native: start from Fusion or Pipeline, nest to any depth, every Fusion has a
  required configurable synthesizer, Solo exposes model + system prompt + a Parameters drawer; a
  live url4 preview reflects the tree; templates seed prebuilt recipes. No Reduce/strategy/judge UI.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
