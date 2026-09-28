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

## Follow-on: code-review fix round (2026-09-22)

`/code-review` against `ed1c67b7..HEAD` on this branch flagged `convertKind()` in
`src/lib/recipe.ts` as data-lossy: it only preserves the outgoing node's configuration when
converting *from* a `solo` with a model set. Converting an already-configured `fusion`
(members + synthesizer) or `pipeline` (stages) to a different kind silently discards that
subtree and replaces it with blank solos, with no confirmation and a 250ms autosave that
persists the loss almost immediately.

Fix: carry over the existing `members`/`stages` (and synthesizer where the target kind still
uses one) when converting from a populated fusion/pipeline, not just from solo.

Also flagged: `buildDraft()` in `ensembles/new/page.tsx` hardcodes `strategy: "majority_vote"`
on every save — a leftover from the pre-recipe flat model — and the ensembles list page
(`ensembles/page.tsx`) renders that field as a truthful label, so every builder-created
ensemble showed "Majority Vote" regardless of what was actually built (Fusion, Pipeline,
custom synthesizer, anything).

Fix: added `describeRecipeKind(root)` to `src/lib/recipe.ts` (e.g. "Fusion · 3 members" /
"Pipeline · 4 stages") and switched the list card to derive its label from `ensemble.root`
when present, falling back to the legacy strategy-label map only for pre-recipe ensembles
that haven't been migrated (no `root` yet). The stale `strategy` field itself is left as-is
in `buildDraft`/the store — no code now trusts it as descriptive.

Also flagged: `memberSolos()`/`rootSynthesizerSolo()` in `recipe.ts` only special-cased
`fusion` roots. A `pipeline` root fell through to `collectSolos(root)` for members (every
stage lumped together as if they were parallel members) and always returned `null` for its
grader (`rootSynthesizerSolo` never recognized a pipeline's last stage). `deriveSlots`/
`deriveJudge` (`ensembles/new/page.tsx:1686-1703`) feed those straight into the RunsPanel's
member list and judge/synthesis-step display, so any Pipeline recipe's run view
misrepresented it as an ungraded parallel fusion.

Fix: `memberSolos` now treats a pipeline's stages-except-the-last as members; a new branch in
`rootSynthesizerSolo` treats the last stage as the grader (mirroring how fusion's synthesizer
is handled), returning it only when that last stage is itself a configured Solo. Verified via
a throwaway script: a 3-stage pipeline (draft/refine/grade) now reports `draft`+`refine` as
members and `grade` as the grader.

Also flagged: `draftSnapshot = JSON.stringify(draft)` (`ensembles/new/page.tsx:2293`) was a
plain assignment, not memoized, so it re-serialized the entire recipe tree on every render of
`EnsembleComposer` regardless of cause — wasted work scaling with tree size.

Fix: wrapped it in `useMemo(() => JSON.stringify(draft), [draft])`; `draft` was already
memoized, so this now only re-stringifies when the recipe/name/runHistory content actually
changes. `customReduce`/`loopScriptId` migration-loss (review finding #3) and the missing
docs/spec-plan artifact (#7) were reviewed and intentionally left open — app is unlaunched
with no real persisted data at risk for #3, and #7 is tracked separately below if pursued.

Also flagged: `NodeLabel` (recipe-tree node rename) and the `EnsembleComposer` title rename
independently reimplemented the same click-pencil→edit→Enter/Escape/blur-commits state
machine, with the two copies already drifting (propagation handling, escape behavior).

Fix: extracted a shared `useInlineRename()` hook (editing flag + Enter/Escape key handler)
used by both; each call site keeps its own markup/styling and value-transform (the title
editor still dash/lowercases as you type). Verified manually in the running dev server: the
title rename (Enter-to-commit) and a node rename (Escape-to-commit) both still work
identically post-refactor.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
