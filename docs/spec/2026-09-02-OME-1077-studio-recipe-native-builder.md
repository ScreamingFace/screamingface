---
title: OME-1077 — Studio compose builder goes recipe-native (solo/fusion/pipeline)
status: accepted
created: 2026-09-02
ticket: OME-1077
related:
  - docs/plan/2026-09-02-OME-1077-studio-recipe-native-builder.md
  - docs/work/2026-09-02-OME-1077-studio-recipe-native-builder.md
note: >
  Written retroactively (2026-09-28) to close the docs/spec + docs/plan gap flagged by a
  /code-review pass on this branch (finding #7). The design decisions below were made and
  implemented as part of OME-1077's own ticket body (single-ticket "lightweight process"
  iteration, per its own explicit decision) rather than as prior separate spec/plan artifacts;
  this file mirrors those decisions rather than inventing new ones.
---

# Studio compose builder goes recipe-native

## Decision

Reshape the Studio compose panel (`apps/screamingface-studio/frontend`) so it matches
ScreamingFace's real artifacts instead of the prior flat "Loop + Reduce / strategy / judge"
model. Per `packages/screamingface/src/screamingface/{model,fusion,pipeline}.py` and
`docs/spec/2026-08-12-OME-786-pipeline-composition.md`, a recipe is one of:

- **Solo** — a unit = one Model (route + optional system prompt + params).
- **Fusion** — parallel `members[]` + a **required** `synthesizer` (itself a Recipe).
- **Pipeline** — serial `stages[]` (only the last stage is graded).

These nest arbitrarily. There is no separate "reduce" primitive — reduction **is** the
synthesizer. "Loop" becomes self-corrective templates, not a standalone builder concept.

## Scope

**Frontend-only / mock this pass.** The url4 preview is a structurally-faithful TypeScript
preview (`recipeToUrl4` in `src/lib/recipe.ts`), not the engine's byte-canonical string —
that comes from the engine at run time. Params come from the existing static
`PARAM_CATALOG`. Runs and the leaderboard stay mock. Real engine/leaderboard/param-discovery
wiring is a later, separate effort.

**Process.** This single ticket tracks the whole effort as a lightweight live iteration —
follow-on UI tweaks (including this spec/plan backfill and a later code-review fix round)
fold into this ticket rather than spawning sub-issues, per OME-1077's own decision.

**Label.** `desktop/ensemble` is used as a temporary landing label — the Studio app has no
landing leaf of its own yet. Creating a `screamingface-studio` leaf and relabeling is a
deferred owner action.

## Contract

- `SavedEnsemble.root?: RecipeNode` is the recipe-native source of truth. It is optional so
  ensembles persisted before this rework still hydrate — migrated on load from
  `slots`/`judge` via `fusionFromSlots()` (see plan).
- `RecipeNode = SoloNode | FusionNode | PipelineNode` (`src/lib/recipe.ts`), each carrying its
  own `id` (stable across kind conversions) and optional display `name`.
- Legacy flat fields (`strategy`, `customReduce`, `reduceScriptId`, `loopMode`,
  `loopScriptId`) remain on `SavedEnsemble` for backward read-compatibility but are no longer
  the source of truth for anything the recipe-native builder renders; `slots`/`judge` are
  *derived* from `root` (`deriveSlots`/`deriveJudge`), not stored independently.

## Acceptance

- Nav shows only Fusions/Models/Leaderboard; `/scripts/` route is kept on disk but unlinked.
- Models page has a lower-right "Start building a fusion" action opening an empty builder.
- Sample size offers 1/50/100/Custom (+Full); `useCache`/`saveCache` run toggles present,
  `saveCache` on by default.
- Builder is recipe-native: start from Fusion or Pipeline, nest to any depth, every Fusion has
  a required configurable synthesizer, every Solo exposes model + system prompt + a Parameters
  drawer; a live url4 preview reflects the tree; templates seed prebuilt recipes. No
  Reduce/strategy/judge UI surfaces the legacy flat model.
- Kind conversions, list-view labeling, and run/judge derivation are consistent with the
  Solo/Fusion/Pipeline contract above for *all three* kinds, not just Fusion (closed by the
  2026-09-22 code-review fix round — see the work ledger).
